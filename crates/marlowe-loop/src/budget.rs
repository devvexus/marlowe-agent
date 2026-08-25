//! CONTRACTS.md §5 — `Budget`, and brief §8.2's spend caps.
//!
//! > **Hitting a cap pauses and asks. It never fails silently and never spends past the line.**
//!
//! # "Never past the line" is a pre-call cap, not a post-call check
//!
//! The obvious implementation checks `spent` at the top of each iteration and pauses when it
//! exceeds the budget. That satisfies *"never fails silently"* and fails *"never spends past
//! the line"*: by the time the check fires, the tokens are bought. The overspend is reported
//! accurately, which is what makes it easy to miss — the number in the pause message is right.
//!
//! So there are two mechanisms and they answer different questions:
//!
//! | Mechanism | Question it answers |
//! |---|---|
//! | [`Budget::exhausted`] at the top of the loop | may another step begin at all? |
//! | [`Budget::call_limits`] on every model call | can this step *return* more than is left? |
//!
//! The second is the one that holds the line: the provider is handed a hard output cap derived
//! from what remains, so a call cannot come back over budget. The first alone would be a
//! measurement of the overspend rather than a prevention of it.
//!
//! A driver that ignores its limit is still caught — [`Budget::exhausted`] sees it on the next
//! iteration — but that is the backstop, not the mechanism.

use serde::{Deserialize, Serialize};

/// CONTRACTS.md §5. Six dimensions, all of them caps rather than targets.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Budget {
    pub tokens: u64,
    pub wall_ms: u64,
    pub tool_calls: u32,
    pub subagents: u16,
    pub depth: u8,
    pub micros_usd: u64,
}

/// Below this many tokens left, a model call cannot produce anything worth the round trip, and
/// issuing one spends the remainder on a truncated step. The loop pauses instead.
///
/// It is a constant rather than a fraction of the budget because the floor is a property of
/// what a useful step costs, not of how large the run's allowance happens to be.
pub const MIN_CALL_TOKENS: u64 = 512;

/// Which dimension ran out. `&'static str` so it can travel into a journal payload and a
/// `BlockReason` without allocating, and so the set of names is closed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct Dimension(pub &'static str);

/// What a model call is allowed to return.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CallLimits {
    /// Hard cap handed to the provider. Derived from what is left, never from a default.
    pub max_output_tokens: u64,
}

impl Budget {
    /// A budget generous enough for an interactive turn. Every field is a real number rather
    /// than `u64::MAX`: an unbounded dimension is a dimension whose cap never fires, and the
    /// point of the type is that all six fire.
    pub fn interactive() -> Self {
        Self {
            tokens: 200_000,
            wall_ms: 10 * 60 * 1_000,
            tool_calls: 200,
            subagents: 8,
            depth: 3,
            micros_usd: 2_000_000, // $2.00
        }
    }

    /// Which cap `spent` has reached, if any. Checked **before** any model spend.
    pub fn exhausted(&self, spent: &Budget) -> Option<Dimension> {
        if spent.tokens >= self.tokens {
            return Some(Dimension("tokens"));
        }
        if spent.wall_ms >= self.wall_ms {
            return Some(Dimension("wall_ms"));
        }
        if spent.tool_calls >= self.tool_calls {
            return Some(Dimension("tool_calls"));
        }
        if spent.subagents >= self.subagents {
            return Some(Dimension("subagents"));
        }
        if spent.micros_usd >= self.micros_usd {
            return Some(Dimension("micros_usd"));
        }
        // `depth` is not compared against `spent`: it is a property of the run's position in
        // the tree, checked at spawn (`slice_for`), not something a run accumulates.
        None
    }

    pub fn remaining(&self, spent: &Budget) -> Budget {
        Budget {
            tokens: self.tokens.saturating_sub(spent.tokens),
            wall_ms: self.wall_ms.saturating_sub(spent.wall_ms),
            tool_calls: self.tool_calls.saturating_sub(spent.tool_calls),
            subagents: self.subagents.saturating_sub(spent.subagents),
            depth: self.depth,
            micros_usd: self.micros_usd.saturating_sub(spent.micros_usd),
        }
    }

    /// The cap handed to the provider for the next call. **This is the line.**
    pub fn call_limits(&self, spent: &Budget) -> CallLimits {
        CallLimits { max_output_tokens: self.remaining(spent).tokens }
    }

