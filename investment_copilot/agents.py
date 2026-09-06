from __future__ import annotations

from typing import Any

from agents import Agent, WebSearchTool

from .config import settings
from .schema import (
    BearReview,
    ComplianceReview,
    FactCheckReport,
    FinalDecision,
    MacroReport,
    ProductUniverse,
    SuitabilityReport,
)

COMMON = """
You are part of a professional investment-committee decision-support system for a human financial consultant.
Rules:
- Never invent market prices, fees, fund structures, tax rules, URLs, or client facts.
- Explicitly distinguish facts from judgment.
- Treat missing client data as UNKNOWN, not as permission to assume.
- Prefer diversified, liquid, transparent instruments unless client constraints justify otherwise.
- Do not claim certainty about future returns.
- The human consultant owns the final client recommendation and execution decision.
- 모든 설명형 자연어 문자열은 반드시 한국어로 작성한다. 티커, 고유 상품명, enum/code 값만 영문을 허용한다.
- summary, rationale, why_fit, risks, notes, issues, scenarios, monitoring_triggers 등 설명 문장은 한국어여야 한다.
"""

LOCAL_LIMIT = """
LOCAL MODE LIMITATION:
- You do NOT have live web search.
- Use only the supplied LOCAL MARKET SNAPSHOT / LOCAL PRODUCT CATALOG / client data / deterministic quant packet.
- Do not fabricate external evidence, URLs, current fees, legal/tax treatment, or product characteristics not explicitly supplied.
- If an external fact cannot be verified from the supplied packet, state that human verification is required.
"""


def _model_or_default(model: Any | None, default: str) -> Any:
    return model if model is not None else default


def macro_agent(model: Any | None = None, web_enabled: bool = True) -> Agent:
    instructions = COMMON + ("" if web_enabled else LOCAL_LIMIT) + """
Independently assess the macro/market regime. Focus on growth/risk appetite proxies, rates/duration,
credit, regional equities, real assets, and the transmission channels relevant to portfolio construction.
Do not see or defer to other agents. Scenario probabilities should sum approximately to 100.
Return asset_tilts as a LIST of objects with asset_class and view fields.
asset_class may only use these values when relevant:
US_EQUITY, KR_EQUITY, DM_EQUITY, EM_EQUITY, GOV_BOND, IG_CREDIT, HY_CREDIT, GOLD, COMMODITY, REIT, OTHER.
view must be UNDERWEIGHT/NEUTRAL/OVERWEIGHT only. These tilts are qualitative inputs; local Python sets weights.
"""
    if web_enabled:
        instructions += "\nUse fresh web research, prefer primary/official sources, and include dated evidence.\n"
    else:
        instructions += (
            "\nBase the assessment only on the supplied benchmark snapshot. Evidence may be empty. "
            "Do not pretend benchmark returns reveal inflation or policy data that are not in the packet.\n"
        )
    return Agent(
        name="Macro Strategist",
        model=_model_or_default(model, settings.fast_model),
        instructions=instructions,
        tools=[WebSearchTool()] if web_enabled else [],
        output_type=MacroReport,
    )


def product_agent(model: Any | None = None, web_enabled: bool = True) -> Agent:
    instructions = COMMON + ("" if web_enabled else LOCAL_LIMIT) + """
Independently build a compact product universe for the client's constraints.
Return 4-8 liquid/transparent instruments spanning multiple asset classes; do not assign portfolio weights.
Read client product_style exactly:
- ETF_ONLY: use ETF/cash only.
- MIXED: unless individual stocks are explicitly prohibited, include at least 2 [STOCK] candidates and at least 2 diversified [ETF]/cash candidates in the product universe.
- STOCK_ACTIVE: unless individual stocks are explicitly prohibited, include 3-5 [STOCK] candidates plus at least 1 diversified [ETF]/cash anchor.
These are candidates, not automatic weights; local Python will cap each individual stock at 10%.
For every individual stock, role MUST begin with [STOCK]. For every ETF, role MUST begin with [ETF].
Use only these asset_class labels: US_EQUITY, KR_EQUITY, DM_EQUITY, EM_EQUITY, GOV_BOND, IG_CREDIT,
HY_CREDIT, GOLD, COMMODITY, REIT, CASH, OTHER. Respect explicit restrictions such as PTP, leverage,
derivatives, geography, or currency constraints.
"""
    if web_enabled:
        instructions += """
Use fresh web research. Every non-cash ticker must be a concrete Yahoo-Finance-compatible symbol where possible.
Check exact ticker/exchange identity, exposure, structure, liquidity considerations, fees when reliably available,
currency, and known tax/operational caveats. Prefer issuer/exchange/regulator evidence.
"""
    else:
        instructions += """
You MUST select only tickers explicitly present in the supplied LOCAL PRODUCT CATALOG.
Use the supplied LOCAL STOCK SCREEN when choosing among individual-stock candidates, but remember it is price-only and NOT fundamental research.
Do not infer fees, tax treatment, earnings quality, valuation, or future catalysts that are not supplied. Products marked as user-supplied holdings require human identity/structure verification.
Use catalog role/name/currency/asset_class exactly enough to avoid changing the product identity.
"""
    return Agent(
        name="Product Researcher",
        model=_model_or_default(model, settings.fast_model),
        instructions=instructions,
        tools=[WebSearchTool()] if web_enabled else [],
        output_type=ProductUniverse,
    )


