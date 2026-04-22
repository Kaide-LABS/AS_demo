from typing import Dict, List
from schemas import RadiantPersonaCalibration, FieldState, TriageManifest, FieldExtractionPlan, AgentAssignment, MergedEvidence, RuleViolation

class FieldStateEngine:
    def __init__(self, schema: type = RadiantPersonaCalibration):
        self.fields: Dict[str, FieldState] = {}
        self._initialize_from_schema()

    def _initialize_from_schema(self):
        self.fields = {
            "segments": FieldState.UNKNOWN,
            "segments[].label": FieldState.UNKNOWN,
            "segments[].description": FieldState.UNKNOWN,
            "segments[].weight": FieldState.UNKNOWN,
            "segments[].demographic_attributes": FieldState.UNKNOWN,
            "segments[].psychographic_attributes": FieldState.UNKNOWN,
            "segments[].behavioral_attributes": FieldState.UNKNOWN,
            "segments[].information_sources": FieldState.UNKNOWN,
            "segments[].verbatims": FieldState.UNKNOWN,
            "brand_constraints": FieldState.UNKNOWN,
            "campaign_benchmarks": FieldState.UNKNOWN,
        }

    def count_unknown(self) -> int:
        return sum(1 for v in self.fields.values() if v == FieldState.UNKNOWN)

    def summary(self) -> str:
        counts = {s: 0 for s in FieldState}
        for state in self.fields.values():
            counts[state] += 1
        return f"{counts[FieldState.VALIDATED]} validated, {counts[FieldState.CANDIDATE]} candidate, {counts[FieldState.UNKNOWN]} unknown"

    def plan_extractions(self, manifest: TriageManifest) -> FieldExtractionPlan:
        assignments = []
        
        segment_artifacts = []
        verbatim_artifacts = []
        demographic_artifacts = []
        behavioral_artifacts = []
        brand_artifacts = [c.artifact_id for c in manifest.classifications]
        benchmark_artifacts = []

        for c in manifest.classifications:
            t = c.artifact_type.value
            if t in ["segmentation_study", "survey_instrument", "brand_tracker"]:
                segment_artifacts.append(c.artifact_id)
            if t in ["focus_group_transcript", "verbatim_corpus", "ethnography"]:
                verbatim_artifacts.append(c.artifact_id)
            if t == "crm_export":
                demographic_artifacts.append(c.artifact_id)
            if t in ["ethnography", "competitive_intel", "survey_instrument", "other"]:
                behavioral_artifacts.append(c.artifact_id)
            if t in ["brand_tracker", "competitive_intel"]:
                benchmark_artifacts.append(c.artifact_id)

        if segment_artifacts:
            assignments.append(AgentAssignment(agent_name="segment_extractor", target_fields=["segments"], artifact_ids=segment_artifacts, priority=10))
        if verbatim_artifacts:
            assignments.append(AgentAssignment(agent_name="verbatim_distiller", target_fields=["segments[].verbatims"], artifact_ids=verbatim_artifacts, priority=8))
        if demographic_artifacts:
            assignments.append(AgentAssignment(agent_name="demographic_normalizer", target_fields=["segments[].demographic_attributes"], artifact_ids=demographic_artifacts, priority=6))
        if behavioral_artifacts:
            assignments.append(AgentAssignment(agent_name="behavioral_extractor", target_fields=["segments[].behavioral_attributes", "segments[].psychographic_attributes", "segments[].information_sources"], artifact_ids=behavioral_artifacts, priority=5))
        if brand_artifacts:
            assignments.append(AgentAssignment(agent_name="brand_tone_extractor", target_fields=["brand_constraints"], artifact_ids=brand_artifacts, priority=4))
        if benchmark_artifacts:
            assignments.append(AgentAssignment(agent_name="campaign_benchmark_extractor", target_fields=["campaign_benchmarks"], artifact_ids=benchmark_artifacts, priority=3))

        return FieldExtractionPlan(assignments=assignments)

    def update(self, merged_evidence: MergedEvidence) -> None:
        for field_path, nodes in merged_evidence.evidence_by_field.items():
            if nodes:
                for k in self.fields:
                    if k.startswith(field_path) or field_path.startswith(k):
                        if self.fields[k] == FieldState.UNKNOWN:
                            self.fields[k] = FieldState.CANDIDATE

    def update_from_validation(self, calibration: RadiantPersonaCalibration, violations: List[RuleViolation]) -> None:
        violated_paths = [v.field_path for v in violations]
        
        for k in self.fields:
            if self.fields[k] == FieldState.CANDIDATE:
                is_violated = any(vp.startswith(k) or k.startswith(vp) for vp in violated_paths)
                if not is_violated:
                    self.fields[k] = FieldState.VALIDATED
                else:
                    self.fields[k] = FieldState.BLOCKED

    def export(self) -> Dict[str, FieldState]:
        return self.fields.copy()
