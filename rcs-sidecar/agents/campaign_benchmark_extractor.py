import structlog
from pydantic import BaseModel
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from agents._citations import coerce_citations
from google.genai import types

AGENT_NAME = "campaign_benchmark_extractor"
logger = structlog.get_logger()

class CampaignBenchmarkDraft(BaseModel):
    metric_name: str
    baseline_value: float
    time_period: str
    channel: str | None = None
    citations: list[dict] = []

class CampaignBenchmarkExtractionOutput(BaseModel):
    benchmarks: list[CampaignBenchmarkDraft]

SYSTEM_PROMPT = """Extract campaign performance benchmarks and KPI baselines.
Include: metric name (e.g., email_open_rate, brand_awareness_pct),
numeric baseline value, time period (e.g., "Q4 2025"), and channel if applicable.
Include citations with artifact_id, locator, and excerpt.
If this artifact contains ANY content relevant to the fields above, you MUST populate the corresponding arrays with at least one evidence node. Return an empty array ONLY if the artifact contains absolutely no relevant content whatsoever."""


async def campaign_benchmark_extractor(artifacts: list[SourceArtifact], plan: FieldExtractionPlan, broadcaster: TheaterBroadcaster) -> ExtractionResult:
    assigned = next((a for a in plan.assignments if a.agent_name == AGENT_NAME), None)
    if not assigned:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    filtered = [a for a in artifacts if a.artifact_id in assigned.artifact_ids]
    contents = "\n\n".join(f"[{a.filename} | artifact_id={a.artifact_id}]\n{a.raw_text[:50000]}" for a in filtered)

    await broadcaster.emit("extract", f"Extracting campaign benchmarks from {len(filtered)} artifacts...", {"model": MODEL_FLASH})

    if not client:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[], validation_passed=True)

    try:
        result, usage, raw_text = await generate_structured(MODEL_FLASH, contents, CampaignBenchmarkExtractionOutput,
                                           thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT)
        if not result.benchmarks:
            logger.warning("extractor_returned_all_empty", agent=AGENT_NAME, raw_response=raw_text)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"campaign_benchmarks": [b.model_dump() for b in result.benchmarks]},
            citations=coerce_citations([c for b in result.benchmarks for c in b.citations], filtered),
            validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[],
                                validation_passed=False, validation_errors=[str(e)])
