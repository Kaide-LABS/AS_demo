from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster

async def brand_tone_extractor(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    return ExtractionResult(agent_name="brand_tone_extractor", extracted_fields={}, citations=[], validation_passed=True)
