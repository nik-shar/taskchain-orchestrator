"""Pydantic models shared across API, planner, executor, verifier, and storage.

Beginner terms used in this file:
- Model: a typed schema class used for validation/serialization.
- Literal: restricts a field to a fixed set of allowed string values.
- Field(default_factory=...): creates a fresh default object per instance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Task lifecycle states used by storage + API responses.
TaskStatus = Literal["queued", "running", "succeeded", "failed"]


class ToolCall(BaseModel):
    """One tool invocation inside a step."""

    # Tool name must match a key in executor registry.
    tool: str
    # Tool-specific arguments (validated later by that tool's input model).
    args: dict[str, Any] = Field(default_factory=dict)


class Step(BaseModel):
    """A logical unit in a plan (can execute one or more tool calls)."""

    step_id: str
    description: str
    tool_calls: list[ToolCall] = Field(default_factory=list)


class Plan(BaseModel):
    """Ordered list of steps produced by planner and consumed by executor."""

    steps: list[Step] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Verifier outcome: pass/fail plus human-readable reasons."""

    passed: bool
    reasons: list[str] = Field(default_factory=list)


class Task(BaseModel):
    """Canonical task record shape returned by API/storage."""

    task_id: str
    # Raw task text submitted by API client.
    input_task: str
    # Caller-provided structured context (service, time window, etc.).
    context: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = "queued"
    # Artifacts captured at each pipeline stage.
    plan_json: Plan | None = None
    result_json: dict[str, Any] | None = None
    verification_json: VerificationResult | None = None
    created_at: datetime
    updated_at: datetime


class CreateTaskRequest(BaseModel):
    """Request body for POST /tasks."""

    # min_length enforces non-empty task text at API boundary.
    task: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class CreateTaskResponse(BaseModel):
    """Response body for POST /tasks."""

    task_id: str