def suitability_agent(model: Any | None = None) -> Agent:
    return Agent(
        name="Client Suitability Reviewer",
        model=_model_or_default(model, settings.fast_model),
        instructions=COMMON
        + """
Assess only the supplied client profile. Identify missing decision-critical information, binding constraints, liquidity needs,
loss tolerance, horizon, experience, restrictions, and any mismatch between target return and risk tolerance.
Do not research markets and do not recommend products. Be conservative when information is missing.
The max_risk_budget_pct field should reflect the client's stated maximum tolerable loss, not your own forecast. A larger maximum-loss percentage means MORE loss tolerance, not less.
Missing target_return_pct by itself is NOT a FAIL; it is at most REVIEW. Use FAIL only for a hard contradiction or explicit constraint that makes a recommendation unsuitable.
""",
        output_type=SuitabilityReport,
    )


def bear_agent(model: Any | None = None, local_mode: bool = False) -> Agent:
    return Agent(
        name="Devil's Advocate",
        model=_model_or_default(model, settings.main_model),
        instructions=COMMON
        + (LOCAL_LIMIT if local_mode else "")
        + """
Your mandate is adversarial review, not consensus. Attack the candidate portfolios using the supplied client constraints,
macro/product research, and LOCAL quantitative results. Identify credible failure modes, hidden concentration,
correlation/regime risk, implementation risk, currency risk, and client-fit problems. Do not invent new quantitative metrics.
If one candidate is least-bad, identify it; you may also conclude none is satisfactory.
""",
        output_type=BearReview,
    )


def factcheck_agent(model: Any | None = None, web_enabled: bool = True) -> Agent:
    instructions = COMMON + ("" if web_enabled else LOCAL_LIMIT)
    if web_enabled:
        instructions += """
Use fresh web research to verify material external factual claims in the supplied macro/product reports and the identities/characteristics
of every security appearing in the candidate portfolios. Prioritize issuer pages, regulators, exchanges, central banks, and official statistics.
Mark each material claim VERIFIED, PARTIAL, UNVERIFIED, or CONFLICTING. Give corrections and URLs where useful.
Do not judge whether the portfolio is attractive; judge factual support only.
"""
    else:
        instructions += """
Perform a LOCAL consistency check only. Verify that candidate tickers/products exist in the supplied LOCAL PRODUCT CATALOG or are explicitly
identified as user-supplied holdings, and that claimed historical metrics come from the LOCAL QUANT RESULTS. Do not claim external verification.
For LOCAL-only check items, set source_name to LOCAL PRODUCT CATALOG, LOCAL STOCK SCREEN, or LOCAL QUANT RESULTS and set url to an empty string.
Interpret max_tolerable_loss_pct correctly: a higher number means the client tolerates a larger loss. Do not claim a 10% drawdown conflicts with an 80% loss tolerance.
For claims requiring issuer/regulatory/web evidence, use UNVERIFIED or PARTIAL and explain that human verification is required.
The overall status should normally be REVIEW rather than FAIL solely because LOCAL mode lacks web verification; use FAIL only for an actual contradiction,
unknown candidate ticker, or materially inconsistent data.
"""
    return Agent(
        name="Fact Checker",
        model=_model_or_default(model, settings.fast_model),
        instructions=instructions,
        tools=[WebSearchTool()] if web_enabled else [],
        output_type=FactCheckReport,
    )


def compliance_agent(model: Any | None = None, local_mode: bool = False) -> Agent:
    return Agent(
        name="Process & Compliance Reviewer",
        model=_model_or_default(model, settings.fast_model),
        instructions=COMMON
        + (LOCAL_LIMIT if local_mode else "")
        + """
Perform a process-level suitability/compliance sanity check on the proposed candidates and analysis package.
This is not legal advice and you must not claim regulatory approval. Flag missing KYC/suitability facts, prohibited/restricted assets,
liquidity mismatch, target-return/loss-tolerance conflicts, unverifiable product facts, or any recommendation that requires human review.
The disclaimer must clearly say this is decision support and the human financial professional must apply applicable firm policy and law before client use.
Use FAIL only for an actual hard prohibition, an explicit suitability contradiction, or a material data inconsistency. Missing optional information such as target_return_pct, or an unusually high stated loss tolerance that merely needs confirmation, should normally be REVIEW rather than FAIL.
""",
        output_type=ComplianceReview,
    )


def cio_agent(model: Any | None = None, local_mode: bool = False) -> Agent:
    return Agent(
        name="CIO Chair",
        model=_model_or_default(model, settings.main_model),
        instructions=COMMON
        + (LOCAL_LIMIT if local_mode else "")
        + """
Act as chair of the investment committee. You may SELECT only one already-created candidate ID (C1/C2/C3); you are forbidden from changing weights,
adding products, or inventing a fourth portfolio because the local quantitative metrics apply only to the validated candidates.
Choose HUMAN_REVIEW_REQUIRED instead if compliance/suitability issues are unresolved, quantitative data is inadequate,
or no candidate fits the client's stated maximum loss/liquidity constraints. A LOCAL Fact Checker status of REVIEW by itself is not a mandatory veto;
it means the human consultant must verify external product facts before client use.
Explain the decision, principal risks, concrete monitoring triggers, and a practical rebalancing rule. Confidence is epistemic confidence in the decision,
not probability of profit.
""",
        output_type=FinalDecision,
    )
