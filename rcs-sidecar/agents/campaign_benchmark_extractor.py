from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster

async def campaign_benchmark_extractor(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    return ExtractionResult(agent_name="campaign_benchmark_extractor", extracted_fields={}, citations=[], validation_passed=True)
