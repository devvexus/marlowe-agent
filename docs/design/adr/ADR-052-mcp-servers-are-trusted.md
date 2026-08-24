# ADR-052 — MCP servers are trusted. Their output is not.

**Status:** accepted, shipped
**Date:** 2026-08-24
**Milestone:** M2 Session C3
**Decided by:** the human, explicitly, overruling the session's own proposal.

---

## 1. The decision

**An installed MCP server is TRUSTED.** Its tool descriptions are ordinary prose and reach the model
as descriptions. They are not marked `UntrustedContent`, no `ToolSchemas` block is pushed into the
context, and registering a server does not latch the run's trust floor.

**The rationale, which is the part that must survive:** a user installing an MCP server is making an
authorization decision. They chose it, they added it, and inspecting what they install is their
responsibility — the same standing every other harness gives an installed server. **The agent does
not add MCP servers on its own initiative, so there is no path by which untrusted content chooses
one.**

### What this overruled, recorded because the reasoning is instructive

The session proposed the opposite: that `Description::trust()` having one caller — a test — was a
defect to close by pushing third-party descriptions into the assembled context at
`UntrustedContent`, where the composed-target check would refuse on them.

That would have been coherent and it would have been wrong. Its consequence, stated in the plan and
approved as a trade before being overruled, was that **registering one MCP server would block every
model-composed target for the life of the run** — the model could no longer choose a path to edit or
a command to run. Applied to something the user deliberately installed, that treats the user's own
decision as an attack.

Brief §7.2 reads *"MCP servers are untrusted input. Tool descriptions are an injection vector by
construction."* This ADR revises that for descriptions and leaves it exactly in place for output.
`registry.rs`'s module header carried the old position until this session and now carries this one.

## 2. Two conditions, and they are not carve-outs

### 2.1 A trusted server is not trusted output

**MCP tool results are `UntrustedContent`, unconditionally.**

This is not an exception bolted onto §1; it is the existing rule, unchanged. `read` is a fully
trusted builtin whose *description* is authored in this repository and whose *file contents* are
untrusted. So are `bash`'s output and `web`'s pages. **Trust attaches to who wrote the tool, never to
what the tool hands back at runtime.**

`marlowe-contract`'s own definition has read *"web, inbound mail, MCP server output, third-party
skill output"* since it was written. C3 is the first code to make the third of those true.

The class is set with **no branch on the server, the tool, or whether the call succeeded**. `isError`
is not a discriminator: an error message is content the server chose too, and a failed call is
exactly where a hostile server would put a payload the success path does not look at.

**The consequence is that layer 1 fires without anybody asking.** `Engine::condense_batch` triggers
on `blocks_composed_targets` — *the trust class, not the tool name* — which is precisely why ADR-039
keyed it that way, and why a new tool returning untrusted content is covered without anyone
remembering to add it. Nothing in `marlowe-mcp` or `mcp.rs` requests containment and nothing in them
can opt out of it.

If MCP results became trusted alongside descriptions, layer 1 would have a hole in it that has
nothing to do with the decision in §1.

### 2.2 The consent is to text the user read, so the text is pinned — §4 below.

## 3. Stdio, not HTTP, and the reason is layer 4

MCP has two standard transports. `marlowe-mcp` implements **stdio**: a child process, JSON-RPC over
its stdin and stdout, one message per line.

**The HTTP transport is deliberately not implemented.** Egress allowlisting is layer 4 of five, it is
ADR-031/ADR-032 approved and **not shipped** — `EgressPolicy::grant()` still has no production call
site — and putting a remote server's bytes on the wire with nothing allowlisting the destination
would be the first production egress path in the product, arriving as a side effect of a
skills-and-tools session.

**The dependency list is the enforcement, not the comment.** `marlowe-mcp` does not depend on
`marlowe-net`, so it has no TLS and no socket, and `cargo tree -p marlowe-mcp` says so.
`no_socket_reaches_this_crate` asserts it from the manifest — ADR-031 §2.3's discipline applied to a
second crate.

