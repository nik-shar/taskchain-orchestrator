"""Strict Pydantic schemas for tool inputs and outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model for strict schema validation."""

    model_config = ConfigDict(extra="forbid")


class ExtractEntitiesInput(StrictModel):
    text: str


class ExtractEntitiesOutput(StrictModel):
    entities: list[str]


class SummarizeInput(StrictModel):
    text: str
    max_words: int = Field(default=60, ge=1, le=300)


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


class KnowledgeItem(StrictModel):
    title: str
    snippet: str
    source_type: str | None = None
    source_id: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    why_selected: str | None = None


class SearchIncidentKnowledgeInput(StrictModel):
    query: str
    limit: int = Field(default=3, ge=1, le=10)
    service: str | None = None
    severity: str | None = None


class SearchIncidentKnowledgeOutput(StrictModel):
    results: list[KnowledgeItem]


class IssueMatch(StrictModel):
    ticket: str
    summary: str
    relevance: float = Field(ge=0.0, le=1.0)
    source: str | None = None
    doc_id: str | None = None
    chunk_id: str | None = None
    score: float | None = Field(default=None, ge=0.0)
    retrieval_mode: str | None = None
    why_selected: str | None = None


class SearchPreviousIssuesInput(StrictModel):
    query: str
    limit: int = Field(default=3, ge=1, le=10)
    service: str | None = None
    severity: str | None = None
    use_llm_rerank: bool | None = None
    use_hybrid: bool | None = None


class SearchPreviousIssuesOutput(StrictModel):
    results: list[IssueMatch]


class BriefCitation(StrictModel):
    source_tool: str
    reference: str
    snippet: str
    score: float | None = Field(default=None, ge=0.0)
    why_selected: str | None = None


class BuildIncidentBriefInput(StrictModel):
    query: str
    incident_knowledge: list[KnowledgeItem] = Field(default_factory=list)
    previous_issues: list[IssueMatch] = Field(default_factory=list)


class BuildIncidentBriefOutput(StrictModel):
    summary: str
    similar_incidents: list[str] = Field(default_factory=list)
    probable_causes: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    escalation_recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[BriefCitation] = Field(default_factory=list)
