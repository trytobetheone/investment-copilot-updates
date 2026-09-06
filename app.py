from __future__ import annotations

import pandas as pd
import streamlit as st

from investment_copilot.config import settings
from investment_copilot.db import Database
from investment_copilot.orchestrator import run_investment_committee
from investment_copilot.reports import build_html_report, selected_candidate, selected_quant
from investment_copilot.schema import ClientProfile, Holding
from investment_copilot.secrets import get_openai_api_key, save_openai_api_key
from investment_copilot.updater import (
    check_for_update, current_version, download_update, launch_updater_and_exit,
    load_update_config, save_update_config, stage_update,
)

st.set_page_config(page_title="Investment Committee Copilot", page_icon="📊", layout="wide")

db = Database()


def profile_to_df(profile: ClientProfile | None) -> pd.DataFrame:
    if not profile or not profile.holdings:
        return pd.DataFrame([{"ticker": "", "name": "", "asset_class": "", "currency": "USD", "weight": 0.0}])
    return pd.DataFrame([h.model_dump() for h in profile.holdings])


def df_to_holdings(df: pd.DataFrame) -> list[Holding]:
    out: list[Holding] = []
    for _, row in df.fillna("").iterrows():
        ticker = str(row.get("ticker", "")).strip()
        if not ticker:
            continue
        try:
            weight = float(row.get("weight", 0) or 0)
        except Exception:
            weight = 0.0
        out.append(Holding(
            ticker=ticker,
            name=str(row.get("name", "")),
            asset_class=str(row.get("asset_class", "Other") or "Other"),
            currency=str(row.get("currency", "USD") or "USD"),
            weight=weight,
        ))
    return out


