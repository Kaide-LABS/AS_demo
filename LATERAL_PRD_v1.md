# LATERAL_PRD_v1.md

## The Concept

### Batch Upload Calibration Foundry

This version solves the onboarding bottleneck through a single high-trust batch upload flow inside Radiant. The enterprise team drops every available artifact into one workspace at once, and the sidecar performs full-document extraction, contradiction resolution, and calibration assembly before Tom Whittle's simulation engine is ever invoked.

This is the closest lateral variant to the current sidecar thesis, but the architecture is deliberately optimized for "one-shot, zero-prep" onboarding rather than iterative back-and-forth. It is a stateless upstream service that emits one validated `RadiantPersonaCalibration` JSON payload and nothing else. It never touches the social graph engine, the persona network logic, or the simulation runtime.

## The Strategic Hook

- Patrick Sharpe is the natural buyer for this version because the context repeatedly frames his product posture around radical workflow compression and "running customer research 100s faster." A batch-first intake removes the slowest part of enterprise setup: manually normalizing dozens of documents before a simulation can even start.
- James He is also aligned because the context notes that UI and enterprise readiness are major scaling constraints. A one-drop intake makes the platform feel like a finished enterprise product rather than a consultancy workflow hidden behind a form.
- Tom Whittle should prefer this version when the priority is clean separation. The sidecar is pure upstream ETL plus validation. The handshake to core remains one JSON contract.

## The Agent Architecture

### Core Principle

`Gemini 1.5 Flash` handles cheap, parallel extraction and routing. `Gemini 1.5 Pro` handles global synthesis, contradiction resolution, and final structured calibration drafting. A deterministic Pydantic layer is the only gate allowed to certify output.

### Pipeline

1. `Artifact Intake Agent`  
   Input: uploaded PDFs, PPT exports, CSVs, XLSX files, DOCX files, survey exports, transcript bundles.  
   Logic: MIME detection, parser selection, OCR fallback where needed.  
   Output: normalized `SourceArtifact[]` with text, tables, metadata, and location anchors.

2. `Routing Agent` using `Gemini 1.5 Flash`  
   Task: classify each artifact into `brand_guidelines`, `campaign_performance`, `segment_study`, `survey_export`, `transcripts`, `crm_segments`, `other`.  
   Output: routing manifest with extraction strategy per file.

3. `Parallel Extraction Agents` using `Gemini 1.5 Flash`  
   Task groups:
   - segment extractor
   - message constraint extractor
   - brand tone extractor
   - KPI and campaign benchmark extractor
   - demographic and psychographic extractor
   - quote and evidence extractor  
   Each agent emits strict partial JSON matching a Pydantic sub-schema.

4. `Evidence Merger`  
   Non-LLM logic merges all partial JSON into a draft evidence graph keyed by candidate field names required by `RadiantPersonaCalibration`.

5. `Conflict Resolver` using `Gemini 1.5 Pro`  
   Task: inspect conflicting evidence across sources, resolve duplicates, rank source authority, identify missing fields, and produce a coherent calibration draft with citations.

6. `Calibration Composer` using `Gemini 1.5 Pro`  
   Task: emit a full draft `RadiantPersonaCalibration` object with segment weights, behavioral dimensions, brand constraints, scenario context, and provenance.

7. `Deterministic Validation Layer`  
   Pydantic checks:
   - exact schema compliance
   - segment weights sum to 1.0
   - all enum values are canonical
   - every generated field has at least one citation
   - required fields cannot be inferred from zero evidence
   - forbidden keys are stripped
   - confidence bands match evidence density

8. `Repair Loop`
   - if Pydantic or deterministic rules fail, emit a narrow repair prompt to `Gemini 1.5 Pro`
   - max 2 repair attempts
   - unresolved fields become explicit `needs_user_confirmation`

### Data Passing Map

`Upload UI -> parsers -> Gemini 1.5 Flash routing -> Gemini 1.5 Flash parallel extractors -> deterministic evidence merger -> Gemini 1.5 Pro conflict resolver -> Gemini 1.5 Pro composer -> Pydantic validator -> final JSON`

## The "Native Environment" UI Spec

### Entry Point

Inside Radiant project setup as `Step 2: Upload Brand Context`.

### Required UI Elements

- large drag-and-drop upload surface
- per-file classification chips
- live pipeline activity rail on the right
- evidence completeness bar
- "missing critical inputs" callout when required source classes are absent
- preview drawer showing extracted constraints and supporting citations
- primary CTA: `Generate Calibration JSON`
- handoff CTA after validation: `Load Into Simulation`

### UX Rules

- batch upload must support at least 25 files in one session
- every extracted claim shown in UI must be expandable to source citation
- no simulation controls are shown until calibration validates
- errors must be explicit and field-specific, never generic

## Phase 1 Execution Spec

1. Build a FastAPI sidecar with endpoints:
   - `POST /calibration/jobs`
   - `GET /calibration/jobs/{id}`
   - `GET /calibration/jobs/{id}/events`
2. Implement file parsers for PDF, DOCX, TXT, CSV, XLSX, and JSON exports.
3. Define Pydantic models:
   - `SourceArtifact`
   - `ExtractedSegment`
   - `BrandConstraint`
   - `CampaignSignal`
   - `CalibrationFieldEvidence`
   - `RadiantPersonaCalibration`
4. Implement `Gemini 1.5 Flash` prompts for routing and partial extraction.
5. Implement a deterministic evidence merger keyed to the final JSON schema.
6. Implement `Gemini 1.5 Pro` prompts for conflict resolution and final composition.
7. Add rule-based validation plus two-attempt repair loop.
8. Build a React intake screen with upload, processing rail, and citation preview.
9. Add a fixture bundle of representative enterprise files and run contract tests against the output JSON.
10. Ship the sidecar as an isolated service with a single downstream contract: validated calibration JSON only.
