from __future__ import annotations

import html
from datetime import timezone

from .schema import AnalysisRecord, CandidatePortfolio, CandidateQuantResult


ASSET_LABELS = {
    "US_EQUITY": "미국 주식", "KR_EQUITY": "한국 주식", "DM_EQUITY": "선진국 주식", "EM_EQUITY": "신흥국 주식",
    "GOV_BOND": "국채", "IG_CREDIT": "투자등급 회사채", "HY_CREDIT": "하이일드", "GOLD": "금",
    "COMMODITY": "원자재", "REIT": "리츠", "CASH": "현금", "OTHER": "기타",
}


def selected_candidate(record: AnalysisRecord) -> CandidatePortfolio | None:
    sid = record.final.selected_candidate_id
    if not sid:
        return None
    return next((c for c in record.candidates.candidates if c.candidate_id == sid), None)


def selected_quant(record: AnalysisRecord) -> CandidateQuantResult | None:
    sid = record.final.selected_candidate_id
    if not sid:
        return None
    return next((q for q in record.quant_results if q.candidate_id == sid), None)


def _li(items: list[str]) -> str:
    return "".join(f"<li>{html.escape(x)}</li>" for x in items)


def build_html_report(record: AnalysisRecord) -> str:
    selected = selected_candidate(record)
    quant = selected_quant(record)
    created = record.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if selected:
        alloc_rows = "".join(
            f"<tr><td>{html.escape(a.ticker)}</td><td>{html.escape(a.name)}</td><td>{html.escape(ASSET_LABELS.get(a.asset_class, a.asset_class))}</td><td>{a.weight:.2f}%</td><td>{html.escape(a.role)}</td></tr>"
            for a in selected.allocations
        )
    else:
        alloc_rows = '<tr><td colspan="5">사람 검토 필요 - 확정된 후보가 없습니다.</td></tr>'

    metric_html = ""
    if quant:
        m = quant.metrics
        metric_html = f"""
        <table><tr><th>과거 연환산수익률</th><th>과거 연환산변동성</th><th>Sharpe</th><th>최대낙폭</th><th>95% 일간 CVaR</th></tr>
        <tr><td>{m.annualized_return_pct}</td><td>{m.annualized_volatility_pct}</td><td>{m.sharpe_ratio}</td><td>{m.max_drawdown_pct}</td><td>{m.cvar_95_daily_pct}</td></tr></table>
        <p class="small">로컬 과거통계 계산. 기간: {html.escape(str(m.data_start))} to {html.escape(str(m.data_end))}. 예측값이 아닙니다.</p>
        """

    fact_rows = "".join(
        f"<tr><td>{html.escape(i.status)}</td><td>{html.escape(i.claim)}</td><td>{html.escape(i.correction)}</td><td><a href=\"{html.escape(i.url)}\">출처</a></td></tr>"
        for i in record.factcheck.items
    )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>투자위원회 보고서</title>
<style>
body{{font-family:Arial,'Malgun Gothic',sans-serif;max-width:1050px;margin:40px auto;padding:0 24px;color:#1f2937;line-height:1.55}}
h1,h2{{color:#111827}} .badge{{display:inline-block;padding:4px 10px;border:1px solid #aaa;border-radius:999px;margin-right:6px}}
table{{border-collapse:collapse;width:100%;margin:12px 0 22px}} th,td{{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}} th{{background:#f5f5f5}} .small{{font-size:12px;color:#666}} .warn{{padding:12px;border-left:4px solid #777;background:#f7f7f7}}
@media print{{body{{margin:12mm;max-width:none}}}}
</style></head><body>
<h1>투자위원회 보고서</h1>
<p><span class="badge">고객 {html.escape(record.client_profile.client_code)}</span><span class="badge">{created}</span><span class="badge">판단: {html.escape(record.final.decision)}</span></p>
<div class="warn"><strong>의사결정 지원용입니다.</strong> {html.escape(record.compliance.disclaimer)}</div>
<h2>1. CIO 최종판정</h2>
<p><strong>선택 후보:</strong> {html.escape(record.final.selected_candidate_id or 'NONE')} &nbsp; <strong>판단 신뢰도:</strong> {record.final.confidence_pct}%</p>
<ul>{_li(record.final.rationale)}</ul>
<h2>2. 권고 포트폴리오</h2>
<table><tr><th>티커</th><th>상품/종목</th><th>자산군</th><th>비중</th><th>역할</th></tr>{alloc_rows}</table>
{metric_html}
<h2>3. 주요 위험</h2><ul>{_li(record.final.principal_risks)}</ul>
<h2>4. 모니터링 및 리밸런싱</h2><ul>{_li(record.final.monitoring_triggers)}</ul><p>{html.escape(record.final.rebalancing_rule)}</p>
<h2>5. 독립 거시환경 분석</h2><p>{html.escape(record.macro.regime_summary)}</p><ul>{_li(record.macro.key_risks)}</ul>
<h2>6. 상품·종목 선정</h2><p>{html.escape(record.product.summary)}</p><ul>{_li([p.ticker + ' - ' + p.why_fit for p in record.product.products])}</ul>
<h2>7. 반대심문 / Bear</h2><ul>{_li(record.bear.strongest_objections)}</ul><h3>실패 시나리오</h3><ul>{_li(record.bear.failure_scenarios)}</ul>
<h2>8. 사실검증</h2><p>종합: <strong>{html.escape(record.factcheck.overall_status)}</strong></p>
<table><tr><th>상태</th><th>주장</th><th>정정/메모</th><th>출처</th></tr>{fact_rows}</table>
<h2>9. 고객 적합성 / 프로세스 검토</h2><p>고객 적합성: <strong>{html.escape(record.suitability.status)}</strong> &nbsp; 프로세스 검토: <strong>{html.escape(record.compliance.status)}</strong></p>
<h3>추가 확인 정보</h3><ul>{_li(record.suitability.missing_information)}</ul>
<h3>사람이 확인할 항목</h3><ul>{_li(record.compliance.required_human_checks)}</ul>
<p class="small">로컬 의사결정 지원 앱에서 생성되었습니다. 시장데이터 가용성에 따라 과거통계가 불완전할 수 있습니다. 고객에게 사용하기 전 모든 사실과 회사 정책·법규 적용 여부를 사람이 확인해야 합니다.</p>
</body></html>"""
