from __future__ import annotations

import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .company_tools import (
    FetchCompanyReferenceInput,
    FetchCompanyReferenceOutput,
    JiraSearchTicketsInput,
    JiraSearchTicketsOutput,
    LogsSearchInput,
    LogsSearchOutput,
    MetricsQueryInput,
    MetricsQueryOutput,
    SearchIncidentKnowledgeInput,
    SearchIncidentKnowledgeOutput,
    SearchPreviousIssuesInput,
    SearchPreviousIssuesOutput,
    fetch_company_reference,
    jira_search_tickets,
    logs_search,
    metrics_query,
    search_incident_knowledge,
    search_previous_issues,
)
from .llm import LLMAdapter
from .models import Plan


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractEntitiesInput(StrictModel):
    text: str


class ExtractEntitiesOutput(StrictModel):
    entities: list[str]


class SummarizeInput(StrictModel):
    text: str
    max_words: int = Field(default=50, ge=1)


class SummarizeOutput(StrictModel):
    summary: str


class ExtractDeadlinesInput(StrictModel):
    text: str


class ExtractDeadlinesOutput(StrictModel):
    deadlines: list[str]


class ExtractActionItemsInput(StrictModel):
    text: str


class ExtractActionItemsOutput(StrictModel):
    action_items: list[str]


PriorityValue = Literal["low", "medium", "high", "critical"]


class ClassifyPriorityInput(StrictModel):
    text: str


class ClassifyPriorityOutput(StrictModel):
    priority: PriorityValue
    reasons: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ToolSpec:
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    fn: Callable[[BaseModel], BaseModel]


def extract_entities(payload: ExtractEntitiesInput) -> ExtractEntitiesOutput:
    matches = re.findall(r"\b[A-Z][a-zA-Z0-9_-]*\b", payload.text)
    seen: set[str] = set()
    ordered_entities: list[str] = []
    for entity in matches:
        if entity in seen:
            continue
        seen.add(entity)
        ordered_entities.append(entity)
    return ExtractEntitiesOutput(entities=ordered_entities)


def summarize(payload: SummarizeInput) -> SummarizeOutput:
    words = payload.text.split()
    summary = " ".join(words[: payload.max_words]).strip()
    return SummarizeOutput(summary=summary)


def extract_deadlines(payload: ExtractDeadlinesInput) -> ExtractDeadlinesOutput:
    text = payload.text
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        (
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
            r"[a-z]*\s+\d{1,2}(?:,\s*\d{4})?\b"
        ),
        r"\b(?:next|within)\s+\d{1,3}\s+(?:day|days|week|weeks|month|months)\b",
        r"\b(?:by|before)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:eow|eom|end of week|end of month|q[1-4])\b",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    return ExtractDeadlinesOutput(deadlines=_dedupe_normalized(candidates))


def extract_action_items(payload: ExtractActionItemsInput) -> ExtractActionItemsOutput:
    lines = re.split(r"[\n.;]", payload.text)
    action_leads = {
        "prepare",
        "draft",
        "review",
        "send",
        "create",
        "update",
        "fix",
        "investigate",
        "deliver",
        "coordinate",
        "include",
        "follow",
        "finalize",
        "publish",
    }
    items: list[str] = []
    for raw_line in lines:
        line = raw_line.strip(" -*\t")
        if not line:
            continue
        first_word = line.split(maxsplit=1)[0].lower()
        is_action = (
            first_word in action_leads
            or "owner:" in line.lower()
            or "assignee:" in line.lower()
            or line.lower().startswith("action:")
            or line.lower().startswith("todo:")
        )
        if is_action:
            items.append(line)

    if not items:
        first_sentence = payload.text.split(".")[0].strip()
        if first_sentence:
            items.append(first_sentence)
    return ExtractActionItemsOutput(action_items=_dedupe_normalized(items)[:10])


def classify_priority(payload: ClassifyPriorityInput) -> ClassifyPriorityOutput:
    text = payload.text.lower()
    critical_terms = ["sev1", "p0", "outage", "production down", "security incident", "breach"]
    high_terms = ["urgent", "asap", "high priority", "deadline", "exec", "blocking"]
    medium_terms = ["important", "soon", "moderate", "follow up"]

    matched_critical = [term for term in critical_terms if term in text]
    matched_high = [term for term in high_terms if term in text]
    matched_medium = [term for term in medium_terms if term in text]

    if matched_critical:
        return ClassifyPriorityOutput(priority="critical", reasons=matched_critical)
    if matched_high:
        return ClassifyPriorityOutput(priority="high", reasons=matched_high)
    if matched_medium:
        return ClassifyPriorityOutput(priority="medium", reasons=matched_medium)
    return ClassifyPriorityOutput(priority="low", reasons=["no urgency signals detected"])