    /// Whether enough remains for a call to be worth issuing.
    pub fn has_room_for_a_call(&self, spent: &Budget) -> bool {
        self.remaining(spent).tokens >= MIN_CALL_TOKENS
    }

    /// The child's budget. §10.1: declared at spawn, never inferred.
    ///
    /// # GRANTED, NEVER SLICED — M3 Session A, and this replaces `slice_for`
    ///
    /// `slice_for` took its fraction of what **remained**, which for repeated spawning decays
    /// geometrically. `CLAUDE.md` records what that produced at depth one: the eighth quarantined
    /// reader held **~0.3%** of the budget, and nothing reported it — the reader simply returned a
    /// worse summary of an attacker-controlled page, which is the output nobody can audit.
    /// `slice_for_quarantined_read` was written to escape exactly that, for one caller.
    ///
    /// M3's tree is depth four before tool-spawned agents, so the decay compounds three more
    /// times and it starves the leaves, which is where all the work happens. So the general case
    /// now does what the quarantine case already did: **the share is of `self` — the run's
    /// ORIGINAL budget — and is then clamped by what actually remains.** Every sibling is offered
    /// the same allocation until the run is genuinely out of budget, at which point this refuses
    /// with the numbers rather than handing out a slice too small to use.
    ///
    /// `explicit` is the *"a master with 200k spends it or hands it down"* half: a parent that
    /// knows the job may name the amount, and it is refused by name if it exceeds what is left.
    /// `None` means *"decide for me"*, and takes `share` of the original.
    ///
    /// **Depth is still structural.** `Err(GrantRefused::NoDepth)` at `depth == 0`: a master
    /// cannot conjure depth, and the caller turns the refusal into something the model can read
    /// rather than running a child at `depth: 0` that spawns anyway.
    pub fn grant(
        &self,
        spent: &Budget,
        share: BudgetShare,
        explicit: Option<u64>,
    ) -> Result<Budget, GrantRefused> {
        if self.depth == 0 {
            return Err(GrantRefused::NoDepth);
        }
        let left = self.remaining(spent);
        if left.tokens == 0 {
            return Err(GrantRefused::PoolEmpty { dimension: "tokens" });
        }
        if let Some(want) = explicit {
            if want > left.tokens {
                return Err(GrantRefused::MoreThanRemains { want, left: left.tokens });
            }
        }
        let of_original = |original: u64| share.apply_u64(original);
        let tokens = explicit.unwrap_or_else(|| of_original(self.tokens)).min(left.tokens);
        Ok(Budget {
            // **Every dimension floors at 1 while the parent still has any.** Audit findings C4
            // and C5 — the seventeenth instance, twice, in the function that hands budgets out.
            //
            // `Budget::exhausted` compares `spent >= budget`, so a granted dimension that rounds
            // to **zero means ALREADY EXHAUSTED, not "may not use"**: the child pauses before its
            // first model call and returns nothing, and the caller reports a refusal whose stated
            // reason is not the real one.
            //
            // Withholding a capability is done structurally elsewhere — `ExposedSet::empty()`
            // means there is no tool to call, `depth: 0` means a spawn is refused. A counter set
            // to zero is not a prohibition, it is a spent budget.
            tokens: at_least_one_u64(tokens, left.tokens),
            wall_ms: at_least_one_u64(of_original(self.wall_ms).min(left.wall_ms), left.wall_ms),
            tool_calls: at_least_one_u32(
                share.apply_u32(self.tool_calls).min(left.tool_calls),
                left.tool_calls,
            ),
            // A child may not spawn more children than its parent had left, and it starts one
            // short because it is itself one of them.
            subagents: at_least_one_u16(left.subagents.saturating_sub(1), left.subagents),
            depth: self.depth - 1,
            micros_usd: at_least_one_u64(
                of_original(self.micros_usd).min(left.micros_usd),
                left.micros_usd,
            ),
        })
    }

    /// What fraction of the **original** token budget one quarantined read may spend.
    ///
    /// A quarter. Generous on purpose: this reader is the only thing standing between a fetched
    /// page and the run, and a reader too poor to summarise does not fail — it returns something
    /// worse, which is indistinguishable from a page that had little to say.
    pub const QUARANTINED_READ_NUMERATOR: u64 = 2;
    pub const QUARANTINED_READ_DENOMINATOR: u64 = 8;

