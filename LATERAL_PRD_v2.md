# LATERAL_PRD_v2.md

## The Concept

### Connector-Led Calibration Harvester

This version solves the same onboarding bottleneck through source connectors instead of manual batch uploads. The enterprise user authenticates approved systems such as Google Drive, SharePoint, Box, Qualtrics export folders, or an internal S3 bucket, and the sidecar pulls only the documents needed to build the initialization JSON.

The lateral shift here is the entry point and data flow: instead of asking the client to assemble files first, the system performs guided source discovery across the customer's existing content estate. The result is still a single validated `RadiantPersonaCalibration` payload upstream of the simulation engine.

## The Strategic Hook

- Patrick Sharpe may prefer this version because it removes manual prep work from already-busy enterprise teams. In regulated and complex organizations, the friction is often not "understanding the simulation" but "finding and packaging the right documents." Connector-led harvesting attacks that directly.
- James He may prefer it because it looks more enterprise-native and defensible in procurement-heavy accounts. It turns Radiant from an impressive model into an operational system that can fit real corporate data environments.
- Tom Whittle should like that it keeps all ugliness in a disposable sidecar instead of polluting the core product with integration logic.

## The Agent Architecture

### Core Principle

`Gemini 1.5 Flash` is used for large-scale source triage and document scoring. `Gemini 1.5 Pro` is reserved for cross-document synthesis and gap planning. Pydantic remains the hard gate.

### Pipeline

1. `Connector Orchestrator`
   - connects to approved enterprise data sources
   - crawls folder metadata, filenames, recency, owners, and document previews
   - never writes into those systems

2. `Document Relevance Screener` using `Gemini 1.5 Flash`
   - scores candidate artifacts against the target simulation brief
   - labels each file as `include`, `hold`, or `ignore`
   - outputs evidence on why each file matters

3. `Source Selection Planner` using deterministic heuristics
   - chooses the minimum viable document set for calibration
   - enforces quotas by source type so Pro context is not wasted on noise

4. `Structured Extractors` using `Gemini 1.5 Flash`
   - extractor for audience definitions
   - extractor for brand and tone constraints
   - extractor for prior campaign signals
   - extractor for stakeholder language and taboo phrasing
   - extractor for segmentation logic and audience cuts

5. `Coverage Auditor` using `Gemini 1.5 Pro`
   - reviews the assembled evidence set
   - identifies schema fields not yet supported
   - recommends an additional fetch pass if necessary

6. `Incremental Fetch Loop`
   - deterministic connector layer retrieves only the additional files requested by the auditor
   - this prevents full-repo over-ingestion and keeps cost bounded

7. `Calibration Composer` using `Gemini 1.5 Pro`
   - composes the final schema-constrained JSON with citations

8. `Pydantic Validation Layer`
   - validates object shape
   - verifies source lineage
   - verifies all required onboarding fields are present
   - verifies confidence and freshness thresholds

### Data Passing Map

`Connector auth -> metadata crawl -> Gemini 1.5 Flash relevance screening -> deterministic source planner -> Gemini 1.5 Flash extraction -> Gemini 1.5 Pro coverage audit -> optional second fetch -> Gemini 1.5 Pro composition -> Pydantic validation -> final JSON`

## The "Native Environment" UI Spec

### Entry Point

A new Radiant setup path called `Connect Existing Research Sources`.

### Required UI Elements

- connector cards for approved enterprise systems
- permission summary panel showing exactly what will be read
- simulation brief box to focus retrieval
- ranked document list with include or exclude toggles
- coverage map showing which schema fields are already supported
- audit banner when the system requests one more source
- final preview of calibration object before handoff

### UX Rules

- the user must be able to complete setup without downloading files locally
- every connector read must be logged and visible in the UI
- the system should stop fetching as soon as minimum viable evidence is reached
- no hidden ingestion of unrelated folders

## Phase 1 Execution Spec

1. Build a sidecar service with OAuth and service-account based connector support.
2. Start with two connectors only for MVP:
   - Google Drive
   - SharePoint or S3
3. Implement metadata-only crawl before any file content retrieval.
4. Build the `Gemini 1.5 Flash` relevance scorer against title, snippet, path, and preview text.
5. Create a deterministic planner that caps how many files of each type can enter the synthesis phase.
6. Build targeted content fetch for only approved files.
7. Implement extractor prompts and partial Pydantic models.
8. Implement a `Gemini 1.5 Pro` coverage auditor that identifies missing schema areas.
9. Support one optional second retrieval pass.
10. Build React screens for connector auth, ranked files, coverage status, and final JSON approval.
11. Add audit logging and export of the source manifest used to build the calibration.
