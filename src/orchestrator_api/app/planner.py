"""Planning layer for the orchestrator.

This module has two planning styles:
1) Deterministic planning: fixed, rule-based steps.
2) LLM-backed planning: model generates steps, then code validates/normalizes.

Beginner terms:
- Plan: ordered list of Step objects.
- Step: one logical action, containing one or more ToolCall objects.
- ToolCall: "call this tool with these args".
- Normalization: filling/cleaning tool args so they match tool schemas.
- Fallback: switch to deterministic behavior when LLM path fails.

Think of planner output as a "to-do list" for the executor.
The planner does not run tools itself; it only decides what should be run.
"""

from __future__ import annotations

import json
import logging
import os

from .llm import LLMAdapter
from .models import Plan, Step, ToolCall

logger = logging.getLogger(__name__)


def build_plan(task_text: str, *, context: dict[str, object] | None = None) -> Plan:
    """Build a deterministic plan from task text and optional context.

    This function is intentionally simple and predictable. It is the reliability
    baseline even when LLM mode is enabled (because LLM mode can fall back here).

    High-level step order:
    1) Extract structured signals from text.
    2) Add retrieval steps when task looks like issue/incident work.
    3) End with summarize so consumers always get a concise output.
    """
    # Base extraction pipeline used for most tasks.
    steps = [
        Step(
            step_id="extract_entities",
            description="Extract candidate entities from the task text.",
            tool_calls=[ToolCall(tool="extract_entities", args={"text": task_text})],
        ),
        Step(
            step_id="extract_deadlines",
            description="Extract explicit deadlines and time markers.",
            tool_calls=[ToolCall(tool="extract_deadlines", args={"text": task_text})],
        ),
        Step(
            step_id="extract_action_items",
            description="Extract concrete action items and owners.",
            tool_calls=[ToolCall(tool="extract_action_items", args={"text": task_text})],
        ),
        Step(
            step_id="classify_priority",
            description="Classify the task urgency and priority.",
            tool_calls=[ToolCall(tool="classify_priority", args={"text": task_text})],
        ),
    ]

    # For issue/incident-like text, add historical retrieval via local RAG.
    if _is_issue_or_incident_like(task_text):
        # "rag_args" are arguments for search_previous_issues tool.
        rag_args: dict[str, object] = {
            "query": task_text,
            "top_k": 6,
        }
        # Use context safely: if context is None, use empty dict.
        context_values = context or {}
        project_key = context_values.get("project_key")
        if _is_incident_like(task_text):
            # Keep broad retrieval for incident-like tasks to avoid over-filtering.
            # In incidents, narrow filters can accidentally hide relevant evidence.
            pass
        else:
            # For non-incident issue tasks, focus on Jira + optional project.
            rag_args["source"] = "jira"
            if isinstance(project_key, str):
                rag_args["project"] = project_key

        steps.append(
            Step(
                step_id="search_previous_issues",
                description="Search previous Jira/incidents using the local RAG index.",
                tool_calls=[
                    ToolCall(
                        tool="search_previous_issues",
                        args=rag_args,
                    )
                ],
            )
        )

    # For incident-like text, add incident knowledge retrieval + policy evidence.
    if _is_incident_like(task_text):
        # "top_k" controls how many hits to retrieve.
        retrieval_args: dict[str, object] = {
            "query": task_text,
            "top_k": 5,
        }
        context_values = context or {}
        # Pull useful incident filters from context when available.
        for key in ("service", "severity"):
            value = context_values.get(key)
            if isinstance(value, str):
                retrieval_args[key] = value
        start_time = context_values.get("start_time")
        end_time = context_values.get("end_time")
        if isinstance(start_time, str):
            retrieval_args["time_start"] = start_time
        if isinstance(end_time, str):
            retrieval_args["time_end"] = end_time

        steps.extend(
            [
                Step(
                    step_id="search_incident_knowledge",
                    description="Search similar incidents and runbook-like knowledge.",
                    tool_calls=[
                        ToolCall(
                            tool="search_incident_knowledge",
                            args=retrieval_args,
                        )
                    ],
                ),
                Step(
                    step_id="fetch_incident_policy",
                    description="Fetch policy evidence for incident response decisions.",
                    tool_calls=[
                        ToolCall(
                            tool="fetch_company_reference",
                            args={
                                # Hard-coded policy source makes verifier expectations stable.
                                "source": "policy_v2",
                                "query": "incident escalation rollback communication",
                                "max_chars": 1200,
                            },
                        )
                    ],
                ),
            ]
        )

    # Keep a final summarize step so downstream consumers always get a short answer.
    steps.append(
        Step(
            step_id="summarize",
            description="Summarize task text in at most 50 words.",
            tool_calls=[ToolCall(tool="summarize", args={"text": task_text, "max_words": 50})],
        )
    )
    return Plan(steps=steps)


