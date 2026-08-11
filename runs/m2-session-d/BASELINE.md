# M2 Session D — the pre-D2 baseline, measured

Taken **after** `PREDICTION.md` was written and **before** any code was changed, on 2026-08-11,
branch `master` at `f85e2e0` plus nothing. Re-measured on this machine rather than cited from
STATE.md, per the standing rule that a measurement is scoped to the system it was taken on.

Binary: `target/release/marlowe.exe`, built this session, `cargo build --release --jobs 4` clean.

Target:

```
exec://../target/release/marlowe.exe --eval-adapter --profile-root {profile_root}
      --embedder-model ../models/jina-embeddings-v2-small-en
      --reranking ../models/ms-marco-MiniLM-L-2-v2-ft-session-j
```

## cargo

```
cargo test --workspace --jobs 4      583 passed, 0 failed, 2 ignored      exit 0
```

One run, to a file. STATE.md's last recorded full-workspace number was 561; everything between was
verified per-crate only.

## conformance

```
{
  "clock_probe": "fail_no_time_dependence",
  "conforms": false,
  "findings": [],
  "interfaces_probed": ["ingest", "retrieve", "answer"]
}

REJECTED: 0 finding(s); clock probe fail_no_time_dependence.        exit 1
```

Unchanged since M0b Session B, and exactly what `PREDICTION.md` recorded as the expected baseline
before this was run.

## repro

```
e796c12e80199f1eb78dd90ee3d5bd1f1eb1ca63225d18e6856123c6392443e3
e796c12e80199f1eb78dd90ee3d5bd1f1eb1ca63225d18e6856123c6392443e3

2 runs at seed=7 clock=1780000000000: IDENTICAL                     exit 0
```

`--embedding-cache` omitted deliberately: two cold runs re-embed everything, so the determinism
check covers the embedder across process spawns as well as the ranking.

The prefix matches the `e796c12e…` C2d recorded. That is a re-measurement, not a citation — the
repo has moved out of OneDrive and `target/` was rebuilt since, either of which could have moved it.

## An instrument defect caught on the way, recorded because the rate is the argument

The first `repro` invocation **never ran**. `cd eval && …` was issued from a shell already in
`eval/`; `cd` failed, `&&` short-circuited, and nothing executed — but the harness's task
notification reported **exit code 0**, because that is the wrapper's exit rather than the command's.
The output file did not exist, which is the only reason it was caught.

**A background task reporting success is a statement about the wrapper, not about the command.**
Same family as the capability-vs-emission reports this project keeps logging: the reading was
authoritative, cheap, and about a different question. Every timed or scored run in this session is
confirmed by reading its output file, not by its exit status.
