from __future__ import annotations
from enum import Enum
from typing import Literal, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator

class ArtifactType(str, Enum):
    BRAND_TRACKER = "brand_tracker"
    FOCUS_GROUP_TRANSCRIPT = "focus_group_transcript"
    SEGMENTATION_STUDY = "segmentation_study"
    CRM_EXPORT = "crm_export"
    SURVEY_INSTRUMENT = "survey_instrument"
    ETHNOGRAPHY = "ethnography"
    COMPETITIVE_INTEL = "competitive_intel"
    VERBATIM_CORPUS = "verbatim_corpus"
    OTHER = "other"

class FieldState(str, Enum):
    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    BLOCKED = "blocked"

class SourceArtifact(BaseModel):
    artifact_id: str
    filename: str
    artifact_type: Optional[ArtifactType] = None
    raw_text: str
    tables: List[dict] = []
    metadata: dict = {}
    size_bytes: int

class ArtifactClassification(BaseModel):
    artifact_id: str
    artifact_type: ArtifactType
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_strategy: str

class TriageManifest(BaseModel):
    classifications: List[ArtifactClassification]

class AgentAssignment(BaseModel):
    agent_name: str
    target_fields: List[str]
    artifact_ids: List[str]
    priority: int = Field(ge=1, le=10)

class FieldExtractionPlan(BaseModel):
    assignments: List[AgentAssignment]

class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str
    artifact_type: ArtifactType
    locator: str
    excerpt: str = Field(max_length=500)

class ExtractionResult(BaseModel):
    agent_name: str
    extracted_fields: dict
    citations: List[SourceCitation]
    validation_passed: bool
    validation_errors: List[str] = []

class EvidenceNode(BaseModel):
    field_path: str
    value: Union[str, float, bool, List[str], dict]
    confidence: float = Field(ge=0.0, le=1.0)
    source_authority: Literal["primary_research", "secondary", "inferred"]
    citation: SourceCitation

class Contradiction(BaseModel):
    field_path: str
    competing_values: List[EvidenceNode]
    resolution_needed: bool = True

class MergedEvidence(BaseModel):
    evidence_by_field: Dict[str, List[EvidenceNode]]
    contradictions: List[Contradiction]
    deduplication_stats: dict

class Verbatim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=20, max_length=1200)
    sentiment: Literal["positive", "neutral", "negative", "mixed"]
    citation: SourceCitation

class BehavioralAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: Union[str, float, bool, List[str]]
    confidence: float = Field(ge=0.0, le=1.0)
    citations: List[SourceCitation] = Field(min_length=1)

class BrandConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraint_type: Literal["tone", "forbidden_language", "messaging_guardrail", "voice_parameter"]
    description: str = Field(max_length=300)
    examples: List[str] = Field(max_length=5)
    citations: List[SourceCitation] = Field(min_length=1)

class CampaignBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_name: str
    baseline_value: float
    time_period: str
    channel: Optional[str] = None
    citations: List[SourceCitation] = Field(min_length=1)

class PersonaSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    label: str = Field(max_length=80)
    description: str = Field(max_length=600)
    weight: float = Field(gt=0.0, le=1.0)
    demographic_attributes: List[BehavioralAttribute]
    psychographic_attributes: List[BehavioralAttribute]
    behavioral_attributes: List[BehavioralAttribute]
    information_sources: List[str]
    verbatims: List[Verbatim] = Field(min_length=5)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool = False

class RadiantPersonaCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.1.0"] = "1.1.0"
    project_id: str
    target_audience_brief: str
    segments: List[PersonaSegment] = Field(min_length=1, max_length=8)
    brand_constraints: List[BrandConstraint] = Field(default_factory=list)
    campaign_benchmarks: List[CampaignBenchmark] = Field(default_factory=list)
    global_provenance: List[SourceCitation]
    coverage_gaps: List[str] = Field(default_factory=list)
    field_state_summary: Dict[str, FieldState] = Field(default_factory=dict)

    @field_validator("segments")
    @classmethod
    def weights_sum_to_one(cls, v: List[PersonaSegment]) -> List[PersonaSegment]:
        total = sum(s.weight for s in v)
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"segment weights sum to {total}, must equal 1.0 ± 0.01")
        return v

class TheaterEvent(BaseModel):
    ts_ms: int
    stage: Literal["ingest", "triage", "field_state", "extract", "merge", "synthesize", "validate", "done", "error"]
    message: str
    meta: dict = {}
    trace_id: Optional[str] = None

class RuleViolation(BaseModel):
    rule_name: str
    field_path: str
    segment_id: Optional[str] = None
    description: str
