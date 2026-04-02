from __future__ import annotations

from pydantic import BaseModel, Field


class Finding(BaseModel):
    source: str = Field(description="Tool or system that produced this finding")
    summary: str
    evidence: str = Field(description="Raw log snippet, metric value, or JSON excerpt")


class RCAReport(BaseModel):
    alert_id: str
    root_cause_hypothesis: str
    contributing_factors: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    code_changes_linked: list[str] = Field(
        default_factory=list,
        description="Commit SHAs or PR URLs if a code change is suspected",
    )
