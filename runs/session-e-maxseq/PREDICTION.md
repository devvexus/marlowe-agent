# Registered BEFORE the 1024 scoring run finished

Written while `score_longmemeval.py` was still embedding, against a baseline that already exists
(`fit-8192-BASELINE/`, session-level top-1 **0.9008**, 218/242). The point of writing it now is that
"the scores are the same except the truncated one" is a prediction, and a prediction stated after
seeing the result is a description.

## What actually changes between the two runs

`MAX_SEQ_LEN` 8192 → 1024 changes the embedding of **exactly the turns that exceed 1024 tokens**:
**453 of 246,750 (0.18%)**. Every other turn tokenizes identically and embeds identically, so its
vector is bit-identical and its ranking contribution is unchanged.

Of those 453:

- **1 is gold** — query `5809eb10`, losing 15 tokens of trailing boilerplate
  (`"...protected in the event of a dispute.\n\nPlease write in English language."`). The answer
  `2014` sits at character 917 of 5425 — **16.9% into the turn** — so it survives.
- **452 are distractors.** Their vectors move slightly. That is the only mechanism by which any
  other query's ranking can change.

## The prediction

1. **Query `5809eb10` is UNCHANGED.** Its answer is nowhere near the truncated tail. If this one
   moves, the mean-pooling reasoning behind choosing 1024 is wrong and the choice should be
   revisited, not explained away.

2. **The overwhelming majority of top-1 picks are byte-identical.** 99.82% of turns produce an
   identical vector, so a query whose slate contains no long distractor cannot move at all.

3. **Net movement is within noise, and I am NOT predicting exactly zero.** 452 distractors change,
   and a distractor that sits near a decision boundary can cross it in either direction. A net of
   0 ± 2 queries would not surprise me. **A net loss of more than ~3, or any systematic direction,
   would be a real signal** and would mean truncation is removing discriminative tail content from
   distractors in a way that helps or hurts non-randomly.

4. **McNemar is expected to be non-significant.** With so few discordant pairs the test has almost
   no power, which is itself the point: this change is not supposed to be a quality intervention.

## What would falsify the whole approach

Any of: `5809eb10` moving; a net change beyond ±3; or a one-sided pattern in which queries move.
None of those is explainable by "0.18% of turns lost their tail", and each would mean the mechanism
is not what this session claims it is.

## What this comparison is and is not

It is **session-level top-1** computed from the fit dump, not the published turn-level R@1. The
published 0.7555 was measured on a different day, through `summary.json`, under a different
configuration. Comparing against it would be the carried-measurement error this project logs; the
comparison that means something is baseline-vs-treatment **on this machine, minutes apart, through
the same code path** — which is what `fit-8192-BASELINE/` exists for.

It is also **not a held-out read**. None is spent here, deliberately: the capability question is
answered exhaustively by the gold-length enumeration, and a held-out read is a scarce, pre-registered
resource that should not be spent on a change whose blast radius is already known by construction.
