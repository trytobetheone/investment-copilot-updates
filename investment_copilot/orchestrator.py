from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from agents import Runner

from .agents import bear_agent, cio_agent, compliance_agent, factcheck_agent, macro_agent, product_agent, suitability_agent
from .config import settings
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


async def _run(profile: ClientProfile, cb: ProgressCallback = None) -> AnalysisRecord:
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError("OpenAI API key not configured. Open Settings in the app and save a key first.")
    os.environ["OPENAI_API_KEY"] = api_key
    profile_json = profile.model_dump_json(indent=2)

    _emit(cb, "round1", "거시·상품·고객적합성 에이전트를 서로 독립적으로 실행 중")
    macro_task = Runner.run(macro_agent(), f"Today's UTC date is {datetime.now(timezone.utc).date()}. Client context:\n{profile_json}")
    product_task = Runner.run(product_agent(), f"Today's UTC date is {datetime.now(timezone.utc).date()}. Client context:\n{profile_json}")
    suitability_task = Runner.run(suitability_agent(), f"Review this client profile exactly as supplied:\n{profile_json}")
    macro_result, product_result, suitability_result = await asyncio.gather(macro_task, product_task, suitability_task)
    macro = macro_result.final_output
    product = product_result.final_output
    suitability = suitability_result.final_output

    _emit(cb, "construction", "AI가 정한 상품군을 사용해 로컬 엔진이 C1/C2/C3 비중을 계산 중")
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

    _emit(cb, "review", "Bear·Fact Check·Compliance 세 팀이 후보를 교차검증 중")
    bear_task = Runner.run(bear_agent(), review_packet)
    fact_task = Runner.run(factcheck_agent(), review_packet)
    compliance_task = Runner.run(compliance_agent(), review_packet)
    bear_result, fact_result, compliance_result = await asyncio.gather(bear_task, fact_task, compliance_task)
    bear, factcheck, compliance = bear_result.final_output, fact_result.final_output, compliance_result.final_output

    _emit(cb, "cio", "CIO가 검증 완료 후보 중 하나를 선택하거나 사람 검토로 보류 중")
    final_packet = review_packet + f"""

BEAR REVIEW
{_json(bear)}

FACT CHECK
{_json(factcheck)}

COMPLIANCE REVIEW
{_json(compliance)}

IMPORTANT: select only C1/C2/C3 or HUMAN_REVIEW_REQUIRED. Do not change any allocation.
"""
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
