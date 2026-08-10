# ADR-034 — Requiredness is a separate field from `ArgumentRole`, because they answer different questions

**Status:** ACCEPTED (M2 C2e/C2f). Code landed in `de18ace`; this is the record and the CONTRACTS amendment.
**Amends:** CONTRACTS §7.3 (`ParamSpec`)
**Extends:** ADR-026 (declared consequence), ADR-006 (the eleven builtins)

## 1. Context

`required` in the JSON tool schema was derived from `ArgumentRole::Target`. One switch answered two
questions:

- **`role`** — *what may untrusted content never shape?* A security property. §9 checks it.
- **`required`** — *what can the executor not run without?* An arity property. The model reads it.

They correlate. A path is usually both. Binding one to the other produced **eleven measured
mismatches across ten builtins**, in both directions:

| tool | sent as required | what the executor wants |
|---|---|---|
| `bash` | `command`, `cwd` | `command`; `cwd` defaults to the workspace |
| `find` | `path` | `pattern` — it fails without it |
| `edit` | `path` | `path` **and** `content` |
| `remember` | `derived_from`, `payload_kind` | the claim itself |
| `ask` | *nothing* | the question |
| `run` | three spawn args | the task |
| `recall` | `payload_kind` | the query |

Two directions of failure, and the second is worse. Nine parameters were marked required that are
not, so the model invented a `cwd` on every shell call. Two the executor demands were marked
optional — `find.pattern`, `edit.content` — so a **schema-valid call the executor rejects** was
reachable, which reads as a model error and is ours.

**And the correction repeated the error.** After a refusal, `Engine::expected_params` handed the
model the same wrong list. A model told the wrong thing and then corrected with the same wrong thing
is worse off than one told nothing.

## 2. Decision

`ParamSpec` gains `required: bool`, independent of `role`. Four constructors —
`target_req`/`target_opt`/`payload_req`/`payload_opt` — so a registration must answer both questions
and cannot answer one by accident.

**All three sites changed together**, which is the load-bearing part: the JSON schema
(`tool_schema`), the model-facing prose (`param_description`), and the post-refusal correction
(`Engine::expected_params`). Any one left behind would keep telling the model the old thing on the
path that matters most.

`RawParamSpec::required` defaults to **optional** when a manifest omits it — the safe direction. An
over-required schema forces a model to invent values; an under-required one produces a call the
executor rejects with an error the model can read and correct.

## 3. CONTRACTS §7.3 is amended

The pinned schema read:

```rust
pub struct ParamSpec { pub name: String, pub role: ArgumentRole, pub ty: ParamType }
```

Shipped code has carried a fourth field since `de18ace`. **A pinned contract that shipped code
contradicts is worse than an out-of-date one** — it is the document a boundary-crossing change is
checked against, and it was silently wrong. Amended to match.

## 4. Consequence, and one test inverted deliberately

`persona_emission.rs::the_web_tool_requires_its_target` was written against the conflation and is
now **inverted**: `web` is search and fetch, so a search has no `url` and a fetch has no `query`.
Declaring `url` mandatory told the model a search was impossible. Neither is required; what must
hold is that both are **offered**, and the executor validates the pair.

Verified on the wire with `MARLOWE_DUMP_BODY=1`:

```
read required=[path]   edit required=[path,content]   find required=[pattern]
bash required=[command]   ask required=[question]   remember required=[text]   run required=[task]
```

**Descriptions were corrected in the same commit**, for the same reason: `bash` said *"persistent
shell session"* (a fresh `cmd /C` per call), `find` said *"index-backed symbol lookup"*
(`line.contains`), `edit` said *"atomic"* (`set_len(0)` + rewrite), `read` said *"blob, or
reference"* (no parameter accepts either). Asked to showcase its tools, the model produced a
**fabricated shell transcript** containing `# symbol search finds ... in the repo index` — echoing
our own false description back. Model-visible prose that makes the model call things wrongly and
then blame itself.

`web`'s description is the one still outstanding: it promises search. It is corrected when `web`
ships (ADR-031).
