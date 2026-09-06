from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from agents import Runner

from .agents import bear_agent, cio_agent, compliance_agent, factcheck_agent, macro_agent, product_agent, suitability_agent
from .ai_backend import load_ai_config, needs_openai_api, resolve_local_model, run_local_structured
from .config import settings
from .local_research import build_market_snapshot, build_product_catalog
from .quant import analyze_candidates, construct_candidates
from .schema import AnalysisRecord, ClientProfile
from .secrets import get_openai_api_key

ProgressCallback = Callable[[str, str], None] | None


def _emit(cb: ProgressCallback, step: str, detail: str) -> None:
    if cb:
        cb(step, detail)


def _json(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


async def _run_local_agent(ai_cfg: Any, agent: Any, prompt: str):
    instructions = agent.instructions if isinstance(agent.instructions, str) else str(agent.instructions)
    output_type = agent.output_type
    if output_type is None:
        raise RuntimeError(f"LOCAL agent {agent.name} has no structured output type.")
    return await run_local_structured(
        ai_cfg,
        instructions=instructions,
        prompt=prompt,
        output_type=output_type,
    )


def _configure_openai_if_needed(mode: str) -> None:
    if not needs_openai_api(mode):
        return
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "이 AI 모드는 OpenAI API key가 필요합니다. 설정에서 API key를 저장하거나 LOCAL 모드로 변경하세요."
        )
    os.environ["OPENAI_API_KEY"] = api_key


async def _run_local_round1(profile: ClientProfile, profile_json: str, ai_cfg: Any, cb: ProgressCallback):
    _emit(cb, "local-data", "Yahoo Finance 벤치마크로 로컬 시장 스냅샷을 만드는 중")
    snapshot = await asyncio.to_thread(build_market_snapshot, 2)
    catalog = build_product_catalog(profile)

    _emit(cb, "round1-local", "LOCAL Macro Agent 실행 중 (외부 AI API 사용 없음)")
    macro_prompt = f"""
Today's UTC date is {datetime.now(timezone.utc).date()}.
CLIENT PROFILE
{profile_json}

LOCAL MARKET SNAPSHOT
{_json(snapshot)}

Important: You have no web access. Use only this snapshot for current market observations.
"""
    macro = await _run_local_agent(ai_cfg, macro_agent(web_enabled=False), macro_prompt)

    _emit(cb, "round1-local", "LOCAL Product Agent 실행 중 (고정 검증 카탈로그에서만 선택)")
    product_prompt = f"""
CLIENT PROFILE
{profile_json}

LOCAL PRODUCT CATALOG
{_json(catalog)}

Select 4-8 products ONLY from the catalog. Do not invent products, fees, tax facts, or URLs.
"""
    product = await _run_local_agent(ai_cfg, product_agent(web_enabled=False), product_prompt)

    _emit(cb, "round1-local", "LOCAL Suitability Agent 실행 중")
    suitability = await _run_local_agent(ai_cfg, suitability_agent(), f"Review this client profile exactly as supplied:\n{profile_json}")
    return macro, product, suitability, snapshot, catalog


async def _run_cloud_round1(profile_json: str, cb: ProgressCallback):
    _emit(cb, "round1-cloud", "거시·상품·고객적합성 에이전트를 OpenAI로 독립 실행 중")
    macro_task = Runner.run(macro_agent(), f"Today's UTC date is {datetime.now(timezone.utc).date()}. Client context:\n{profile_json}")
    product_task = Runner.run(product_agent(), f"Today's UTC date is {datetime.now(timezone.utc).date()}. Client context:\n{profile_json}")
    suitability_task = Runner.run(suitability_agent(), f"Review this client profile exactly as supplied:\n{profile_json}")
    macro_result, product_result, suitability_result = await asyncio.gather(macro_task, product_task, suitability_task)
    return macro_result.final_output, product_result.final_output, suitability_result.final_output


async def _run_hybrid_round1(profile_json: str, ai_cfg: Any, cb: ProgressCallback):
    _emit(cb, "round1-hybrid", "Macro/Product는 웹 리서치, Suitability는 LOCAL 모델로 실행 중")
    macro_task = Runner.run(macro_agent(), f"Today's UTC date is {datetime.now(timezone.utc).date()}. Client context:\n{profile_json}")
    product_task = Runner.run(product_agent(), f"Today's UTC date is {datetime.now(timezone.utc).date()}. Client context:\n{profile_json}")
    macro_result, product_result = await asyncio.gather(macro_task, product_task)
    suitability = await _run_local_agent(ai_cfg, suitability_agent(), f"Review this client profile exactly as supplied:\n{profile_json}")
    return macro_result.final_output, product_result.final_output, suitability


