# LATERAL_PRD_v3.md

## The Concept

### Conversational Calibration Copilot

This version attacks enterprise onboarding friction through an interview-led flow rather than document-first ingestion. The user starts with a short business brief, and the sidecar runs a structured interview that requests only the missing artifacts and clarifications needed to populate the rigid initialization schema.

The lateral difference is that the sidecar does not begin from "upload everything." It begins from the simulation objective, builds a field-level missing-data map, and then pulls the minimum evidence required to complete the JSON. This is still strictly upstream of the core engine.

## The Strategic Hook

- Patrick Sharpe may prefer this version because it is the fastest path to first value for teams that do not have neat research folders ready. It minimizes user effort and keeps the product feeling like software rather than a consulting upload portal.
- James He may prefer it because it presents Radiant as a decision interface, not just a file processor. The user feels like they are already shaping a simulation rather than performing admin work.
- Tom Whittle should prefer the architecture when the goal is a thinner and more explainable intake path with fewer heavy files moving through the system.

## The Agent Architecture

### Core Principle

`Gemini 1.5 Pro` plans the interview and maintains the schema-level gap model. `Gemini 1.5 Flash` handles rapid answer normalization, artifact parsing, and field-level extraction. Pydantic remains the hard authority.

### Pipeline

1. `Brief Interpreter` using `Gemini 1.5 Pro`
   - takes a short campaign or stakeholder brief
   - maps it to required calibration fields
   - creates a missing-information plan

2. `Interview Manager` using `Gemini 1.5 Pro`
   - asks the next best question
   - decides whether the next step should be a user answer, a file request, or a connector request
   - keeps questions tightly tied to missing JSON fields

3. `Answer Normalizer` using `Gemini 1.5 Flash`
   - converts free-text user answers into typed candidate values
   - attaches confidence and missing evidence flags

4. `On-Demand Artifact Extractors` using `Gemini 1.5 Flash`
   - triggered only when the interview manager requests a file
   - extract just the fields currently missing

5. `Schema State Store`
   - deterministic in-memory or ephemeral job state
   - tracks each required field as `unknown`, `candidate`, `validated`, or `blocked`

6. `Calibration Reconciler` using `Gemini 1.5 Pro`
   - periodically reviews the field state
   - collapses overlapping evidence
   - decides whether enough confidence exists to draft final JSON

7. `Pydantic Validation Layer`
   - validates the final object
   - rejects unsupported inferences
   - forces open questions to remain explicit instead of silently invented

### Data Passing Map

`Brief -> Gemini 1.5 Pro interview planner -> user answers and requested files -> Gemini 1.5 Flash normalization/extraction -> deterministic field state store -> Gemini 1.5 Pro reconciler -> Pydantic validation -> final JSON`

## The "Native Environment" UI Spec

### Entry Point

`Start With A Brief` inside Radiant onboarding.

### Required UI Elements

- a single large brief composer to start the flow
- chat-style interview surface
- right-side schema checklist showing which fields are complete
- file request drawer for just-in-time artifact uploads
- confidence meters per section
- explicit unresolved issues panel
- final `Generate Calibration JSON` action when all required sections are green

### UX Rules

- the interview must never ask broad or redundant questions
- every question must map to one or more missing schema fields
- the user must always see progress toward a valid simulation-ready payload
- the system must permit proceeding with explicit gaps only if those gaps are marked for manual confirmation upstream of simulation launch

## Phase 1 Execution Spec

1. Define the full target initialization schema and break it into user-understandable sections.
2. Build a field-state engine that tracks progress by schema field, not by conversation turn.
3. Implement a `Gemini 1.5 Pro` prompt that generates the next best question from the current missing-data map.
4. Implement `Gemini 1.5 Flash` answer normalization into typed candidate values.
5. Support ad hoc file upload when the interview requests evidence.
6. Build lightweight extractors that read only for currently missing fields.
7. Add deterministic rules that prevent unsupported field completion.
8. Build the chat UI plus a persistent schema progress rail.
9. Test with three onboarding scenarios:
   - fully prepared enterprise client
   - messy partially prepared client
   - client with only a short campaign brief and one deck
10. Keep the output contract unchanged: one validated calibration JSON handed to the existing simulation startup flow.