A local child process is not layer 4 dressed up: the user named the command, their own shell could
run it, and nothing here decides a destination. What that process does with its own network access
is outside every boundary this project has — which is equally true of `bash`, and is recorded in
ADR-049 §4 rather than implied.

## 4. Descriptions are pinned at install, and a change re-asks

**§1's argument is only sound while the text the user inspected is the text that gets sent.**

An MCP tool list is fetched from a live process on **every connect**. The description reviewed at
install is not necessarily the description in turn forty's request body. A server that ships one
description on day one and another on day nine has converted the user's consent into a formality:
they approved text they will never see again. Mutating tool descriptions after install is a known
attack on live-fetched tool lists, and it is the specific way §1 can be made false without anyone
doing anything wrong at the moment it happens.

So each description is hashed at install, and a change re-asks **naming the tool**:

```
marlowe: mcp 2 tool(s) from 1 server(s)
marlowe:   ! `probe__hostile` describes itself differently than when it was installed.
             Re-read it before using it.
```

Three verdicts, not two. A tool that is merely **new** is a different event from one whose
description **changed under a name the user already approved**, and `Changed` outranks `New` when a
connect did both: one invalidates a decision the user already made, the other is a decision they have
not made yet.

**The hash is over the sanitised text — what renders, not the raw bytes.** The user is consenting to
what they can see. Hashing raw bytes would fire a prompt on a change invisible to them, which trains
people to accept prompts; the converse is closed by the sanitiser rather than the hash, because two
strings differing only in invisible characters now render as distinct `<U+XXXX>` markers.

**This is not a signature and not an integrity check against the server.** Nothing here authenticates
who changed the text, and nothing prevents a server from changing it. The only claim is: *this is not
the text the user approved, so ask.* Naming that boundary matters, because a hash in a security
module invites the reading that something is being verified.

**An empty pin file treats every tool as new, never as approved.** A missing file must not read as
blanket approval.

## 5. Exposure, and a budget that refuses by name

MCP tools **consume exposure slots**. The interactive set is ten of ARCHITECTURE §5's twelve after
ADR-051 exposed `use`, so **two MCP tools fit and a third does not**.

`CapabilityProfile::interactive_with` widens the base set and returns `ExposureError::TooMany`, which
names the count and the remedy. It refuses at load rather than dropping the overflow: a server whose
third tool quietly vanished would look like a server with a broken tool. **The refusal names the
budget rather than picking a victim** — which builtin to give up is the user's call.

Widening exists here and nowhere else. `narrowed` has no counterpart on purpose, because a **spawn**
may only narrow and `WidenedPastParent` enforces it. This is not that: it is how a top-level profile
is *built*, it takes no parent, and a child of the profile it returns is still narrowed against it.

**One registry, three call sites.** `builtin_registry()` was called separately for the `Engine` and
for each driver — already a duplication hazard, and a real defect the moment the registry has a
per-profile component. An `Engine` that knows a tool and a driver that does not would offer the model
nothing and refuse nothing, and the symptom would be a tool the user installed that the model never
mentions. `tool_registry()` is now the one builder.

## 6. Consequences, including two the reader should not have to infer

- **`Description::trust()` and `Transport::description_trust()` are DELETED**, not left returning a
  value nobody reads. The only caller `trust()` ever had was a test asserting its own declaration —
  this repository's most-repeated defect, which does not improve by having a reason. `Description`
  no longer carries a `TrustClass` and `Description::new` no longer takes a `Transport`.
  `manifest_provenance()` still records third-party-ness for the **manifest**, which is a different
  question and is untouched.
- **`registry.rs`'s module header and `ollama.rs`'s comment both said something false and now do
  not.** The adapter comment read *"containment is the trust class and the assembler's tier"* —
  naming two defences, **neither of which runs on that path**. A description never enters a
  `ContextView`, so no tier applies to it and no trust floor sees it; it goes into the `tools` array
  and nowhere else. Two mechanisms cited where zero were operating.