DETERMINISTIC_TOOL_REGISTRY: dict[str, ToolSpec] = {
    "extract_entities": ToolSpec(
        input_model=ExtractEntitiesInput,
        output_model=ExtractEntitiesOutput,
        fn=extract_entities,
    ),
    "extract_deadlines": ToolSpec(
        input_model=ExtractDeadlinesInput,
        output_model=ExtractDeadlinesOutput,
        fn=extract_deadlines,
    ),
    "extract_action_items": ToolSpec(
        input_model=ExtractActionItemsInput,
        output_model=ExtractActionItemsOutput,
        fn=extract_action_items,
    ),
    "classify_priority": ToolSpec(
        input_model=ClassifyPriorityInput,
        output_model=ClassifyPriorityOutput,
        fn=classify_priority,
    ),
    "summarize": ToolSpec(
        input_model=SummarizeInput,
        output_model=SummarizeOutput,
        fn=summarize,
    ),
    "fetch_company_reference": ToolSpec(
        input_model=FetchCompanyReferenceInput,
        output_model=FetchCompanyReferenceOutput,
        fn=fetch_company_reference,
    ),
    "jira_search_tickets": ToolSpec(
        input_model=JiraSearchTicketsInput,
        output_model=JiraSearchTicketsOutput,
        fn=jira_search_tickets,
    ),
    "metrics_query": ToolSpec(
        input_model=MetricsQueryInput,
        output_model=MetricsQueryOutput,
        fn=metrics_query,
    ),
    "logs_search": ToolSpec(
        input_model=LogsSearchInput,
        output_model=LogsSearchOutput,
        fn=logs_search,
    ),
    "search_incident_knowledge": ToolSpec(
        input_model=SearchIncidentKnowledgeInput,
        output_model=SearchIncidentKnowledgeOutput,
        fn=search_incident_knowledge,
    ),
    "search_previous_issues": ToolSpec(
        input_model=SearchPreviousIssuesInput,
        output_model=SearchPreviousIssuesOutput,
        fn=search_previous_issues,
    ),
}


class LLMToolRunner:
    """LLM-backed implementation for built-in tools."""

    def __init__(self, *, llm_adapter: LLMAdapter, timeout_s: float = 8.0) -> None:
        self.llm_adapter = llm_adapter
        self.timeout_s = timeout_s

    def extract_entities(self, payload: ExtractEntitiesInput) -> ExtractEntitiesOutput:
        system_prompt = (
            "Extract named entities from the input text. Return JSON only with key 'entities'. "
            "Entities should be unique and keep input order."
        )
        user_prompt = payload.text
        return self.llm_adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=ExtractEntitiesOutput,
            timeout_s=self.timeout_s,
        )

    def summarize(self, payload: SummarizeInput) -> SummarizeOutput:
        system_prompt = (
            "Summarize the input text in plain language. "
            "Return JSON only with key 'summary'. "
            "Do not exceed the requested max word count."
        )
        user_prompt = f"Max words: {payload.max_words}\n\nText:\n{payload.text}"
        return self.llm_adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=SummarizeOutput,
            timeout_s=self.timeout_s,
        )

    def extract_deadlines(self, payload: ExtractDeadlinesInput) -> ExtractDeadlinesOutput:
        system_prompt = (
            "Extract explicit deadlines and time markers from the input. "
            "Return JSON only with key 'deadlines' as a list of strings."
        )
        return self.llm_adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=payload.text,
            response_model=ExtractDeadlinesOutput,
            timeout_s=self.timeout_s,
        )

    def extract_action_items(self, payload: ExtractActionItemsInput) -> ExtractActionItemsOutput:
        system_prompt = (
            "Extract concrete action items from the input text. "
            "Return JSON only with key 'action_items' as short imperative strings."
        )
        return self.llm_adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=payload.text,
            response_model=ExtractActionItemsOutput,
            timeout_s=self.timeout_s,
        )

    def classify_priority(self, payload: ClassifyPriorityInput) -> ClassifyPriorityOutput:
        system_prompt = (
            "Classify priority as one of: low, medium, high, critical. "
            "Return JSON only with keys 'priority' and 'reasons'."
        )
        return self.llm_adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=payload.text,
            response_model=ClassifyPriorityOutput,
            timeout_s=self.timeout_s,
        )


