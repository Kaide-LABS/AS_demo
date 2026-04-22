from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster

async def verbatim_distiller(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    return ExtractionResult(agent_name="verbatim_distiller", extracted_fields={"segments[].verbatims": []}, citations=[], validation_passed=True)
