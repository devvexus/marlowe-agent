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
    /// `None` when the parent has no depth left — the caller turns that into a refusal the
    /// model can read, rather than a child that runs with `depth: 0` and spawns anyway.
    /// Anthropic's documented deep-research failures were excessive spawning and endless loops;
    /// this is the structural bound against reproducing them.
    pub fn slice_for(&self, spent: &Budget, share: BudgetShare) -> Option<Budget> {
        if self.depth == 0 {
            return None;
        }
        let left = self.remaining(spent);
        Some(Budget {
            tokens: share.apply_u64(left.tokens),
            wall_ms: share.apply_u64(left.wall_ms),
            tool_calls: share.apply_u32(left.tool_calls),
            // A child may not spawn more children than its parent had left, and it starts one
            // short because it is itself one of them.
            subagents: left.subagents.saturating_sub(1),
            depth: self.depth - 1,
            micros_usd: share.apply_u64(left.micros_usd),
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

/// How much of what is left a child gets. §10.2's effort scaling, expressed as a declared
/// fraction rather than a heuristic the orchestrator applies invisibly.
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
            BudgetShare::Standard => 2,
            BudgetShare::Large => 4,
        }
    }

    fn apply_u64(self, v: u64) -> u64 {
        v.saturating_mul(self.numerator()) / 8
    }

    fn apply_u32(self, v: u32) -> u32 {
        ((v as u64).saturating_mul(self.numerator()) / 8) as u32
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
        let child = root.slice_for(&Budget::default(), BudgetShare::Standard).unwrap();
        assert_eq!(child.depth, 1);
        let grandchild = child.slice_for(&Budget::default(), BudgetShare::Standard).unwrap();
        assert_eq!(grandchild.depth, 0);
        assert_eq!(
            grandchild.slice_for(&Budget::default(), BudgetShare::Standard),
            None,
            "the tree stops; a great-grandchild is refused rather than run at depth 0"
        );
    }

    #[test]
    fn a_child_never_receives_the_whole_remaining_budget() {
        let b = Budget::interactive();
        for share in [BudgetShare::Small, BudgetShare::Standard, BudgetShare::Large] {
            let child = b.slice_for(&Budget::default(), share).unwrap();
            assert!(
                child.tokens < b.tokens,
                "a parent that hands over everything cannot synthesise the answer it asked for"
            );
            assert!(child.subagents < b.subagents);
        }
    }

    #[test]
    fn there_is_a_floor_below_which_a_call_is_not_worth_issuing() {
        let b = Budget { tokens: 1_000, ..Budget::interactive() };
        assert!(b.has_room_for_a_call(&spent(0)));
        assert!(!b.has_room_for_a_call(&spent(600)));
    }
}
