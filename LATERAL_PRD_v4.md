# LATERAL_PRD_v4.md

## The Concept

### Schema-First Mapping Studio

This version solves the onboarding bottleneck by reversing the control model. Instead of asking the LLM system to infer the whole calibration in one pass, the product exposes the rigid initialization schema directly in a guided mapping studio. The sidecar then uses Gemini to populate each field or section from uploaded evidence, one schema block at a time.

The lateral shift is architectural discipline: the JSON schema becomes the primary interface, and the LLMs act as bounded field-population workers. This is the most deterministic variant and the one most likely to win with teams that want maximum inspectability.

## The Strategic Hook

- Patrick Sharpe may prefer this version if he wants the lowest-risk product behavior in enterprise settings. The user can see the exact structure being filled and can correct errors before simulation launch.
- James He may prefer it because it makes the path from messy research to simulation input legible and demoable in a boardroom. It visibly converts enterprise context into machine-ready structure.
- Tom Whittle should like it because it keeps the contract explicit and minimizes hidden agent behavior. The sidecar looks like a strict adapter to his engine, not an adjacent black box.

## The Agent Architecture

### Core Principle

`Gemini 1.5 Flash` works as a section-level mapper. `Gemini 1.5 Pro` is used only when a whole schema section depends on multi-document reconciliation or ambiguous tradeoffs. Pydantic validation happens continuously, not only at the end.

### Pipeline

1. `Schema Loader`
   - loads the exact target JSON schema and field definitions
   - groups fields into sections such as audience definition, segment weights, brand constraints, behavioral priors, and campaign context

2. `Section Prioritizer`
   - deterministic logic decides section order based on what is essential to start a simulation
   - marks `required now` versus `optional later`

3. `Section Mapper` using `Gemini 1.5 Flash`
   - for each section, consumes only the relevant evidence subset
   - outputs candidate values plus citations and confidence

4. `Complex Section Resolver` using `Gemini 1.5 Pro`
   - invoked only when a section spans conflicting documents or requires aggregation across many sources
   - examples: segment weighting or campaign-to-persona mapping

5. `Continuous Pydantic Validator`
   - validates each section as soon as it is filled
   - prevents invalid values from contaminating later stages

6. `User Review Layer`
   - UI exposes each section as draft, valid, invalid, or needs evidence
   - user can approve or reopen a section

7. `Final Object Assembler`
   - deterministic merge of validated sections into the final `RadiantPersonaCalibration`

### Data Passing Map

`Schema loader -> deterministic section prioritizer -> Gemini 1.5 Flash section mapper -> optional Gemini 1.5 Pro complex resolver -> continuous Pydantic validation -> user approvals -> deterministic final assembly -> final JSON`

## The "Native Environment" UI Spec

### Entry Point

`Advanced Mapping Studio` for enterprise implementation teams.

### Required UI Elements

- left navigation listing every schema section
- central field and evidence mapping canvas
- source panel showing uploaded documents and extracted snippets
- section validity badges
- per-field citation chips
- approve, reopen, and mark-missing controls
- final export and `Load Into Simulation` button only after all required sections validate

### UX Rules

- each field must visibly show whether it was user-entered, Flash-generated, or Pro-resolved
- the UI should support partial save and resume by job ID
- no field may be silently auto-filled without visible provenance
- the studio must be usable by solutions engineers and customer teams together during onboarding calls

## Phase 1 Execution Spec

1. Formalize the simulation initialization schema into sectioned Pydantic models.
2. Build a deterministic section dependency graph.
3. Implement evidence indexing so each document chunk can be retrieved by schema section.
4. Build `Gemini 1.5 Flash` prompts for section-level extraction only.
5. Build a `Gemini 1.5 Pro` escalation path for complex or conflicting sections.
6. Run Pydantic validation after every section update.
7. Build a React studio with section navigation, evidence panel, and per-field provenance.
8. Add user approval state on each section before final export.
9. Write contract tests that assert:
   - invalid sections cannot be exported
   - provenance is preserved on every field
   - final JSON matches the core engine contract exactly
10. Deploy as a standalone sidecar service and wire the final handoff button to the existing simulation launch path without any modification to Tom Whittle's engine.
