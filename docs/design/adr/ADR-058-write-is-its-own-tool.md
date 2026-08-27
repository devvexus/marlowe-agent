# ADR-058 — `write` is its own tool, and the exposure budget moves to thirteen

**Status:** accepted, 2026-08-27
**Supersedes nothing. Amends** ARCHITECTURE §5's `≤12` to `≤13`.

---

## §1. The decision

**A tool's name is the first thing a model matches against the verb in a request, and a tool with
two modes separated by an optional parameter forces a guess.** So:

| tool | parameters | what it does |
|---|---|---|
| `write` | `path`, `content` — **both required** | creates the file, or replaces all of it |
| `edit` | `path`, `replacing`, `content` — **all required** | replaces one exact snippet, fails if absent |

Neither has a mode. `edit` without `replacing` is refused **by name**, and the refusal names
`write`.

And **`MAX_EXPOSED_TOOLS` moves from 12 to 13**, so the eleventh builtin is not paid for out of a
user's MCP allowance.

---

## §2. What actually happened, because the argument is entirely evidence

Watched live 2026-08-26 on `qwen3.5:9b`, journal seq 4806–4864. The user asked for a handoff
document. The model's **first** action was not `edit`:

```text
seq 4806  tool_requested  bash
seq 4807  blast_radius    "cat > session-handoff.md << 'EOF' ..."
seq 4810  tool_failed     exit 1 · 1 line
```

Told to *write* a file, it went looking for a write verb, found none among the ten builtins, and
reached for the shell — where a heredoc fails under `cmd /C` with a bare exit code.

Only after that did it find `edit`, and then it picked the wrong mode:

```text
seq 4813  edit   "Session Handoff - 2087.md"  replacing set   → failed
seq 4820  read   "Session Handoff - 2087.md"  → 0 lines · 0 B
seq 4825  edit   "session-handoff.md"         replacing set   → failed
seq 4830  read   → 0 lines · 0 B
seq 4835  read   → 0 lines · 0 B
seq 4839  bash   dir "session-handoff.md"
seq 4859  edit   (no replacing)               → +52 −0
```

**Six calls and three minutes**, and `Session Handoff - 2087.md` left on disk at **0 bytes** —
because `path` is a `WritePath`, path scoping opens it `CreateOrOpen` before any executor runs, and
`"".find(replacing)` then cannot match.

## §3. Why the description was not the fix, and this is the general point

Three separate attempts were made to fix this with prose before the shape was changed:

1. `edit`'s description gained *"Without `replacing`, `content` becomes the whole file — **this is
   how you create one**"*.
2. `bash`'s description gained *"To write or change a file use `edit`, never this"*.
3. The refusal message gained a three-branch diagnosis naming the remedy.

All three are improvements and **none of them removes the choice**. A model holding a request and a
schema that offers `replacing` as optional still has to decide which tool it is in. The ambiguity
was in the shape, not in the wording, and prose cannot be the last line of defence against a shape.

This is the same reasoning that deleted the four undocumented `RawParamSpec` constructors earlier
the same day: **remove the way to get it wrong rather than documenting around it.** A test catches a
mistake; a missing constructor prevents one.

## §4. Why the budget moved instead of the MCP allowance

Splitting the tools took the exposed builtins from ten to eleven. Against a cap of twelve that left
an MCP server exactly **one** tool.

That is the wrong thing to have paid with. A fix to Marlowe's own surface should not shrink what a
user's server may offer, and one tool is not a usable budget for a server — `mcp.json` is not
hypothetical, and DECISIONS records that **MCPs are trusted because the user added them
deliberately**. Taking their slots to fund a builtin inverts that.

**Thirteen is arithmetic, not a new judgement**: eleven exposed builtins plus the two MCP slots the
budget has always meant. `composition_root.rs` now asserts `MAX_EXPOSED_TOOLS - builtins == 2` —
**the property is the two slots, not the number thirteen** — so a future builtin that eats one fails
the suite rather than passing quietly.

It carries **no spare**, deliberately. The next builtin raises this again, in the open, with a
reason. A cap that absorbed each new tool would be the permissive default this project keeps
deleting.

## §5. What this does not do

* **`read` is unchanged.** It is already targeted: `range` takes `first-last`, 1-based inclusive.
* **The zero-byte file is not prevented, only made unnecessary.** Path scoping opens a `WritePath`
  handle before any executor runs, so `edit` on a name that does not exist still leaves the file at
  zero bytes; `marlowe-exec` cannot tell one it just created from one that was already empty, and
  `scope/mod.rs` is a §13 path. `edit`'s refusal states the side effect instead. **What changed is
  that no model call needs to produce one** — `write` is one call with nothing to decide.
* **No consolidation of `find`.** A regex `find` and a `glob` are the next things asked for and are
  not decided here; `glob` would take the exposed builtins to twelve and needs its own amendment.
