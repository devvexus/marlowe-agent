"""Session J — addendum registration for a POST-HOC length-normalization form.

**This does not make a post-hoc finding pre-registered, and nothing here should be read as though
it did.** What it does is pin the held-out prediction *before* the held-out read, so the one honest
test the form can still get is not adjusted after the fact.

## What the registered arms did

`runs/session-j/PREREGISTRATION.json` registered `f_hat` as **the conditional mean of the rerank
logit on log word pieces, estimated without reference to R@1**, and swept only its strength. On
L-2 f32 at seq 256, fit split:

| arm | best on the grid | delta R@1 |
|---|---|---|
| 7b subtractive | lambda 0.25 | **-0.0262** |
| 7d role only | lambda 0.25 | **-0.0088** |
| 7e both | lambda 0.25 | **-0.0350** |
| 7c divisive | alpha 0.5 | **+0.0349** |

**7b, 7d and 7e are monotonically WORSE at every strength, and the reason is that the fitted
correction has the wrong sign.** The OLS slope of the logit on log word pieces is **-0.5091** and
the role coefficient is **-0.9352**: on the slate, the model already scores longer and
assistant-authored candidates *lower* on average. Subtracting that fitted mean therefore **adds**
score to exactly the candidates that were supposed to be penalized, and the measured failure
profile confirms it — the rank-1 distractor on failures goes from 50.0% assistant-authored at 157
median word pieces to 71.4% at 430.

## Why the registered estimator could not have worked

**It measured the model's length response, when the quantity needing correction was the model's
length response RELATIVE TO relevance's.** Both are measurable and they disagree in magnitude by an
order of magnitude:

| length bin (median wp) | 32 | 51 | 68 | 88 | 186 | 368 | 530 | 656 |
|---|---|---|---|---|---|---|---|---|
| mean logit | -6.94 | -6.90 | -6.02 | -5.87 | -6.73 | -7.07 | -8.03 | -8.62 |
| **gold rate** | 0.115 | 0.248 | **0.353** | 0.329 | 0.063 | 0.039 | **0.007** | **0.007** |

Across the range the mean logit moves about 2.6 logits and is not even monotone, while the gold
rate falls **50-fold**. The model is *under*-penalizing length by a wide margin, and an estimator
built from `E[s | len]` cannot see that, because relevance never enters it. **Ninth instance of the
family that ADR-011, ADR-013 and ADR-014 each named one level deeper: the instrument could not have
measured the thing it was registered to measure.**

## The form this addendum pins

    s - c * log(wordpieces)

which is **7b's functional form with a positive constant slope in place of the fitted negative
one**. It is not a new mechanism; it is the registered mechanism with the coefficient's *source*
changed, and that change is post-hoc.

It is also **not** the same transform as 7c, and the difference is measured rather than assumed:
`sigmoid(s) / len^a` equals `s - a*log(len)` only where `log sigmoid(s) ~ s`, which holds for the
81.8% of slate logits below -2 and fails at the head, where the decision is made. At a = 2.0 the
two forms differ by 0.0480 R@1. 7c's registered grid also **contained its own maximum** — extending
it to a = 1.5, 2, 3, 4, 6 gives 0.6288, 0.6288, 0.5983, 0.5808, 0.5633, all at or below the
in-grid peak — so no grid extension is claimed for 7c.

## What is fixed here, and what it costs

`c = 2.0`, **selected on the fit split over an 11-point sweep** — 0.0, 0.5, 1.0, 1.5, 2.0, 2.5,
3.0, 4.0, 5.0, 7.0, 10.0, giving 0.5983, 0.6288, 0.6550, 0.6594, **0.6769**, 0.6769, 0.6725,
0.6376, 0.6070, 0.5721, 0.5109. The peak is broad — every c in [1.5, 3.0] clears +0.06 — which is
why a single constant is defensible at all, and the whole curve is recorded so the selection is
visible rather than absorbed into one number.

**The cost is stated plainly: the fit delta of +0.0786 is optimistically biased and must not be
quoted as the result.** The held-out read is the result.

    python tools/preregister_session_j_addendum.py
"""

from __future__ import annotations

import io
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "runs" / "session-j" / "ADDENDUM-post-hoc-length-form.json"
BASE_PREREG = REPO / "runs" / "session-j" / "PREREGISTRATION.json"


