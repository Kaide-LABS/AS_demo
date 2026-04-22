from typing import List, Dict
from schemas import ExtractionResult, MergedEvidence, EvidenceNode, Contradiction

class EvidenceMerger:
    def merge(self, extractions: List[ExtractionResult]) -> MergedEvidence:
        evidence_by_field: Dict[str, List[EvidenceNode]] = {}
        total_nodes = 0
        unique_nodes = 0
        contradictions = []

        for ext in extractions:
            for field, val in ext.extracted_fields.items():
                if field not in evidence_by_field:
                    evidence_by_field[field] = []
                for cit in ext.citations:
                    authority = "secondary"
                    if cit.artifact_type.value in ["focus_group_transcript", "ethnography", "survey_instrument"]:
                        authority = "primary_research"
                    
                    evidence_by_field[field].append(EvidenceNode(
                        field_path=field,
                        value=val,
                        confidence=0.8,
                        source_authority=authority,
                        citation=cit
                    ))
                    total_nodes += 1

        for field, nodes in evidence_by_field.items():
            seen_locators = set()
            deduped = []
            for n in sorted(nodes, key=lambda x: x.confidence, reverse=True):
                loc = (n.citation.artifact_id, n.citation.locator)
                if loc not in seen_locators:
                    seen_locators.add(loc)
                    deduped.append(n)
            evidence_by_field[field] = deduped
            unique_nodes += len(deduped)

        for field, nodes in evidence_by_field.items():
            if len(nodes) > 1:
                val_set = set(str(n.value) for n in nodes if isinstance(n.value, (str, float, int, bool)))
                if len(val_set) > 1:
                    contradictions.append(Contradiction(
                        field_path=field,
                        competing_values=nodes,
                        resolution_needed=True
                    ))

        auth_weight = {"primary_research": 3, "secondary": 2, "inferred": 1}
        for field in evidence_by_field:
            evidence_by_field[field].sort(key=lambda n: (auth_weight.get(n.source_authority, 0), n.confidence), reverse=True)

        return MergedEvidence(
            evidence_by_field=evidence_by_field,
            contradictions=contradictions,
            deduplication_stats={"total_nodes": total_nodes, "unique_after_merge": unique_nodes}
        )
