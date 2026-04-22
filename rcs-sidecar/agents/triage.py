from schemas import TriageManifest, SourceArtifact, ArtifactClassification, ArtifactType
from theater import TheaterBroadcaster
from agents.client import generate_structured, MODEL_FLASH_LITE
from google.genai import types

async def triage_agent(artifacts: list[SourceArtifact], broadcaster: TheaterBroadcaster) -> TriageManifest:
    contents = "Classify artifacts.\n"
    for a in artifacts:
        contents += f"Artifact: {a.filename}\nText: {a.raw_text[:2000]}\n"
    
    # In a real impl we use LLM. For mock/safety if LLM not set:
    classifications = []
    for a in artifacts:
        t = ArtifactType.OTHER
        if "brand" in a.filename.lower() or "tracker" in a.filename.lower(): t = ArtifactType.BRAND_TRACKER
        elif "segment" in a.filename.lower(): t = ArtifactType.SEGMENTATION_STUDY
        elif "transcript" in a.filename.lower(): t = ArtifactType.VERBATIM_CORPUS
        elif "crm" in a.filename.lower() or "csv" in a.filename.lower(): t = ArtifactType.CRM_EXPORT
        
        classifications.append(ArtifactClassification(
            artifact_id=a.artifact_id,
            artifact_type=t,
            confidence=0.9,
            extraction_strategy="default"
        ))
        await broadcaster.emit("triage", f"Classified {a.filename} as {t.value}")
    
    return TriageManifest(classifications=classifications)