def main() -> int:
    if OUT_PATH.exists():
        raise SystemExit(f"{OUT_PATH.relative_to(REPO)} already exists; written once, never rewritten.")
    if not BASE_PREREG.exists():
        raise SystemExit("the base pre-registration is missing; this addendum amends it and cannot stand alone.")

    addendum = {
        "_what": "Session J addendum. A POST-HOC length-normalization form, with its held-out "
                 "prediction pinned BEFORE the held-out read.",
        "_this_is_not": (
            "a pre-registration of the form. The form was found by looking at fit-split numbers. "
            "This file cannot and does not undo that. It pins the prediction so the one honest "
            "test the form can still get is not adjusted afterwards."
        ),
        "amends": "runs/session-j/PREREGISTRATION.json",
        "written_before": "any held-out number for any arm 7 variant",

        "what_the_registered_arms_did": {
            "population": "L-2 f32, seq 256, fit split, 229 cases",
            "control_r_at_1": 0.5983,
            "best_per_arm": {
                "7b_subtractive": {"strength": 0.25, "delta_r_at_1": -0.0262},
                "7c_divisive": {"strength": 0.5, "delta_r_at_1": 0.0349},
                "7d_role_only": {"strength": 0.25, "delta_r_at_1": -0.0088},
                "7e_both": {"strength": 0.25, "delta_r_at_1": -0.0350},
            },
            "verdict": (
                "7c PASSES its registered floor and lands inside the registered band. 7b, 7d and "
                "7e FAIL at every strength, and the failure is a sign error in the registered "
                "estimator rather than noise."
            ),
        },

        "why_the_registered_estimator_has_the_wrong_sign": {
            "fitted_ols_slope_logits_per_log_wordpiece": -0.5091,
            "fitted_role_beta_logits": -0.9352,
            "mechanism": (
                "on the slate the model ALREADY scores longer and assistant-authored candidates "
                "lower on average, so subtracting the fitted conditional mean ADDS score to the "
                "candidates that needed penalizing"
            ),
            "confirmed_by": (
                "the failure profile moves the wrong way — rank-1 on failures goes from 50.0% "
                "assistant at 157 median word pieces to 71.4% at 430 as lambda rises"
            ),
            "the_deeper_error": (
                "E[s | len] measures the MODEL's length response. What needed correcting is the "
                "model's length response RELATIVE TO RELEVANCE's. Across length bins the mean "
                "logit moves ~2.6 logits and is not monotone, while the gold rate falls 50-fold "
                "(0.353 at 68 word pieces to 0.007 at 530). Relevance never enters the registered "
                "estimator, so it could not have seen that gap."
            ),
            "family": (
                "ninth instance. ADR-011: the mechanism could not move the metric. ADR-013: the "
                "read could not vary. ADR-014: the contrast could not reach significance. Here: "
                "the estimator could not have measured the quantity it was registered to correct."
            ),
        },

        "the_form": {
            "expression": "s - c * log(wordpieces)",
            "relation_to_registered_arms": (
                "7b's functional form with a positive CONSTANT slope in place of the fitted "
                "negative one. Not a new mechanism — the registered mechanism with the "
                "coefficient's source changed, and that change is post-hoc."
            ),
            "not_the_same_as_7c": {
                "why": "sigmoid(s)/len^a equals s - a*log(len) only where log sigmoid(s) ~ s",
                "share_of_slate_logits_below_-2": 0.818,
                "measured_difference_at_a_2_0": 0.0480,
                "_so": "they diverge exactly at the head of the ranking, where top-1 is decided",
            },
            "7c_grid_contained_its_own_maximum": {
                "in_grid": {"0.25": 0.6245, "0.5": 0.6332, "0.75": 0.6245, "1.0": 0.6332},
                "beyond_grid": {"1.5": 0.6288, "2.0": 0.6288, "3.0": 0.5983,
                                "4.0": 0.5808, "6.0": 0.5633},
                "_so": "no grid extension is claimed for 7c; its registered sweep was adequate",
            },
        },

        "what_is_fixed_here": {
            "c": 2.0,
            "selected_on": "the fit split, over an 11-point sweep",
            "the_whole_sweep": {
                "0.0": 0.5983, "0.5": 0.6288, "1.0": 0.6550, "1.5": 0.6594, "2.0": 0.6769,
                "2.5": 0.6769, "3.0": 0.6725, "4.0": 0.6376, "5.0": 0.6070, "7.0": 0.5721,
                "10.0": 0.5109,
            },
            "why_a_single_constant_is_defensible": (
                "the peak is broad — every c in [1.5, 3.0] clears +0.06 over the control — so the "
                "choice is not a knife edge. It is still a fit-selected constant."
            ),
            "fit_delta_r_at_1": 0.0786,
            "_binding": (
                "the fit delta of +0.0786 is optimistically biased and MUST NOT be quoted as the "
                "result. The held-out read is the result."
            ),
        },

        "held_out_prediction_pinned_now": {
            "floor_for_the_form_to_be_considered_real": 0.02,
            "predicted_band": [0.03, 0.08],
            "reasoning": (
                "a post-hoc form selected on one split typically shrinks out of sample. The floor "
                "is set at the same 0.02 the base registration used for Part 2, and the band's "
                "lower edge sits well below the fit delta deliberately."
            ),
            "also_predicted": (
                "the rank-1 failure profile converges toward gold's on held-out as it did on fit: "
                "assistant share falls from ~50% toward ~15%, and median rank-1 word pieces on "
                "failures falls from ~157 toward gold's median of ~70. If R@1 rises WITHOUT that "
                "profile shift, the gain is not length normalization and the mechanism claim is "
                "wrong even if the number is right."
            ),
            "reads_allowed": 1,
            "_binding": (
                "ONE held-out read, taken together with the registered arms at the end of Part 2. "
                "c is not re-selected on held-out under any circumstance."
            ),
        },

        "shipping_note": (
            "this form needs only the candidate's word-piece count, which the shipped path already "
            "computes when it encodes the pair. Unlike the role arms it requires NO schema change "
            "and no DERIVATION_VERSION bump — the log-length term is arithmetic on a number "
            "rerank.rs already has in hand."
        ),
    }

    OUT_PATH.write_text(json.dumps(addendum, indent=2) + "\n", encoding="utf-8")
    print("Session J addendum written — a POST-HOC form, with its held-out prediction pinned.")
    print("  registered arms: 7c PASSES (+0.0349, in band); 7b / 7d / 7e FAIL on a sign error")
    print("  the estimator measured the model's length response, not its response RELATIVE to")
    print("  relevance's -- mean logit moves 2.6 across length bins, the gold rate falls 50-fold")
    print("  post-hoc form: s - 2.0*log(wordpieces), fit delta +0.0786, BIASED and not the result")
    print("  held-out: floor +0.02, band [+0.03, +0.08], ONE read, c never re-selected")
    print(f"\nWROTE {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