    /// The slice a **quarantined read** gets. Deliberately not [`slice_for`], and the two
    /// differences were each a bug in effect.
    ///
    /// # 1. A share of the ORIGINAL budget, not of what remains
    ///
    /// `slice_for` takes its fraction of `remaining`, which for a repeated operation decays
    /// geometrically: read 1 gets ⅛ of B, read 2 gets ⅛ of what is left, and **read 8's reader
    /// holds about 0.3% of the original budget.** Nothing reports that. The reader simply returns
    /// a worse summary, and a degraded summary of an attacker-controlled page is precisely the
    /// output nobody can audit.
    ///
    /// Here the share is taken from `self` — the original — and then clamped by what actually
    /// remains, so every read is offered the same allocation until the run is genuinely out of
    /// budget, at which point the caller fails closed with a message that says so.
    ///
    /// # 2. Depth is not consumed, because the reader cannot spawn
    ///
    /// `slice_for` refuses at `depth == 0`, which is correct for a subagent that might spawn its
    /// own. A quarantined reader holds `ExposedSet::empty()`, so it structurally **cannot** call
    /// `run` — it has no need of depth and returning `None` for it was a capability that
    /// disappeared with distance from the root. Live consequence: a run four levels deep could
    /// fetch a page and then never read it, receiving *"no budget remained to condense it"* while
    /// the real cause was depth. The child is given `depth: 0` and `subagents: 0`, which is what
    /// a run that cannot spawn actually needs.
    pub fn slice_for_quarantined_read(&self, spent: &Budget) -> Option<Budget> {
        let left = self.remaining(spent);
        if left.tokens == 0 || left.wall_ms == 0 {
            return None;
        }
        let share = |original: u64, remaining: u64| {
            original
                .saturating_mul(Self::QUARANTINED_READ_NUMERATOR)
                .checked_div(Self::QUARANTINED_READ_DENOMINATOR)
                .unwrap_or(0)
                .min(remaining)
        };
        Some(Budget {
            tokens: at_least_one_u64(share(self.tokens, left.tokens), left.tokens),
            wall_ms: at_least_one_u64(share(self.wall_ms, left.wall_ms), left.wall_ms),
            // **1, not 0, and the difference is not cosmetic.**
            //
            // [`Budget::exhausted`] compares `spent >= budget`, so a dimension set to zero reads
            // as *already exhausted* rather than *may not use*. A reader handed `tool_calls: 0`
            // paused before its first model call, returned nothing, and the parent reported "the
            // content could not be condensed" — a quarantine that silently stopped reading
            // anything at all.
            //
            // The capability is withheld structurally instead, which is stronger than a counter:
            // the profile is `ExposedSet::empty()`, so there is no tool to call, and `depth: 0`
            // means `slice_for` refuses any spawn. These numbers exist only to keep the budget
            // check from firing on the first iteration.
            tool_calls: 1,
            subagents: 1,
            depth: 0,
            // C4: `micros_usd` is the dimension the first pass at instance 17 did not
            // enumerate, and it is the one whose failure mode is money.
            micros_usd: at_least_one_u64(share(self.micros_usd, left.micros_usd), left.micros_usd),
        })
    }

    /// Accumulate a step's cost.
    pub fn add(&mut self, other: &Budget) {
        self.tokens = self.tokens.saturating_add(other.tokens);
        self.wall_ms = self.wall_ms.saturating_add(other.wall_ms);
        self.tool_calls = self.tool_calls.saturating_add(other.tool_calls);
        self.subagents = self.subagents.saturating_add(other.subagents);
        self.micros_usd = self.micros_usd.saturating_add(other.micros_usd);
    }
}

/// Why a spawn was refused a budget. **Every variant carries the numbers**, because a refusal a
/// model cannot act on produces a retry loop rather than a smaller request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum GrantRefused {
    #[error(
        "this run is at the bottom of its declared depth and cannot spawn. A master allocates          depth it was given; it cannot conjure more"
    )]
    NoDepth,
    #[error("the {dimension} pool is empty; there is nothing left to grant")]
    PoolEmpty { dimension: &'static str },
    #[error(
        "a grant of {want} tokens was asked for and {left} remain. A grant is deducted from the          parent's pool, so it cannot exceed it"
    )]
    MoreThanRemains { want: u64, left: u64 },
}

