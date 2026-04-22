from schemas import TriageManifest, SourceArtifact, ArtifactClassification, ArtifactType
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH_LITE, client
from google.genai import types

SYSTEM_PROMPT = """You are a document classifier for enterprise market research artifacts.
Classify each document into exactly one category.
Categories: brand_tracker, focus_group_transcript, segmentation_study,
crm_export, survey_instrument, ethnography, competitive_intel, verbatim_corpus, other.
For each artifact, also specify extraction_strategy as "default"."""


async def triage_agent(artifacts: list[SourceArtifact], broadcaster: TheaterBroadcaster) -> TriageManifest:
    if client:
        contents = "Classify these artifacts:\n\n"
        for a in artifacts:
            contents += f"artifact_id: {a.artifact_id}\nfilename: {a.filename}\npreview: {a.raw_text[:2000]}\n---\n"
        try:
            manifest, usage = await generate_structured(
                model=MODEL_FLASH_LITE,
                contents=contents,
                response_schema=TriageManifest,
                thinking_level=types.ThinkingLevel.MINIMAL,
                system_instruction=SYSTEM_PROMPT,
            )
            for c in manifest.classifications:
                await broadcaster.emit("triage", f"Classified {c.artifact_id} as {c.artifact_type.value}")
            await broadcaster.emit('triage', f'Triage completed', meta=usage)
            return manifest
        except Exception:
            pass  # fall through to heuristic

    classifications = []
    for a in artifacts:
        t = ArtifactType.OTHER
        fn = a.filename.lower()
        if "brand" in fn or "tracker" in fn:
            t = ArtifactType.BRAND_TRACKER
        elif "segment" in fn:
            t = ArtifactType.SEGMENTATION_STUDY
        elif "transcript" in fn:
            t = ArtifactType.VERBATIM_CORPUS
        elif "crm" in fn:
            t = ArtifactType.CRM_EXPORT
        elif "survey" in fn or fn.endswith(".qsf"):
            t = ArtifactType.SURVEY_INSTRUMENT
        elif "ethnograph" in fn:
            t = ArtifactType.ETHNOGRAPHY
        elif "compet" in fn:
            t = ArtifactType.COMPETITIVE_INTEL
        classifications.append(ArtifactClassification(
            artifact_id=a.artifact_id, artifact_type=t,
            confidence=0.7, extraction_strategy="default",
        ))
        await broadcaster.emit("triage", f"Classified {a.filename} as {t.value}")

    return TriageManifest(classifications=classifications)
