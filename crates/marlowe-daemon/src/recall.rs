//! The `recall` tool — §5.5's explicit memory search. M2 Session D.
//!
//! # Why this is a wrapper rather than an arm in `marlowe-exec`
//!
//! `marlowe-exec` executes tools against the filesystem and the network. Teaching it about beliefs
//! would point the tool-executor crate at the memory crate for one arm, and every future tool
//! touching a subsystem would do the same until `marlowe-exec` depended on everything. So the
//! daemon — the composition root, which already owns both — wraps the filesystem host and answers
//! `recall` itself, delegating everything else unchanged.
//!
//! # Why `recall` is not gated by the declared operating point
//!
//! Auto-injection is content the model did **not** ask for, arriving in its context where it reads
//! as its own knowledge. K1 condition 3 governs that, at 10% coverage, because the cost of being
//! wrong is a confident false statement the user cannot trace.
//!
//! `recall` is the model deliberately searching, and evaluating what comes back. CONTRACTS §3.6
//! says it sees **tombstones and unmatured entries** — precisely the things auto-injection must
//! not. Applying the injection cut point here would make explicit search strictly worse than the
//! thing it exists to be better than, and brief §5.5 asks for the opposite: *"recall recovered by
//! making the agent's explicit memory search tool excellent."*
//!
//! **Security is unchanged by that choice.** Recalled text lands in the context view carrying its
//! own trust class, exactly as an injected memory does, and `ContextView::trust_floor` is `min`
//! over every block. Nothing is smuggled past a guard; a different question is being answered.

use std::sync::{Arc, Mutex};

use marlowe_contract::TrustClass;
use marlowe_loop::driver::{ToolBody, ToolHost, ToolOutcome};
use marlowe_tools::{Metric, ResultSummary};
use marlowe_memory::cue::lexical;
use marlowe_memory::BeliefStore;
use marlowe_permission::{Adjudication, Args};
use marlowe_tools::ToolId;

/// How many memories one `recall` returns.
///
/// Small on purpose. `recall` competes for the same context the conversation needs, and a search
/// that returns forty results has moved the retrieval problem into the model's attention rather
/// than solving it.
const RECALL_LIMIT: usize = 5;

/// The daemon's tool host: the filesystem tools, plus `recall` over the belief store.
pub struct RecallTools<H: ToolHost> {
    inner: H,
    beliefs: Arc<Mutex<BeliefStore>>,
}

impl<H: ToolHost> RecallTools<H> {
    pub fn new(inner: H, beliefs: Arc<Mutex<BeliefStore>>) -> Self {
        Self { inner, beliefs }
    }

    fn recall(&self, args: &Args) -> ToolOutcome {
        let Some(query) = args.get("query").and_then(|v| v.as_text()) else {
            return failed("`query` is required");
        };

        let beliefs = self.beliefs.lock().expect("the belief store lock was poisoned");
        // §4.3: hot ∪ cold. **Tombstones and unmatured entries included** — this is the "I used to
        // know" path, and excluding them would make explicit recall a slower copy of injection.
        let candidates = beliefs.recall_candidates();
        if candidates.is_empty() {
            return ToolOutcome {
                summary: ResultSummary::new(vec![Metric::Count { n: 0, unit: "memories" }]),
                body: ToolBody::Inline(
                    "no memories are stored yet. Nothing has been remembered in this profile."
                        .to_string(),
                ),
                // The HARNESS computed this: it enumerated the store and counted zero. No belief's
                // content is in the answer, so no belief's class is inherited.
                trust: TrustClass::AgentObserved,
                failed: false,
                wall_ms: 0,
                preview: None,
            };
        }

        let scores = lexical::score_all(&candidates, query);
        let mut ranked: Vec<usize> = (0..candidates.len()).collect();
        // Score descending, then id ascending. The id tiebreak is not decoration: two equal scores
        // ordered by whatever the collection did would make one run's recall differ from the next.
        ranked.sort_by(|a, b| {
            scores[*b]
                .total_cmp(&scores[*a])
                .then_with(|| candidates[*a].id.cmp(&candidates[*b].id))
        });
        // A zero lexical score means the query shares nothing with the memory. Returning those
        // would pad the answer with text the model then has to argue with.
        ranked.retain(|i| scores[*i] > 0.0);
        ranked.truncate(RECALL_LIMIT);

        if ranked.is_empty() {
            return ToolOutcome {
                summary: ResultSummary::new(vec![
                    Metric::Count { n: 0, unit: "memories" },
                    Metric::Count { n: candidates.len() as u64, unit: "searched" },
                ]),
                body: ToolBody::Inline(format!(
                    "nothing stored matches {query:?}. {} memories were searched.",
                    candidates.len()
                )),
                trust: TrustClass::AgentObserved,
                failed: false,
                wall_ms: 0,
                preview: None,
            };
        }

        // **`min` over what is actually returned — §3.3's worst case.** A `ToolOutcome` carries one
        // trust class, so a result mixing a user-asserted memory with a web-derived one must take
        // the lower. Taking the higher, or the first, would let one untrusted belief ride into the
        // context at another's authority: laundering through the search tool.
        let floor = ranked
            .iter()
            .map(|i| candidates[*i].effective_trust)
            .min()
            .unwrap_or(TrustClass::AgentObserved);

        let mut out = String::new();
        for i in &ranked {
            let e = candidates[*i];
            // The fidelity and the maturation state are stated, because a tombstone with empty text
            // is otherwise indistinguishable from a memory that says nothing, and an unmatured
            // belief is one the model should weigh differently from a settled one.
            out.push_str(&format!(
                "- [{}] {} ({:?}, {})\n",
                e.id,
                if e.text.is_empty() { "(forgotten — the record was tombstoned)" } else { &e.text },
                e.effective_trust,
                match e.silent_until {
                    Some(_) => "not yet matured",
                    None => "matured",
                }
            ));
        }

        ToolOutcome {
            summary: ResultSummary::new(vec![
                Metric::Count { n: ranked.len() as u64, unit: "memories" },
                Metric::Count { n: candidates.len() as u64, unit: "searched" },
            ]),
            body: ToolBody::Inline(out),
            trust: floor,
            failed: false,
            wall_ms: 0,
            preview: None,
        }
    }
}

fn failed(detail: &str) -> ToolOutcome {
    ToolOutcome {
        summary: ResultSummary::new(vec![Metric::Count { n: 0, unit: "memories" }]),
        body: ToolBody::Inline(detail.to_string()),
        trust: TrustClass::AgentObserved,
        failed: true,
        wall_ms: 0,
        preview: None,
    }
}

impl<H: ToolHost> ToolHost for RecallTools<H> {
    fn executes(&self) -> Vec<ToolId> {
        // **The inner host's set plus `recall`, never a hardcoded list.** A hardcoded one would
        // drift the moment `marlowe-exec` gained or lost an executor, and
        // `verify_every_exposed_tool_is_runnable` would then refuse at load with a name that had
        // nothing to do with the change.
        let mut tools = self.inner.executes();
        tools.push(ToolId::new("recall"));
        tools
    }

    fn execute(
        &mut self,
        tool: &ToolId,
        args: &Args,
        adjudication: &Adjudication,
    ) -> ToolOutcome {
        if tool.as_str() == "recall" {
            return self.recall(args);
        }
        self.inner.execute(tool, args, adjudication)
    }
}
