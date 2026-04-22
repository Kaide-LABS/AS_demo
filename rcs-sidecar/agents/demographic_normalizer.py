from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster

async def demographic_normalizer(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    return ExtractionResult(agent_name="demographic_normalizer", extracted_fields={}, citations=[], validation_passed=True)