class LLMPlanner:
    """Planner that asks an LLM to produce a structured Plan.

    Important: model output is never trusted directly.
    We still:
    1) validate tool names against an allowlist
    2) normalize/repair arguments
    """

    def __init__(self, *, llm_adapter: LLMAdapter, timeout_s: float = 8.0) -> None:
        self.llm_adapter = llm_adapter
        self.timeout_s = timeout_s

    def build_plan(self, task_text: str, *, context: dict[str, object] | None = None) -> Plan:
        # Context is serialized and passed to the model as input evidence.
        # ensure_ascii=True keeps JSON predictable for logs/prompts.
        context_json = json.dumps(context or {}, ensure_ascii=True, sort_keys=True)
        # Prompt constrains tool names and ordering expectations.
        system_prompt = (
            "You are a strict planning module for an orchestration API. "
            "Return JSON only. Build a short plan with three to six steps. "
            "Use only tools named 'extract_entities', 'extract_deadlines', "
            "'extract_action_items', 'classify_priority', 'summarize', "
            "'fetch_company_reference', 'jira_search_tickets', 'metrics_query', "
            "'logs_search', 'search_incident_knowledge', and 'search_previous_issues'. "
            "If policy/config evidence is needed, use fetch_company_reference with source in "
            "{policy_v1, policy_v2, governance_notes, company_profile, jira_config, "
            "slack_config, oncall_rota, github_actions, postgres_config}. "
            "For issue/incident tasks, prefer search_previous_issues. "
            "For incident-like tasks (alert, outage, sev/p1), "
            "also prefer search_incident_knowledge before final summarize. "
            "Always include a final summarize step and include max_words."
        )
        user_prompt = (
            f"Task:\n{task_text}\n\n"
            f"Context JSON:\n{context_json}\n\n"
            "Return a plan that conforms to the provided schema."
        )
        # Adapter returns a typed Plan (Pydantic-validated structured output).
        plan = self.llm_adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=Plan,
            timeout_s=self.timeout_s,
        )
        # Defense-in-depth: reject unknown tool names.
        self._validate_tools(plan)
        # Defense-in-depth: repair common missing/invalid args.
        return self._normalize_plan_args(plan, task_text=task_text, context=context)

    @staticmethod
    def _validate_tools(plan: Plan) -> None:
        """Allowlist tool names so model output cannot route to unknown tools."""
        # Keeping this list explicit prevents accidental tool exposure.
        allowed = {
            "extract_entities",
            "extract_deadlines",
            "extract_action_items",
            "classify_priority",
            "summarize",
            "fetch_company_reference",
            "jira_search_tickets",
            "metrics_query",
            "logs_search",
            "search_incident_knowledge",
            "search_previous_issues",
        }
        for step in plan.steps:
            for tool_call in step.tool_calls:
                if tool_call.tool not in allowed:
                    raise ValueError(f"Unsupported tool from LLM planner: {tool_call.tool}")

    @staticmethod
    def _normalize_plan_args(
        plan: Plan,
        *,
        task_text: str,
        context: dict[str, object] | None,
    ) -> Plan:
        """Patch common LLM planning mistakes with safe defaults/context values.

        Why normalization exists:
        - LLM can omit required args.
        - LLM can include unsupported args.
        - Context values are often known at API level and should be injected.
        """
        context_values = context or {}
        for step in plan.steps:
            for tool_call in step.tool_calls:
                # Copy to avoid mutating dict while reading it.
                args = dict(tool_call.args)

                if tool_call.tool == "summarize":
                    # LLM planner frequently omits summarize text; default to original task.
                    # setdefault() keeps existing model-provided values if present.
                    args.setdefault("text", task_text)
                    args.setdefault("max_words", 120)

                if tool_call.tool in {"metrics_query", "logs_search"}:
                    # These tools usually need service + time window.
                    for key in ("service", "start_time", "end_time"):
                        value = context_values.get(key)
                        if key not in args and isinstance(value, str):
                            args[key] = value

                if tool_call.tool == "jira_search_tickets":
                    # Time window fields are not supported by jira_search_tickets input schema.
                    # Removing unsupported keys avoids executor validation failures.
                    args.pop("start_time", None)
                    args.pop("end_time", None)
                    project_key = context_values.get("project_key")
                    if "project_key" not in args and isinstance(project_key, str):
                        args["project_key"] = project_key

                if tool_call.tool == "search_incident_knowledge":
                    # Ensure retrieval request always has a query and sane defaults.
                    args.setdefault("query", task_text)
                    args.setdefault("top_k", 5)
                    service = context_values.get("service")
                    severity = context_values.get("severity")
                    start_time = context_values.get("start_time")
                    end_time = context_values.get("end_time")
                    if "service" not in args and isinstance(service, str):
                        args["service"] = service
                    if "severity" not in args and isinstance(severity, str):
                        args["severity"] = severity
                    if "time_start" not in args and isinstance(start_time, str):
                        args["time_start"] = start_time
                    if "time_end" not in args and isinstance(end_time, str):
                        args["time_end"] = end_time

                if tool_call.tool == "search_previous_issues":
                    # For non-incident tasks, default to Jira-focused previous issues.
                    args.setdefault("query", task_text)
                    args.setdefault("top_k", 6)
                    project_key = context_values.get("project_key")
                    incident_like = _is_incident_like(task_text)
                    if args.get("source") == "incident_event_log":
                        # Incident rows do not carry project keys in this corpus.
                        args.pop("project", None)
                    if "source" not in args and not incident_like:
                        args["source"] = "jira"
                    if "project" not in args and not incident_like and isinstance(project_key, str):
                        args["project"] = project_key

                tool_call.args = args
        return plan