/// How much of the run's **original** budget a child is granted. §10.2's effort scaling,
/// expressed as a declared fraction rather than a heuristic the orchestrator applies invisibly.
///
/// # The numerators moved in M3 Session A, and the reason is the acceptance row
///
/// They were 1/8, 2/8, 4/8 **of what remained**. M3's acceptance requires the leaf share at
/// **depth 4** to sit inside a declared band and never fall below 1% of the root. A default of
/// 2/8 compounded four times is 0.39% — under the line before any sibling decay is counted at
/// all. `Standard` is now **3/8**, which measures **1.98%** at depth 4 from a 200k root:
/// `a_leaf_at_depth_four_is_inside_the_declared_band` is the command that prints it.
///
/// `Large` is 5/8 rather than 4/8 for the reason the old comment gave and could not enforce:
/// *never all of it* — a parent that hands over everything cannot synthesise the result it asked
/// for. 5/8 leaves 3/8.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BudgetShare {
    /// A quick lookup. One eighth.
    Small,
    /// The default for a worker. One quarter.
    Standard,
    /// A substantial investigation. One half. Never all of it — a parent that hands over
    /// everything cannot synthesise the result it asked for.
    Large,
}

impl BudgetShare {
    fn numerator(self) -> u64 {
        match self {
            BudgetShare::Small => 1,
            BudgetShare::Standard => 3,
            BudgetShare::Large => 5,
        }
    }

    fn apply_u64(self, v: u64) -> u64 {
        v.saturating_mul(self.numerator()) / 8
    }

    fn apply_u32(self, v: u32) -> u32 {
        ((v as u64).saturating_mul(self.numerator()) / 8) as u32
    }
}


/// A granted dimension is never zero while the parent still has some of it.
///
/// See [`Budget::grant`] for why: `exhausted` compares `spent >= budget`, so zero reads as
/// *already spent*, and a child handed a zero pauses before its first call. `remaining == 0` is the
/// one case where zero is the truth, and it is passed through so the caller's own guard can see it.
fn at_least_one_u64(sliced: u64, remaining: u64) -> u64 {
    if remaining == 0 {
        0
    } else {
        sliced.max(1)
    }
}

fn at_least_one_u32(sliced: u32, remaining: u32) -> u32 {
    if remaining == 0 {
        0
    } else {
        sliced.max(1)
    }
}

