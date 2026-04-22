from pydantic import BaseModel
from schemas import ExtractionResult, FieldExtractionPlan, SourceArtifact
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH, client
from google.genai import types

AGENT_NAME = "campaign_benchmark_extractor"

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
Include citations with artifact_id, locator, and excerpt."""


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
        result = await generate_structured(MODEL_FLASH, contents, CampaignBenchmarkExtractionOutput,
                                           thinking_level=types.ThinkingLevel.LOW, system_instruction=SYSTEM_PROMPT)
        return ExtractionResult(
            agent_name=AGENT_NAME,
            extracted_fields={"campaign_benchmarks": [b.model_dump() for b in result.benchmarks]},
            citations=[], validation_passed=True,
        )
    except Exception as e:
        return ExtractionResult(agent_name=AGENT_NAME, extracted_fields={}, citations=[],
                                validation_passed=False, validation_errors=[str(e)])
