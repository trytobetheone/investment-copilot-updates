from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


AssetClass = Literal[
    "US_EQUITY", "KR_EQUITY", "DM_EQUITY", "EM_EQUITY",
    "GOV_BOND", "IG_CREDIT", "HY_CREDIT", "GOLD", "COMMODITY",
    "REIT", "CASH", "OTHER"
]


class Holding(BaseModel):
    ticker: str = Field(min_length=1)
    name: str = ""
    asset_class: str = "OTHER"
    currency: str = "USD"
    weight: float = Field(ge=0, le=100)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()


class ClientProfile(BaseModel):
    client_code: str = Field(min_length=1, description="Use a pseudonymous client code, not a real name.")
    base_currency: str = "KRW"
    investable_assets: float = Field(gt=0)
    horizon_years: int = Field(ge=1, le=60)
    max_tolerable_loss_pct: float = Field(gt=0, le=100)
    minimum_liquidity_pct: float = Field(ge=0, le=100)
    target_return_pct: float | None = Field(default=None, ge=-100, le=100)
    experience_level: Literal["low", "medium", "high"] = "medium"
    tax_priority: Literal["low", "medium", "high"] = "medium"
    product_style: Literal["ETF_ONLY", "MIXED", "STOCK_ACTIVE"] = "MIXED"
    restrictions: str = ""
    preferences: str = ""
    notes: str = ""
    holdings: list[Holding] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    claim: str
    source_name: str
    url: str
    as_of_date: str
    confidence: Literal["low", "medium", "high"]


class MacroScenario(BaseModel):
    name: str
    probability_pct: float = Field(ge=0, le=100)
    portfolio_implications: list[str] = Field(default_factory=list)


class AssetTilt(BaseModel):
    asset_class: AssetClass
    view: Literal["UNDERWEIGHT", "NEUTRAL", "OVERWEIGHT"]


class MacroReport(BaseModel):
    regime_summary: str
    scenarios: list[MacroScenario] = Field(default_factory=list)
    # Keep this as an explicit list instead of dict[str, ...]. OpenAI strict structured
    # outputs reject free-form/typed additionalProperties objects.
    asset_tilts: list[AssetTilt] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]


class ProductIdea(BaseModel):
    ticker: str
    name: str
    asset_class: AssetClass
    currency: str
    role: str
    why_fit: str
    implementation_risks: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()


class ProductUniverse(BaseModel):
    summary: str
    products: list[ProductIdea] = Field(min_length=4, max_length=8)
    red_flags: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]


class SuitabilityReport(BaseModel):
    status: Literal["PASS", "REVIEW", "FAIL"]
    missing_information: list[str] = Field(default_factory=list)
    binding_constraints: list[str] = Field(default_factory=list)
    suitability_notes: list[str] = Field(default_factory=list)
    max_risk_budget_pct: float = Field(ge=0, le=100)


class AllocationLine(BaseModel):
    ticker: str
    name: str = ""
    asset_class: str
    currency: str
    weight: float = Field(gt=0, le=100)
    role: str

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()


class CandidatePortfolio(BaseModel):
    candidate_id: str
    label: str
    thesis: str
    allocations: list[AllocationLine]
    estimated_income_yield_pct: float | None = None
    implementation_notes: list[str] = Field(default_factory=list)

    def total_weight(self) -> float:
        return sum(x.weight for x in self.allocations)


class CandidateSet(BaseModel):
    candidates: list[CandidatePortfolio] = Field(min_length=2, max_length=3)


class QuantMetrics(BaseModel):
    status: Literal["OK", "PARTIAL", "FAILED"]
    annualized_return_pct: float | None = None
    annualized_volatility_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    var_95_daily_pct: float | None = None
    cvar_95_daily_pct: float | None = None
    worst_20d_pct: float | None = None
    observations: int = 0
    data_start: str | None = None
    data_end: str | None = None
    warnings: list[str] = Field(default_factory=list)
    risk_contributions_pct: dict[str, float] = Field(default_factory=dict)


class CandidateQuantResult(BaseModel):
    candidate_id: str
    metrics: QuantMetrics


class BearReview(BaseModel):
    overall_risk: Literal["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
    strongest_objections: list[str] = Field(default_factory=list)
    failure_scenarios: list[str] = Field(default_factory=list)
    concentration_concerns: list[str] = Field(default_factory=list)
    client_mismatch_concerns: list[str] = Field(default_factory=list)
    preferred_candidate_id: str | None = None


class FactCheckItem(BaseModel):
    claim: str
    status: Literal["VERIFIED", "PARTIAL", "UNVERIFIED", "CONFLICTING"]
    correction: str
    source_name: str
    url: str
    as_of_date: str


class FactCheckReport(BaseModel):
    overall_status: Literal["PASS", "REVIEW", "FAIL"]
    items: list[FactCheckItem] = Field(default_factory=list)
    product_red_flags: list[str] = Field(default_factory=list)


class ComplianceReview(BaseModel):
    status: Literal["PASS", "REVIEW", "FAIL"]
    issues: list[str] = Field(default_factory=list)
    required_human_checks: list[str] = Field(default_factory=list)
    disclaimer: str


class FinalDecision(BaseModel):
    decision: Literal["SELECT", "HUMAN_REVIEW_REQUIRED"]
    selected_candidate_id: str | None = None
    rationale: list[str] = Field(default_factory=list)
    principal_risks: list[str] = Field(default_factory=list)
    monitoring_triggers: list[str] = Field(default_factory=list)
    rebalancing_rule: str
    confidence_pct: int = Field(ge=0, le=100)


class AnalysisRecord(BaseModel):
    created_at: datetime
    client_profile: ClientProfile
    macro: MacroReport
    product: ProductUniverse
    suitability: SuitabilityReport
    candidates: CandidateSet
    quant_results: list[CandidateQuantResult]
    bear: BearReview
    factcheck: FactCheckReport
    compliance: ComplianceReview
    final: FinalDecision
