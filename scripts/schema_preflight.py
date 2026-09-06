from __future__ import annotations

from typing import Any
from agents import AgentOutputSchema
from investment_copilot.schema import (
    BearReview, ComplianceReview, FactCheckReport, FinalDecision,
    MacroReport, ProductUniverse, SuitabilityReport,
)

SCHEMAS = [
    MacroReport, ProductUniverse, SuitabilityReport, BearReview,
    FactCheckReport, ComplianceReview, FinalDecision,
]

def walk(node: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(node, dict):
        ap = node.get("additionalProperties")
        if ap not in (None, False):
            errors.append(f"{path}: open/typed additionalProperties is not strict-compatible")
        if "default" in node and node["default"] is not None:
            errors.append(f"{path}: non-null JSON Schema default is not allowed in strict mode")
        for key, value in node.items():
            errors.extend(walk(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            errors.extend(walk(value, f"{path}[{i}]"))
    return errors

for schema in SCHEMAS:
    raw = schema.model_json_schema()
    issues = walk(raw)
    if issues:
        raise RuntimeError(f"{schema.__name__} failed schema preflight: " + " | ".join(issues))
    AgentOutputSchema(schema, strict_json_schema=True)
    print(f"OK strict output schema: {schema.__name__}")

print("All agent output schemas are strict-compatible.")
