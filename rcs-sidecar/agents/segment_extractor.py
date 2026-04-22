from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster

async def segment_extractor(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    await broadcaster.emit("extract", "Extracting segments...", {"model": "gemini-3-flash-preview"})
    return ExtractionResult(agent_name="segment_extractor", extracted_fields={"segments": []}, citations=[], validation_passed=True)