async def _run(profile: ClientProfile, cb: ProgressCallback = None) -> AnalysisRecord:
    ai_cfg = load_ai_config()
    mode = ai_cfg.mode.upper()
    _configure_openai_if_needed(mode)

    if mode in {"LOCAL", "HYBRID"}:
        _emit(cb, "local-ai", "LM Studio 로컬 모델 연결 확인 중")
        local_model_id = resolve_local_model(ai_cfg)
        _emit(cb, "local-ai", f"로컬 모델 연결됨: {local_model_id}")

    profile_json = profile.model_dump_json(indent=2)
    local_snapshot: dict[str, Any] | None = None
    local_catalog: list[dict[str, Any]] | None = None

    if mode == "LOCAL":
        macro, product, suitability, local_snapshot, local_catalog = await _run_local_round1(profile, profile_json, ai_cfg, cb)
    elif mode == "HYBRID":
        macro, product, suitability = await _run_hybrid_round1(profile_json, ai_cfg, cb)
    else:
        macro, product, suitability = await _run_cloud_round1(profile_json, cb)

    _emit(cb, "construction", "상품군을 사용해 로컬 Python 엔진이 C1/C2/C3 비중을 계산 중")
    candidates = await asyncio.to_thread(construct_candidates, profile, product, macro, settings.price_history_years)

    _emit(cb, "quant", "후보별 기준통화 환산 가격으로 수익·변동성·MDD·VaR/CVaR 계산 중")
    quant_results = await asyncio.to_thread(
        analyze_candidates,
        candidates.candidates,
        profile.base_currency,
        settings.price_history_years,
        settings.risk_free_rate_pct,
    )

    review_packet = f"""
AI MODE
{mode}

CLIENT PROFILE
{profile_json}

MACRO REPORT
{_json(macro)}

PRODUCT UNIVERSE
{_json(product)}

SUITABILITY REPORT
{_json(suitability)}

DETERMINISTIC CANDIDATES (weights were set by local Python, not by an LLM)
{_json(candidates)}

LOCAL QUANT RESULTS (authoritative for historical numerical metrics; base currency={profile.base_currency})
{_json(quant_results)}
"""
    if mode == "LOCAL":
        review_packet += f"""

LOCAL MARKET SNAPSHOT
{_json(local_snapshot)}

LOCAL PRODUCT CATALOG
{_json(local_catalog)}
"""

    if mode == "LOCAL":
        _emit(cb, "review-local", "LOCAL Bear Agent 실행 중")
        bear = await _run_local_agent(ai_cfg, bear_agent(local_mode=True), review_packet)
        _emit(cb, "review-local", "LOCAL Fact Checker 실행 중 (웹 검증 아님)")
        factcheck = await _run_local_agent(ai_cfg, factcheck_agent(web_enabled=False), review_packet)
        _emit(cb, "review-local", "LOCAL Compliance Agent 실행 중")
        compliance = await _run_local_agent(ai_cfg, compliance_agent(local_mode=True), review_packet)
    elif mode == "HYBRID":
        _emit(cb, "review-hybrid", "Bear/Compliance는 LOCAL, Fact Check만 웹 리서치로 실행 중")
        bear = await _run_local_agent(ai_cfg, bear_agent(local_mode=True), review_packet)
        fact_result = await Runner.run(factcheck_agent(), review_packet)
        factcheck = fact_result.final_output
        compliance = await _run_local_agent(ai_cfg, compliance_agent(local_mode=True), review_packet)
    else:
        _emit(cb, "review-cloud", "Bear·Fact Check·Compliance 세 팀을 OpenAI로 교차검증 중")
        bear_task = Runner.run(bear_agent(), review_packet)
        fact_task = Runner.run(factcheck_agent(), review_packet)
        compliance_task = Runner.run(compliance_agent(), review_packet)
        bear_result, fact_result, compliance_result = await asyncio.gather(bear_task, fact_task, compliance_task)

    if mode == "CLOUD":
        bear, factcheck, compliance = bear_result.final_output, fact_result.final_output, compliance_result.final_output

    _emit(cb, "cio", f"CIO 최종판정 실행 중 ({'LOCAL' if mode in {'LOCAL','HYBRID'} else 'OpenAI'})")
    final_packet = review_packet + f"""

BEAR REVIEW
{_json(bear)}

FACT CHECK
{_json(factcheck)}

COMPLIANCE REVIEW
{_json(compliance)}

IMPORTANT: select only C1/C2/C3 or HUMAN_REVIEW_REQUIRED. Do not change any allocation.
"""
    if mode in {"LOCAL", "HYBRID"}:
        final = await _run_local_agent(ai_cfg, cio_agent(local_mode=True), final_packet)
    else:
        final_result = await Runner.run(cio_agent(), final_packet)
        final = final_result.final_output

    valid_ids = {c.candidate_id for c in candidates.candidates}
    if final.decision == "SELECT" and final.selected_candidate_id not in valid_ids:
        final.decision = "HUMAN_REVIEW_REQUIRED"
        final.selected_candidate_id = None
        final.rationale.insert(0, "System guardrail: CIO returned an invalid candidate ID.")
        final.confidence_pct = min(final.confidence_pct, 25)

    if compliance.status == "FAIL" or suitability.status == "FAIL" or factcheck.overall_status == "FAIL":
        final.decision = "HUMAN_REVIEW_REQUIRED"
        final.selected_candidate_id = None
        final.rationale.insert(0, "System guardrail: a mandatory review gate failed.")
        final.confidence_pct = min(final.confidence_pct, 40)

    selected_quant = next((q.metrics for q in quant_results if q.candidate_id == final.selected_candidate_id), None)
    if selected_quant and selected_quant.status == "FAILED":
        final.decision = "HUMAN_REVIEW_REQUIRED"
        final.selected_candidate_id = None
        final.rationale.insert(0, "System guardrail: selected candidate has failed quantitative validation.")
        final.confidence_pct = min(final.confidence_pct, 30)

    return AnalysisRecord(
        created_at=datetime.now(timezone.utc), client_profile=profile, macro=macro, product=product,
        suitability=suitability, candidates=candidates, quant_results=quant_results,
        bear=bear, factcheck=factcheck, compliance=compliance, final=final,
    )


def run_investment_committee(profile: ClientProfile, cb: ProgressCallback = None) -> AnalysisRecord:
    return asyncio.run(_run(profile, cb))
