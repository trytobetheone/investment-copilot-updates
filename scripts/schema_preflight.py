from __future__ import annotations

from agents import AgentOutputSchema
from investment_copilot.schema import (
    BearReview, ComplianceReview, FactCheckReport, FinalDecision,
    MacroReport, ProductUniverse, SuitabilityReport,
)

SCHEMAS = [
    MacroReport, ProductUniverse, SuitabilityReport, BearReview,
    FactCheckReport, ComplianceReview, FinalDecision,
]

for schema in SCHEMAS:
    AgentOutputSchema(schema, strict_json_schema=True)
    print(f"OK strict output schema: {schema.__name__}")

print("All agent output schemas are strict-compatible.")
