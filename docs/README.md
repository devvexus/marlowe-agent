# Marlowe — documentation

Start at the [project README](../README.md) for what Marlowe is and why. This page is a map of
what is in `docs/`.

Requirements say what the system must do; design says how it is built and what has been settled.
Where the two disagree, the design documents are the ones kept current — requirements are long and
are read only when the design documents do not answer the question.

## Design — read these first

| Path | What it is | When to read |
|---|---|---|
| [`design/ARCHITECTURE.md`](design/ARCHITECTURE.md) | Component boundaries, the core abstraction, the agent loop | Before touching any subsystem |
| [`design/CONTRACTS.md`](design/CONTRACTS.md) | Pinned schemas and type signatures | Before any code crossing a boundary |
| [`design/DECISIONS.md`](design/DECISIONS.md) | Settled choices with their rationale | Before proposing an alternative |
| [`design/adr/`](design/adr/) | ADR-030 onward, one file each; earlier ones are inline in `DECISIONS.md` | For the argument behind a decision |
| [`design/ROADMAP.md`](design/ROADMAP.md) | Milestone sequence and the kill criteria | To find current scope |
| [`design/SECURITY-AUDIT.md`](design/SECURITY-AUDIT.md) | Open security findings — a standing ledger, not a closed report | Before touching any of the five layers |
| [`../STATE.md`](../STATE.md) | Built / next / known issues | At the start of every session |

## Design — subsystem and session documents

| Path | What it is |
|---|---|
| [`design/M3-DESIGN.md`](design/M3-DESIGN.md) | The agent tree, typed upward channels, and what runs on the control plane |
| [`design/SCOPED-MEMORY.md`](design/SCOPED-MEMORY.md) | Scoped memory and instillation — designed, not built |
| [`design/PI-MODEL.md`](design/PI-MODEL.md) · [`design/PI-SESSION-PLAN.md`](design/PI-SESSION-PLAN.md) · [`design/SESSION-PI-KICKOFF.md`](design/SESSION-PI-KICKOFF.md) | The principal-investigator model and its session plan |
| [`design/AGENT-DIRECTORY.md`](design/AGENT-DIRECTORY.md) | The agent directory and the model level ladder |
| [`design/CAPACITY-SENSOR.md`](design/CAPACITY-SENSOR.md) | GPU capacity measurement, and why the obvious sensor is unreliable |
| [`design/REDTEAM-SESSION.md`](design/REDTEAM-SESSION.md) | The scheduled red-team passes and what a zero from them does and does not mean |

## Design — measurement and evaluation

| Path | What it is |
|---|---|
| [`design/PRECISION-COVERAGE.md`](design/PRECISION-COVERAGE.md) | The published precision/coverage curve and the declared operating point |
| [`design/HARM-WEIGHTED-PRECISION.md`](design/HARM-WEIGHTED-PRECISION.md) | Why R@1 was inflated across the whole project, and the correction |
| [`design/EVAL-PRODUCT-DIVERGENCE.md`](design/EVAL-PRODUCT-DIVERGENCE.md) | Where the eval harness and the shipped product stop describing the same system |
| [`design/ANALOGICAL-RETRIEVAL.md`](design/ANALOGICAL-RETRIEVAL.md) | Retrieval beyond lexical and dense cues |
| [`design/spike-2026-08-04-embedder.md`](design/spike-2026-08-04-embedder.md) · [`design/spike-2026-08-04-cross-encoder.md`](design/spike-2026-08-04-cross-encoder.md) · [`design/spike-2026-08-01.md`](design/spike-2026-08-01.md) | The spikes the model choices rest on |
| [`design/CI.md`](design/CI.md) | What runs automatically, and what deliberately does not |

## Requirements

Long, and not loaded by default.

| Path | What it is |
|---|---|
| [`requirements/01-brief.md`](requirements/01-brief.md) | The engine |
| [`requirements/02-addendum-secretary.md`](requirements/02-addendum-secretary.md) | The secretary layer |
| [`requirements/03-addendum-terminal.md`](requirements/03-addendum-terminal.md) | The terminal interface — read before any interface work |
| [`requirements/04-addendum-persona.md`](requirements/04-addendum-persona.md) | The persona — read before any user-visible prose |
| [`requirements/proposed-K1-amendment.md`](requirements/proposed-K1-amendment.md) · [`requirements/proposed-research-memory.md`](requirements/proposed-research-memory.md) | Proposals, kept separate from the accepted set |

## A note on the persona

The persona is a versioned artifact in [`../persona/`](../persona/), not a section of a document.
`persona/v2.md` is what ships; every byte of it is sent to the model, so it contains the persona
text and nothing else — no header, no version comment. Anything explanatory lives in
[`../persona/README.md`](../persona/README.md).
