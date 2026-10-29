"""
VEXA — LLM Output Schemas

These Pydantic models define exactly what each agent's LLM must return. They
are deliberately separate from the result envelopes in ``contracts.py``:

    LLM text ──extract_json_object──► dict ──<Agent>Output.model_validate──► typed output
                                                                      │
                                     orchestrator adds timing/status ─┴─► contracts.<Agent>Result

Validation happens in two places:
1. Real mode: as a CrewAI task guardrail (``make_guardrail``). An invalid answer is
   sent back to the agent with the validation errors and retried; after the
   configured retries the task fails loudly instead of yielding default values.
2. Every mode: the result parsers in ``crew.py`` re-validate and record
   ``output_valid`` / ``validation_errors`` on the result.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class _LLMOutput(BaseModel):
    # Unknown keys are ignored (LLMs add extras); known keys are type-checked.
    model_config = ConfigDict(extra="ignore")


def _str_list(v: Any) -> Any:
    """Accept a single string where a list of strings is expected."""
    return [v] if isinstance(v, str) else v


class RequirementAnalysisOutput(_LLMOutput):
    task_summary: str = Field(min_length=1)
    functional_requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=1, description="Testable success conditions")
    ambiguities: list[str] = Field(default_factory=list)
    affected_areas: list[str] = Field(default_factory=list)

    _coerce = field_validator(
        "functional_requirements", "constraints", "acceptance_criteria", "ambiguities", "affected_areas",
        mode="before",
    )(_str_list)


class ProjectAnalysisOutput(_LLMOutput):
    total_files: int = Field(default=0, ge=0)
    languages: dict[str, int] = Field(default_factory=dict)
    important_files: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    relevant_file_contents: dict[str, str] = Field(default_factory=dict)
    existing_tests: list[str] = Field(default_factory=list)
    git_status: str = ""
    project_context: str = Field(min_length=1)


StepAction = Literal["write", "patch", "delete", "test", "verify"]


class ImplementationStepOutput(_LLMOutput):
    step_number: int = Field(ge=1)
    description: str = Field(min_length=1)
    files_affected: list[str] = Field(default_factory=list)
    action: StepAction = "patch"


class ImplementationPlanOutput(_LLMOutput):
    objective: str = Field(min_length=1)
    steps: list[ImplementationStepOutput] = Field(min_length=1)
    files_to_modify: list[str] = Field(default_factory=list)
    files_to_create: list[str] = Field(default_factory=list)
    test_strategy: str = ""
    risks: list[str] = Field(default_factory=list)


FileAction = Literal["created", "patched", "written", "overwritten", "deleted"]


class FileChangeOutput(_LLMOutput):
    path: str = Field(min_length=1)
    action: FileAction = "patched"
    description: str = ""


class CodingOutput(_LLMOutput):
    files_changed: list[FileChangeOutput] = Field(default_factory=list)
    implementation_notes: str = ""


class TesterOutput(_LLMOutput):
    failures: list[str] = Field(default_factory=list)

    _coerce = field_validator("failures", mode="before")(_str_list)


RootCauseCategory = Literal["implementation_bug", "test_bug", "environment", "pre_existing", "unknown"]


class DebugOutput(_LLMOutput):
    root_cause: str = Field(min_length=1)
    root_cause_category: RootCauseCategory = "unknown"
    fix_applied: str = ""
    files_changed: list[FileChangeOutput] = Field(default_factory=list)


class VerifierOutput(_LLMOutput):
    verified: bool
    requirements_satisfied: list[str] = Field(default_factory=list)
    requirements_failed: list[str] = Field(default_factory=list)
    tests_passed: bool = False
    files_changed: list[str] = Field(default_factory=list)
    remaining_risks: list[str] = Field(default_factory=list)
    evidence: str = ""


AGENT_OUTPUT_SCHEMAS: dict[str, type[_LLMOutput]] = {
    "RequirementAnalyst": RequirementAnalysisOutput,
    "ProjectAnalyst": ProjectAnalysisOutput,
    "Planner": ImplementationPlanOutput,
    "Coder": CodingOutput,
    "Tester": TesterOutput,
    "Debugger": DebugOutput,
    "Verifier": VerifierOutput,
}


# ---------------------------------------------------------------------------
# Extraction and validation
# ---------------------------------------------------------------------------


def extract_json_object(text: Any) -> dict[str, Any] | None:
    """
    Return the first JSON object embedded in *text*, or None.

    Uses a real JSON decoder from each '{' rather than a greedy regex, so
    surrounding prose or code fences do not corrupt the result.
    """
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        idx = text.find("{", idx + 1)
    return None


def _format_errors(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors()
    ]


def validate_output(raw: Any, schema: type[BaseModel]) -> tuple[BaseModel | None, list[str]]:
    """Validate raw LLM text against *schema*. Returns (instance, errors)."""
    data = extract_json_object(raw)
    if data is None:
        return None, ["No JSON object found in the response"]
    try:
        return schema.model_validate(data), []
    except ValidationError as exc:
        return None, _format_errors(exc)


def make_guardrail(schema: type[BaseModel]):
    """
    Build a CrewAI task guardrail that enforces *schema*.

    On success the task output is replaced by the normalised JSON; on failure
    CrewAI re-prompts the agent with the error message below.
    """

    # No return annotation: CrewAI inspects it, and with postponed annotations
    # it would be a string. The contract is (ok: bool, value_or_error: Any).
    def guardrail(output):
        instance, errors = validate_output(getattr(output, "raw", output), schema)
        if instance is not None:
            return True, instance.model_dump_json()
        schema_json = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        return False, (
            "Your answer did not match the required JSON schema. Problems: "
            + "; ".join(errors[:10])
            + f". Return ONLY one JSON object matching this JSON Schema: {schema_json}"
        )

    guardrail.__name__ = f"{schema.__name__}_guardrail"
    return guardrail


ManagerChoice = Literal[
    "RequirementAnalyst", "ProjectAnalyst", "Planner", "Coder", "Tester", "Debugger", "Verifier", "FINISH",
]


class ManagerDecision(_LLMOutput):
    """Hierarchical architecture: the Manager's review of the last result and its next delegation."""

    review_of_last_result: Literal["accept", "revise", "none"] = "none"
    review_notes: str = ""
    next_agent: ManagerChoice
    brief: str = Field(default="", description="Task-specific instructions for the delegated specialist")
    work_package: list[int] = Field(default_factory=list,
                                    description="Coder only: plan step numbers to implement in this delegation")
    reason: str = ""


AGENT_OUTPUT_SCHEMAS["Manager"] = ManagerDecision