- **Every MCP parameter loads as `ArgumentRole::Target`, fail-closed.** An MCP schema does not say
  which arguments choose a destination, and the adjudicator's own default for an undeclared argument
  is `Target` for the same reason.
- **Consequence defaults to `Irreversible`**, which `adjudicate` turns into an approval prompt on
  every call. Nothing in the protocol carries this, and nothing should infer it; a user who knows
  better declares it per server in `mcp.json`. Absent means maximum — §7.3's rule applied where the
  information genuinely is not available.
- **Tool ids are namespaced `<server>__<tool>`.** Two servers offering `search` would otherwise
  collide, and whichever registered second would be refused — reading as "the second server is
  broken". Two underscores because tool names are matched by string equality throughout the
  codebase and a `/` or `:` would require every one of those to learn about namespacing.
- **A malformed `mcp.json` refuses to start.** Starting with the servers a broken parse happened to
  reach gives the user half their tools and no statement that anything went wrong.
- **MCP calls are served serially**, not concurrently: one client owns one child's pipe, so two
  calls in flight on one server would interleave. Everything else in a batch is still delegated as
  one batch, so the inner host's concurrent fetch is untouched.

## 7. What ADR-052 does NOT change — the display sanitiser, which matters MORE now

`registry.rs:89`'s `char::is_control` was `Cc` and nothing else. U+2028/U+2029, the whole of `Cf`
including U+202E RIGHT-TO-LEFT OVERRIDE and the zero-width block, and the tag characters at U+E0000
all walked into a model-visible **and user-visible** tool list. It now routes through
`marlowe_contract::text`, the project's single definition of what may be displayed.

**Trusting the source does not make invisible characters visible.** Trust governs *authority* — may
this text direct action. It says nothing about whether the text **displays as what it reads**. This
decision rests a third-party tool's safety entirely on the user having inspected what they
installed, so **a character that makes a description render differently than it reads is an attack on
the exact mechanism the decision depends on**. A bidi override defeats the inspection, and the
inspection is now the only control in the path.

Asserted where the bytes go — the `request_body` of **both** adapters — and not on
`Description::text()`, because asserting on the constructor's return value asserts a declaration.

## Verification

| Claim | How |
|---|---|
| A real server answers over a real pipe | `mcp_output_is_untrusted.rs` spawns `tools/probe_mcp_server.py` and handshakes |
| Its result is `UntrustedContent` | same file; mutation `mcp_trust` fails exactly that test |
| The parent never sees the raw bytes | `the_hostile_response_does_not_reach_the_parents_window`, through a real `Engine::run` |
| …and that absence means something | **the control**: identical bytes at `AgentObserved` **do** reach the parent |
| A changed description re-asks | `pin.rs` tests; mutation `pin_reconsent` fails three of them; **seen live**, END-TO-END §2 |
| No socket in the transport | `no_socket_reaches_this_crate`, read from the manifest |
| Invisible characters do not reach the wire | `a_description_cannot_forge_its_own_rendering.rs`, both adapters; mutation `desc_sanitiser` |
| Two MCP tools fit the budget and a third refuses by name | `composition_root.rs`. **Added at the close-of-session audit** — §5's claim had no test, and `STATE.md` said it did |
| A malformed `mcp.json` refuses | `composition_root.rs`, with a well-formed control at the same path |
| A batch survives all three wrappers | `composition_root.rs`; mutations `skilltools_batch` and `mcptools_batch` |

**And once in the product.** `runs/session-c3/END-TO-END.md` §4: the model called two MCP tools on a
real server; the journal records **2 `run_spawned`, 0 `run_failed`** — one quarantined reader per
result group — and the parent answered from a validated summary, having never seen the injected
instruction or the probe token.