class Planner:
    """Route planning requests to deterministic or LLM planner.

    This class is the public planner entrypoint used by main.py.
    """

    def __init__(
        self,
        *,
        mode: str = "deterministic",
        llm_adapter: LLMAdapter | None = None,
        timeout_s: float = 8.0,
    ) -> None:
        self.mode = mode.lower().strip()
        self.llm_planner = (
            LLMPlanner(llm_adapter=llm_adapter, timeout_s=timeout_s) if llm_adapter else None
        )

    def build_plan(self, task_text: str, *, context: dict[str, object] | None = None) -> Plan:
        # If mode=llm and adapter exists, try model planner first.
        if self.mode == "llm" and self.llm_planner is not None:
            try:
                if _trace_enabled():
                    logger.warning("LLM trace planner mode=llm action=attempt_build_plan")
                return self.llm_planner.build_plan(task_text, context=context)
            except Exception as exc:  # noqa: BLE001
                # Reliability rule: never fail planning just because LLM failed.
                logger.warning(
                    "LLM planner failed; falling back to deterministic planner. reason=%s",
                    exc,
                )
                return build_plan(task_text, context=context)
        # If llm mode is requested but no adapter is available, log and degrade gracefully.
        if self.mode == "llm" and self.llm_planner is None:
            logger.warning(
                "Planner mode is 'llm' but no LLM adapter was available; using deterministic plan."
            )
        if _trace_enabled():
            logger.warning("LLM trace planner mode=%s action=deterministic_plan", self.mode)
        # Default path for deterministic mode.
        return build_plan(task_text, context=context)


def _is_incident_like(task_text: str) -> bool:
    """Heuristic detector for incident-like language.

    Heuristic means a simple keyword rule, not an ML classifier.
    """
    lowered = task_text.lower()
    signals = ("alert", "incident", "sev", "p1", "outage")
    return any(signal in lowered for signal in signals)


def _is_issue_or_incident_like(task_text: str) -> bool:
    """Broader heuristic detector for issue/defect/incident language.

    This is intentionally broader than _is_incident_like so bug/ticket tasks
    also get previous-issues retrieval.
    """
    lowered = task_text.lower()
    signals = (
        "alert",
        "incident",
        "sev",
        "p1",
        "outage",
        "bug",
        "issue",
        "ticket",
        "defect",
        "regression",
        "root cause",
    )
    return any(signal in lowered for signal in signals)


def _trace_enabled() -> bool:
    """Enable verbose LLM planner logging when ORCHESTRATOR_LLM_TRACE=1."""
    return os.getenv("ORCHESTRATOR_LLM_TRACE", "0").strip() == "1"