fn at_least_one_u16(sliced: u16, remaining: u16) -> u16 {
    if remaining == 0 {
        0
    } else {
        sliced.max(1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spent(tokens: u64) -> Budget {
        Budget { tokens, ..Budget::default() }
    }

    #[test]
    fn the_call_cap_is_what_is_left_not_a_default() {
        let b = Budget { tokens: 10_000, ..Budget::interactive() };
        assert_eq!(b.call_limits(&spent(0)).max_output_tokens, 10_000);
        assert_eq!(b.call_limits(&spent(9_000)).max_output_tokens, 1_000);
        // The property the report item names: a call issued at this point cannot come back
        // over the line, because the provider was told the line.
        assert_eq!(b.call_limits(&spent(10_000)).max_output_tokens, 0);
    }

    #[test]
    fn every_dimension_can_be_the_one_that_fires() {
        // A budget test that only ever exercises tokens is a budget test for one dimension.
        let b = Budget {
            tokens: 10,
            wall_ms: 10,
            tool_calls: 10,
            subagents: 10,
            depth: 2,
            micros_usd: 10,
        };
        let cases: [(Budget, &str); 5] = [
            (Budget { tokens: 10, ..Default::default() }, "tokens"),
            (Budget { wall_ms: 10, ..Default::default() }, "wall_ms"),
            (Budget { tool_calls: 10, ..Default::default() }, "tool_calls"),
            (Budget { subagents: 10, ..Default::default() }, "subagents"),
            (Budget { micros_usd: 10, ..Default::default() }, "micros_usd"),
        ];
        for (spent, dimension) in cases {
            assert_eq!(
                b.exhausted(&spent),
                Some(Dimension(dimension)),
                "spending {spent:?} should exhaust {dimension}"
            );
        }
        assert_eq!(b.exhausted(&Budget::default()), None);
    }

    #[test]
    fn depth_bounds_the_tree_rather_than_accumulating() {
        let root = Budget { depth: 2, ..Budget::interactive() };
        let child = root.grant(&Budget::default(), BudgetShare::Standard, None).unwrap();
        assert_eq!(child.depth, 1);
        let grandchild = child.grant(&Budget::default(), BudgetShare::Standard, None).unwrap();
        assert_eq!(grandchild.depth, 0);
        assert_eq!(
            grandchild.grant(&Budget::default(), BudgetShare::Standard, None),
            Err(GrantRefused::NoDepth),
            "the tree stops; a great-grandchild is refused rather than run at depth 0"
        );
    }

    #[test]
    fn a_child_never_receives_the_whole_remaining_budget() {
        let b = Budget::interactive();
        for share in [BudgetShare::Small, BudgetShare::Standard, BudgetShare::Large] {
            let child = b.grant(&Budget::default(), share, None).unwrap();
            assert!(
                child.tokens < b.tokens,
                "a parent that hands over everything cannot synthesise the answer it asked for"
            );
            assert!(child.subagents < b.subagents);
        }
    }

    /// **The acceptance row, as a command that prints a number.** M3 §11: *"Leaf budget share at
    /// depth 4 — within a declared band of the grant; never `< 1%`."*
    ///
    /// The band is declared here, in the assertion, rather than in prose: **[1%, 5%] of the
    /// root**, at the default share, over four levels.
    #[test]
    fn a_leaf_at_depth_four_is_inside_the_declared_band() {
        let root = Budget { depth: 4, ..Budget::interactive() };
        let mut b = root;
        for level in 1..=4 {
            b = b
                .grant(&Budget::default(), BudgetShare::Standard, None)
                .unwrap_or_else(|e| panic!("level {level} refused: {e}"));
        }
        let share = b.tokens as f64 / root.tokens as f64;
        println!("leaf at depth 4: {} of {} tokens = {:.2}%", b.tokens, root.tokens, share * 100.0);
        assert!(share >= 0.01, "leaf starved at {:.3}% -- the band's floor is 1%", share * 100.0);
        assert!(share <= 0.05, "leaf over-granted at {:.3}%; the band's ceiling is 5%", share * 100.0);
    }

    /// **The control for the row above.** It fails if `grant` ever goes back to taking its share
    /// of the *remainder*, which is what starved the eighth reader to 0.3%.
    ///
    /// Two spawns from the same parent, with the first one's whole budget already spent: under
    /// slicing the second sibling gets a fraction of a depleted pool; under granting it is offered
    /// the same allocation until the pool is genuinely gone.
    #[test]
    fn a_second_sibling_is_offered_the_same_allocation_as_the_first() {
        let b = Budget { depth: 2, ..Budget::interactive() };
        let first = b.grant(&Budget::default(), BudgetShare::Standard, None).unwrap();
        let after_first = Budget { tokens: first.tokens, ..Budget::default() };
        let second = b.grant(&after_first, BudgetShare::Standard, None).unwrap();
        assert_eq!(
            first.tokens, second.tokens,
            "a grant is a share of the ORIGINAL; the second sibling must not be paid out of the              first one's leftovers"
        );
    }

    #[test]
    fn an_explicit_grant_larger_than_the_pool_is_refused_with_both_numbers() {
        let b = Budget { tokens: 1_000, depth: 2, ..Budget::interactive() };
        let e = b.grant(&Budget::default(), BudgetShare::Standard, Some(5_000)).unwrap_err();
        assert_eq!(e, GrantRefused::MoreThanRemains { want: 5_000, left: 1_000 });
        // A model that is told only "refused" retries the same request. One told the numbers
        // can ask for less.
        assert!(e.to_string().contains("5000") && e.to_string().contains("1000"), "{e}");
    }

    #[test]
    fn an_explicit_grant_inside_the_pool_is_honoured_exactly() {
        // "A master with 200k spends it or hands it down." A named amount is not re-derived.
        let b = Budget { tokens: 200_000, depth: 2, ..Budget::interactive() };
        let child = b.grant(&Budget::default(), BudgetShare::Small, Some(150_000)).unwrap();
        assert_eq!(child.tokens, 150_000, "an explicit grant overrides the share, in both directions");
    }

    #[test]
    fn there_is_a_floor_below_which_a_call_is_not_worth_issuing() {
        let b = Budget { tokens: 1_000, ..Budget::interactive() };
        assert!(b.has_room_for_a_call(&spent(0)));
        assert!(!b.has_room_for_a_call(&spent(600)));
    }
}