def build_tool_registry(
    *, llm_adapter: LLMAdapter | None = None, llm_timeout_s: float = 8.0
) -> dict[str, ToolSpec]:
    if llm_adapter is None:
        return dict(DETERMINISTIC_TOOL_REGISTRY)

    llm_runner = LLMToolRunner(llm_adapter=llm_adapter, timeout_s=llm_timeout_s)
    return {
        "extract_entities": ToolSpec(
            input_model=ExtractEntitiesInput,
            output_model=ExtractEntitiesOutput,
            fn=llm_runner.extract_entities,
        ),
        "extract_deadlines": ToolSpec(
            input_model=ExtractDeadlinesInput,
            output_model=ExtractDeadlinesOutput,
            fn=llm_runner.extract_deadlines,
        ),
        "extract_action_items": ToolSpec(
            input_model=ExtractActionItemsInput,
            output_model=ExtractActionItemsOutput,
            fn=llm_runner.extract_action_items,
        ),
        "classify_priority": ToolSpec(
            input_model=ClassifyPriorityInput,
            output_model=ClassifyPriorityOutput,
            fn=llm_runner.classify_priority,
        ),
        "summarize": ToolSpec(
            input_model=SummarizeInput,
            output_model=SummarizeOutput,
            fn=llm_runner.summarize,
        ),
        "fetch_company_reference": ToolSpec(
            input_model=FetchCompanyReferenceInput,
            output_model=FetchCompanyReferenceOutput,
            fn=fetch_company_reference,
        ),
        "jira_search_tickets": ToolSpec(
            input_model=JiraSearchTicketsInput,
            output_model=JiraSearchTicketsOutput,
            fn=jira_search_tickets,
        ),
        "metrics_query": ToolSpec(
            input_model=MetricsQueryInput,
            output_model=MetricsQueryOutput,
            fn=metrics_query,
        ),
        "logs_search": ToolSpec(
            input_model=LogsSearchInput,
            output_model=LogsSearchOutput,
            fn=logs_search,
        ),
        "search_incident_knowledge": ToolSpec(
            input_model=SearchIncidentKnowledgeInput,
            output_model=SearchIncidentKnowledgeOutput,
            fn=search_incident_knowledge,
        ),
        "search_previous_issues": ToolSpec(
            input_model=SearchPreviousIssuesInput,
            output_model=SearchPreviousIssuesOutput,
            fn=search_previous_issues,
        ),
    }


TOOL_REGISTRY = DETERMINISTIC_TOOL_REGISTRY


def _dedupe_normalized(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = " ".join(value.split()).strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


class Executor:
    def __init__(
        self,
        *,
        registry: dict[str, ToolSpec] | None = None,
        tool_timeout_s: float = 2.0,
        retry_policy: dict[str, float | int] | None = None,
    ) -> None:
        self.registry = registry or build_tool_registry()
        self.tool_timeout_s = tool_timeout_s
        retry_policy = retry_policy or {}
        self.max_retries = int(retry_policy.get("max_retries", 0))
        self.backoff_s = float(retry_policy.get("backoff_s", 0.0))

    def execute_plan(self, plan: Plan) -> dict[str, Any]:
        step_results: list[dict[str, Any]] = []
        total_tools = 0
        total_duration_ms = 0.0
        error_count = 0
        for step in plan.steps:
            tool_results: list[dict[str, Any]] = []
            for tool_call in step.tool_calls:
                result = self._execute_with_retry(tool_call.tool, tool_call.args)
                tool_results.append(result)
                total_tools += 1
                total_duration_ms += float(result.get("duration_ms", 0.0))
                if result.get("status") != "ok":
                    error_count += 1
            step_results.append(
                {
                    "step_id": step.step_id,
                    "description": step.description,
                    "tool_results": tool_results,
                }
            )
        return {
            "steps": step_results,
            "execution_metadata": {
                "total_tools": total_tools,
                "total_duration_ms": round(total_duration_ms, 2),
                "error_count": error_count,
            },
        }

    def _execute_with_retry(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        started_at = time.perf_counter()
        final_error: str = "unknown error"
        attempts = 0
        for attempt in range(self.max_retries + 1):
            attempts = attempt + 1
            try:
                output = self._execute_once(tool_name, args)
                return {
                    "tool": tool_name,
                    "status": "ok",
                    "output": output,
                    "attempts": attempts,
                    "duration_ms": _duration_ms(started_at),
                }
            except Exception as exc:  # noqa: BLE001
                final_error = str(exc)
                if attempt < self.max_retries and self.backoff_s > 0:
                    time.sleep(self.backoff_s)
        return {
            "tool": tool_name,
            "status": "error",
            "error": final_error,
            "attempts": attempts,
            "duration_ms": _duration_ms(started_at),
        }

    def _execute_once(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        spec = self.registry.get(tool_name)
        if spec is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        payload = spec.input_model.model_validate(args)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(spec.fn, payload)
            try:
                raw_output = future.result(timeout=self.tool_timeout_s)
            except TimeoutError as exc:
                raise TimeoutError(
                    f"Tool '{tool_name}' timed out after {self.tool_timeout_s:.2f}s"
                ) from exc

        validated_output = spec.output_model.model_validate(raw_output)
        return validated_output.model_dump()


def _duration_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 2)