def render_record(record):
    st.subheader("CIO 최종판정")
    if record.final.decision == "SELECT":
        st.success(f"선택: {record.final.selected_candidate_id} · 판단 신뢰도 {record.final.confidence_pct}%")
    else:
        st.warning(f"HUMAN REVIEW REQUIRED · 판단 신뢰도 {record.final.confidence_pct}%")

    for reason in record.final.rationale:
        st.markdown(f"- {reason}")

    selected = selected_candidate(record)
    quant = selected_quant(record)

    if selected:
        st.subheader(f"최종 포트폴리오 · {selected.label}")
        alloc = pd.DataFrame([a.model_dump() for a in selected.allocations])
        st.dataframe(alloc[["ticker", "name", "asset_class", "currency", "weight", "role"]], use_container_width=True, hide_index=True)
        st.bar_chart(alloc.set_index("ticker")["weight"])

    if quant:
        m = quant.metrics
        cols = st.columns(5)
        cols[0].metric("과거 연환산수익률", "-" if m.annualized_return_pct is None else f"{m.annualized_return_pct:.2f}%")
        cols[1].metric("과거 변동성", "-" if m.annualized_volatility_pct is None else f"{m.annualized_volatility_pct:.2f}%")
        cols[2].metric("Sharpe", "-" if m.sharpe_ratio is None else f"{m.sharpe_ratio:.2f}")
        cols[3].metric("MDD", "-" if m.max_drawdown_pct is None else f"{m.max_drawdown_pct:.2f}%")
        cols[4].metric("95% 일간 CVaR", "-" if m.cvar_95_daily_pct is None else f"{m.cvar_95_daily_pct:.2f}%")
        st.caption(f"가격데이터 {m.data_start} ~ {m.data_end}, 관측치 {m.observations}. 과거 통계이며 예측값이 아닙니다.")
        if m.warnings:
            st.warning("정량 데이터 경고: " + " / ".join(m.warnings))

    with st.expander("3개 후보 비교", expanded=True):
        rows = []
        qmap = {q.candidate_id: q.metrics for q in record.quant_results}
        for c in record.candidates.candidates:
            m = qmap.get(c.candidate_id)
            rows.append({
                "후보": c.candidate_id,
                "성격": c.label,
                "과거수익률%": getattr(m, "annualized_return_pct", None),
                "변동성%": getattr(m, "annualized_volatility_pct", None),
                "MDD%": getattr(m, "max_drawdown_pct", None),
                "Sharpe": getattr(m, "sharpe_ratio", None),
                "Quant상태": getattr(m, "status", None),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        with st.expander("Macro Agent"):
            st.write(record.macro.regime_summary)
            for x in record.macro.key_risks:
                st.markdown(f"- {x}")
            st.caption(f"confidence: {record.macro.confidence}")
        with st.expander("Product Agent"):
            st.write(record.product.summary)
            for p in record.product.products:
                st.markdown(f"- **{p.ticker}** · {p.name} · {p.asset_class} · {p.why_fit}")
            for r in record.product.red_flags:
                st.markdown(f"⚠️ {r}")
        with st.expander("Suitability Agent"):
            st.write(f"Status: **{record.suitability.status}**")
            if record.suitability.missing_information:
                st.write("Missing:")
                st.write(record.suitability.missing_information)
            st.write(record.suitability.suitability_notes)
    with c2:
        with st.expander("Bear Agent", expanded=True):
            st.write(f"Risk: **{record.bear.overall_risk}**")
            for x in record.bear.strongest_objections:
                st.markdown(f"- {x}")
            st.write("Failure scenarios")
            for x in record.bear.failure_scenarios:
                st.markdown(f"- {x}")
        with st.expander("Fact Checker", expanded=True):
            st.write(f"Overall: **{record.factcheck.overall_status}**")
            fact_rows = [x.model_dump() for x in record.factcheck.items]
            if fact_rows:
                st.dataframe(pd.DataFrame(fact_rows), use_container_width=True, hide_index=True)
            if record.factcheck.product_red_flags:
                st.warning(" / ".join(record.factcheck.product_red_flags))
        with st.expander("Compliance / Process"):
            st.write(f"Status: **{record.compliance.status}**")
            for x in record.compliance.issues:
                st.markdown(f"- {x}")
            st.write("Human checks:", record.compliance.required_human_checks)

    st.subheader("모니터링 규칙")
    for x in record.final.monitoring_triggers:
        st.markdown(f"- {x}")
    st.write("**Rebalancing:**", record.final.rebalancing_rule)

    html_report = build_html_report(record)
    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "HTML 투자위원회 보고서 다운로드",
            data=html_report.encode("utf-8"),
            file_name=f"IC_{record.client_profile.client_code}_{record.created_at.date()}.html",
            mime="text/html",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "전체 감사로그 JSON 다운로드",
            data=record.model_dump_json(indent=2).encode("utf-8"),
            file_name=f"IC_{record.client_profile.client_code}_{record.created_at.date()}.json",
            mime="application/json",
            use_container_width=True,
        )


st.title("📊 Investment Committee Copilot")
st.caption("독립 리서치 → 후보생성 → 로컬 정량검증 → Bear/Fact/Compliance 교차검증 → CIO 선택")
st.info("고객 실명·주민번호·계좌번호는 입력하지 말고 Client Code를 쓰는 것을 권장합니다. 이 앱은 거래를 자동 실행하지 않습니다.")

page = st.sidebar.radio("메뉴", ["고객 & 분석", "분석 기록", "설정", "업데이트"])
st.sidebar.caption(f"Version: {current_version()}\n\nMain model: {settings.main_model}\n\nFast model: {settings.fast_model}")

if page == "업데이트":
    st.header("업데이트")
    st.write(f"현재 버전: **{current_version()}**")
    cfg = load_update_config()
    manifest_url = st.text_input(
        "업데이트 채널(manifest URL)",
        value=str(cfg.get("manifest_url") or ""),
        placeholder="https://raw.githubusercontent.com/.../update_manifest.json",
        help="한 번 연결하면 이후에는 이 주소를 통해 새 버전을 자동 확인합니다.",
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("업데이트 채널 저장", use_container_width=True):
            save_update_config(manifest_url)
            st.success("업데이트 채널을 저장했습니다. 고객 DB와 API key에는 영향이 없습니다.")
    with c2:
        check = st.button("새 버전 확인", type="primary", use_container_width=True)

    if check:
        info = check_for_update()
        st.session_state["update_info"] = info

    info = st.session_state.get("update_info")
    if info:
        if info.error:
            st.warning(info.error)
        elif not info.available:
            st.success(f"최신 버전입니다. ({info.current_version})")
        else:
            st.info(f"새 버전 **{info.latest_version}** 사용 가능 · 현재 {info.current_version}")
            if info.notes:
                st.markdown("**변경사항**")
                for note in info.notes:
                    st.markdown(f"- {note}")
            st.warning("업데이트 직전 고객 DB와 분석기록을 자동 백업합니다. 업데이트 중 앱이 한 번 종료되고 자동 재실행됩니다.")
            if st.button(f"⬆️ {info.latest_version} 지금 업데이트", type="primary", use_container_width=True):
                try:
                    with st.spinner("업데이트 파일 다운로드 및 무결성 확인 중..."):
                        zpath = download_update(info)
                        stage_update(info, zpath)
                    st.success("다운로드 완료. 앱을 종료하고 업데이트를 적용합니다...")
                    launch_updater_and_exit()
                except Exception as exc:
                    st.error(f"업데이트 준비 실패: {exc}")

    st.divider()
    st.caption("업데이트 시 보존: data/ 전체(고객 DB·분석기록·업데이트 설정), Windows Credential Manager의 OpenAI API key, .env. 코드와 requirements만 교체합니다. 실패하면 backups/의 직전 상태로 자동 복구합니다.")

elif page == "설정":
    st.header("설정")
    configured = bool(get_openai_api_key())
    st.write("OpenAI API key:", "✅ 저장됨" if configured else "❌ 미설정")
    new_key = st.text_input("새 API key", type="password", placeholder="sk-...")
    if st.button("Windows Credential Manager에 저장", type="primary"):
        try:
            save_openai_api_key(new_key)
            st.success("저장했습니다. API key는 앱 DB가 아니라 OS 자격 증명 저장소를 사용합니다.")
        except Exception as exc:
            st.error(str(exc))
    st.markdown("""
**기본 안전장치**
- 고객 프로필은 로컬 SQLite에 저장됩니다.
- API key는 가능한 경우 OS keyring에 저장합니다.
- 최종 CIO는 정량검증이 끝난 C1/C2/C3만 선택할 수 있습니다.
- Suitability / Fact Check / Compliance 중 FAIL이 있으면 자동으로 Human Review로 바뀝니다.
- 자동매매/주문 전송 기능은 포함하지 않았습니다.
""")

elif page == "분석 기록":
    st.header("분석 기록")
    clients = db.list_clients()
    chosen = st.selectbox("고객 필터", ["전체"] + clients)
    rows = db.list_analyses(None if chosen == "전체" else chosen)
    if not rows:
        st.info("아직 저장된 분석이 없습니다.")
    else:
        table = pd.DataFrame([
            {
                "id": r["id"],
                "client_code": r["client_code"],
                "created_at": r["created_at"],
                "decision": r["record"]["final"]["decision"],
                "selected": r["record"]["final"].get("selected_candidate_id"),
                "confidence": r["record"]["final"]["confidence_pct"],
            }
            for r in rows
        ])
        st.dataframe(table, use_container_width=True, hide_index=True)
        ids = [r["id"] for r in rows]
        rid = st.selectbox("상세보기 ID", ids)
        rec = db.get_analysis(int(rid))
        if rec:
            render_record(rec)

else:
    st.header("고객 프로필 & 새 투자위원회")
    clients = db.list_clients()
    mode = st.radio("프로필", ["새 고객", "기존 고객"], horizontal=True)
    existing = None
    if mode == "기존 고객" and clients:
        code = st.selectbox("Client Code", clients)
        existing = db.get_client(code)
    elif mode == "기존 고객" and not clients:
        st.info("저장된 고객이 없습니다. 새 고객으로 입력하세요.")

    e = existing
    c1, c2, c3 = st.columns(3)
    with c1:
        client_code = st.text_input("Client Code", value=e.client_code if e else "CLIENT_001")
        assets = st.number_input("투자가능자산", min_value=1.0, value=float(e.investable_assets) if e else 300_000_000.0, step=10_000_000.0)
        currencies = ["KRW", "USD", "JPY", "EUR"]
        base_currency = st.selectbox("기준통화", currencies, index=currencies.index(e.base_currency) if e and e.base_currency in currencies else 0)
    with c2:
        horizon = st.number_input("투자기간(년)", min_value=1, max_value=60, value=e.horizon_years if e else 5)
        max_loss = st.slider("감내 가능한 최대손실(%)", 1, 80, int(e.max_tolerable_loss_pct) if e else 20)
        min_liq = st.slider("최소 유동성/현금성 비중(%)", 0, 100, int(e.minimum_liquidity_pct) if e else 10)
    with c3:
        target_default = 0.0 if not e or e.target_return_pct is None else float(e.target_return_pct)
        target = st.number_input("목표 연수익률(%, 0=미지정)", min_value=0.0, max_value=50.0, value=target_default, step=0.5)
        levels = ["low", "medium", "high"]
        experience = st.selectbox("투자경험", levels, index=levels.index(e.experience_level) if e else 1)
        tax_priority = st.selectbox("세후효율 중요도", levels, index=levels.index(e.tax_priority) if e else 1)

    restrictions = st.text_area("금지/제약 자산", value=e.restrictions if e else "예: 레버리지 ETF 금지, PTP 금지")
    preferences = st.text_area("선호", value=e.preferences if e else "예: 한국/미국 상장 ETF 선호, 배당보다 총수익 우선")
    notes = st.text_area("기타 고객 메모", value=e.notes if e else "")

    st.subheader("현재 보유자산 (선택)")
    st.caption("Yahoo Finance 형식 티커를 사용합니다. 한국 거래소 예: 005930.KS. CASH는 현금으로 처리합니다.")
    edited = st.data_editor(
        profile_to_df(e),
        num_rows="dynamic",
        use_container_width=True,
        column_config={"weight": st.column_config.NumberColumn("weight", min_value=0.0, max_value=100.0, step=0.5)},
        key=f"holdings_{client_code}",
    )

    profile = ClientProfile(
        client_code=client_code.strip(),
        base_currency=base_currency,
        investable_assets=assets,
        horizon_years=int(horizon),
        max_tolerable_loss_pct=float(max_loss),
        minimum_liquidity_pct=float(min_liq),
        target_return_pct=None if target == 0 else float(target),
        experience_level=experience,
        tax_priority=tax_priority,
        restrictions=restrictions,
        preferences=preferences,
        notes=notes,
        holdings=df_to_holdings(edited),
    )

    b1, b2 = st.columns([1, 2])
    with b1:
        if st.button("프로필 저장", use_container_width=True):
            db.upsert_client(profile)
            st.success("로컬 DB에 저장했습니다.")
    with b2:
        can_run = bool(get_openai_api_key())
        if not can_run:
            st.warning("먼저 설정 메뉴에서 OpenAI API key를 저장하세요.")
        run = st.button("🚀 투자위원회 실행", type="primary", use_container_width=True, disabled=not can_run)

    if run:
        db.upsert_client(profile)
        status = st.status("투자위원회 시작", expanded=True)

        def progress(step: str, detail: str):
            status.write(f"**{step}** · {detail}")

        try:
            record = run_investment_committee(profile, progress)
            analysis_id = db.save_analysis(record)
            status.update(label=f"완료 · 분석 ID {analysis_id}", state="complete", expanded=False)
            render_record(record)
        except Exception as exc:
            status.update(label="분석 실패", state="error", expanded=True)
            st.exception(exc)
            st.info("네트워크/API key/모델 접근권한/market-data ticker 형식을 확인하세요. 실패한 실행은 분석 기록에 저장하지 않습니다.")
