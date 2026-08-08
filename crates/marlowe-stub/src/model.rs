//! The daemon-side view models the surface renders.
//!
//! **None of these are pinned in `CONTRACTS.md`, and that is deliberate.** §13 pins `TurnEvent` —
//! the loop → surface *turn stream* — and nothing else about a surface. The status band, the
//! control strip and the inspector are views the daemon publishes, and no contract describes them
//! yet because no daemon exists yet.
//!
//! **M2 must pin them.** Inventing contract types this milestone would pin a shape to whatever a
//! stub found convenient, which is the same mistake as letting the interface be shaped by whatever
//! memory happens to do today. They live here, in the stub, until there is a daemon whose shape
//! they describe.
//!
//! What holds the boundary in the meantime: `marlowe-surface` **does not depend on anything that
//! can produce these values**. It renders what it is handed. A surface that cannot fabricate state
//! is a surface that provably holds no state the daemon lacks (ARCHITECTURE.md §2.14).

/// §B5's seven states. One region, always visible, outside every scroll area.
///
/// > **Motion means Marlowe is working. Stillness means the ball is in the user's court.**
///
/// That rule is carried by [`StatusState::samples_amplitude`], not by a colour. `Waiting` stops
/// sampling, so the indicator freezes structurally — see ADR-021. Nothing branches on "is this the
/// waiting state" inside the widget.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StatusState {
    Listening,
    Thinking,
    Speaking,
    Writing,
    Running,
    Waiting,
    Idle,
}

/// Which of the three state colours (or none) a thing carries. §B2: **state colours encode state
/// only, never category.**
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tone {
    /// Healthy, live, running normally.
    Green,
    /// Needs attention, approaching a limit, degraded.
    Amber,
    /// Conflict, failure, irreversible.
    Red,
    /// Focus, labels, hotkeys, structure.
    Accent,
    /// Body text.
    Normal,
    /// Inactive, and **load-bearing**: §B2 — an event needing nothing from the user is dimmed to
    /// near-invisible so the eye goes to the ones that do.
    Dim,
}

impl StatusState {
    pub fn name(self) -> &'static str {
        match self {
            StatusState::Listening => "listening",
            StatusState::Thinking => "thinking",
            StatusState::Speaking => "speaking",
            StatusState::Writing => "writing",
            StatusState::Running => "running",
            StatusState::Waiting => "waiting",
            StatusState::Idle => "idle",
        }
    }

    /// §B5's colour column.
    pub fn tone(self) -> Tone {
        match self {
            StatusState::Listening | StatusState::Speaking => Tone::Green,
            StatusState::Thinking | StatusState::Writing => Tone::Accent,
            StatusState::Running | StatusState::Waiting => Tone::Amber,
            StatusState::Idle => Tone::Dim,
        }
    }

    /// **Whether a sample source is attached at all.**
    ///
    /// `Waiting` returns false and that is the whole of §B5's freeze rule. The meter draws what its
    /// source last reported and holds the last frame when the source stops (ADR-021), so "the
    /// indicator freezes when nothing will happen until the user acts" needs no special case.
    ///
    /// `Idle` still samples — it reports a flat zero baseline, which is a reading, not an absence.
    /// A still-but-live indicator and a frozen one are different claims and the user can tell.
    pub fn samples_amplitude(self) -> bool {
        !matches!(self, StatusState::Waiting)
    }

    /// The message field's placeholder tracks the band (§B8). This is how barge-in is made visible
    /// without a second indicator.
    pub fn placeholder(self) -> &'static str {
        match self {
            StatusState::Listening => "listening — type to take over",
            StatusState::Thinking => "thinking — esc to interrupt",
            StatusState::Speaking => "speaking — type to take over",
            StatusState::Writing => "writing — esc to stop",
            StatusState::Running => "running a tool — esc cancels",
            StatusState::Waiting => "waiting on you",
            StatusState::Idle => "ask me something",
        }
    }
}

/// What the status band shows for the current state. §B5: *"the numbers that matter **for that
/// state**"* — a band that always shows the same four numbers is a status bar, not a status band.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StatusBand {
    pub state: StatusState,
    /// What it is doing, in specifics. `reading 34 sources · 12 pending`, never `working`.
    pub detail: String,
    /// The numbers for this state, right-aligned, at most two lines.
    pub figures: Vec<String>,
    /// Set when invariant 4 has fired. Renders amber, over the state's own detail.
    pub degraded: Option<crate::turn::DegradedPath>,
}

/// §B4's five control-strip regions, in order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ControlStrip {
    pub model: Picker,
    pub profile: Picker,
    pub session: Picker,
    pub workspace: Picker,
    /// **The one that matters.** It is the single control changing what Marlowe may do without
    /// asking, it carries state colour, and it is **never a value the agent can change**
    /// (Addendum A §A8: self-granted promotion is structurally impossible).
    pub autonomy: Picker,
}

/// A control-strip value with its in-place selection list. Drawn by Marlowe, never an OS widget.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Picker {
    pub options: Vec<String>,
    pub selected: usize,
    /// True while the dropdown is open. Open state is the *surface's* business, but it lives with
    /// the value so a redraw cannot lose it.
    pub open: bool,
}

impl Picker {
    pub fn new(options: &[&str], selected: usize) -> Self {
        assert!(
            selected < options.len(),
            "Picker::new selected index {selected} is out of range for {} options; a picker with \
             no valid selection would render an empty region with a border and a hotkey, which is \
             a region that lies about being interactive",
            options.len()
        );
        Self {
            options: options.iter().map(|s| (*s).to_string()).collect(),
            selected,
            open: false,
        }
    }

    pub fn value(&self) -> &str {
        &self.options[self.selected]
    }

    /// Autonomy is amber at `confirm` and above (§B4). Every other picker is toneless — a control
    /// strip where four of five fields carry colour is a control strip where colour means nothing.
    pub fn autonomy_tone(&self) -> Tone {
        match self.value() {
            "confirm" | "act" => Tone::Amber,
            _ => Tone::Normal,
        }
    }
}

/// One line in the transcript.
#[derive(Debug, Clone, PartialEq)]
pub enum Entry {
    User(String),
    /// Marlowe's prose. Carries the persona (Addendum C) — **including here, in a stub**.
    Said(String),
    /// A group of consecutive tool calls. §B6's same-verb collapse operates within a group.
    Tools(Vec<ToolCall>),
    /// `─ compacted · 47 turns → summary ─`. Announces itself inline and does not interrupt.
    Compacted { turns: u32 },
}

/// One rendered tool call. §B6: **one line**, expandable, failures auto-expanded.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolCall {
    pub id: u64,
    pub verb: &'static str,
    pub target: String,
    pub state: crate::turn::ToolLineState,
    /// Set when consecutive same-verb calls collapsed into this one: six reads become
    /// `⋯ read  6 files`. The collapsed targets are kept so expanding shows what they were.
    pub collapsed: Vec<String>,
    /// User expanded it with Enter/Tab. Failures start expanded and this is why the field is not
    /// simply derived from the state — a user can also collapse a failure back down.
    pub expanded: bool,
}

impl ToolCall {
    pub fn ok(id: u64, verb: &'static str, target: &str, metrics: Vec<crate::turn::Metric>) -> Self {
        Self {
            id,
            verb,
            target: target.to_string(),
            state: crate::turn::ToolLineState::Ok(crate::turn::ResultSummary::new(metrics)),
            collapsed: Vec::new(),
            expanded: false,
        }
    }

    pub fn failed(
        id: u64,
        verb: &'static str,
        target: &str,
        metrics: Vec<crate::turn::Metric>,
        detail: &str,
    ) -> Self {
        Self {
            id,
            verb,
            target: target.to_string(),
            state: crate::turn::ToolLineState::Failed(crate::turn::ResultSummary::with_detail(
                metrics, detail,
            )),
            collapsed: Vec::new(),
            expanded: true, // §B6: failures auto-expand.
        }
    }

    pub fn running(id: u64, verb: &'static str, target: &str, elapsed_ms: u64) -> Self {
        Self {
            id,
            verb,
            target: target.to_string(),
            state: crate::turn::ToolLineState::Running { elapsed_ms },
            collapsed: Vec::new(),
            expanded: false,
        }
    }

    pub fn is_failure(&self) -> bool {
        matches!(self.state, crate::turn::ToolLineState::Failed(_))
    }
}

/// The pinned pager (§B6). Carries what no other region has, and it never scrolls.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Pager {
    pub turn: u32,
    pub compacted: u32,
    /// How many compaction generations this session goes back. What `^l` walks.
    pub lineage: u32,
}

/// The six inspector tabs (§B7). Tabs are pinned; content scrolls.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Runs,
    Schedule,
    Sessions,
    Skills,
    Trust,
    Status,
}

impl Tab {
    pub const ALL: [Tab; 6] = [
        Tab::Runs,
        Tab::Schedule,
        Tab::Sessions,
        Tab::Skills,
        Tab::Trust,
        Tab::Status,
    ];

    pub fn title(self) -> &'static str {
        match self {
            Tab::Runs => "Runs",
            Tab::Schedule => "Schedule",
            Tab::Sessions => "Sessions",
            Tab::Skills => "Skills",
            Tab::Trust => "Trust",
            Tab::Status => "Status",
        }
    }

    /// The digit that reaches this tab. `1`–`6`, per §B7.
    pub fn digit(self) -> char {
        match self {
            Tab::Runs => '1',
            Tab::Schedule => '2',
            Tab::Sessions => '3',
            Tab::Skills => '4',
            Tab::Trust => '5',
            Tab::Status => '6',
        }
    }

    /// Whether M1 renders this tab with data.
    ///
    /// **The four that are not live are still present and still reachable**, each rendering one
    /// bordered region that says what will live there and in which milestone. §B7's tab bar must
    /// not lie — a tab that silently shows nothing is worse than a tab that says it is not built,
    /// because the user cannot tell it apart from a bug.
    pub fn is_live_in_m1(self) -> bool {
        matches!(self, Tab::Runs | Tab::Schedule)
    }
}

/// An item inside an inspector pane.
///
/// §B7: *"Each item inside is itself a bordered region with a label and a key."* The mockup shows
/// several bordered items with no key; prose wins, and the surface's `Region` type makes a keyless
/// bordered region unrepresentable anyway.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Item {
    pub label: String,
    /// The key on this item's bottom border. Registered in the surface's key registry, which
    /// **errors at startup** on a collision rather than silently letting one key shadow another.
    pub key: char,
    /// Lines inside the region, each with its tone. Dimming is how a dense screen tells the eye
    /// where to look, so this is data, not styling.
    pub lines: Vec<(String, Tone)>,
    /// The border tone. `Dim` for an item needing nothing from the user.
    pub tone: Tone,
    /// A text field the user types into — the Steer field is the only one in M1 (§B7, v1.0 §10.1:
    /// *inject guidance into a running child without restarting it*).
    pub editable: bool,
}

impl Item {
    pub fn new(label: &str, key: char, tone: Tone, lines: &[(&str, Tone)]) -> Self {
        Self {
            label: label.to_string(),
            key,
            lines: lines.iter().map(|(s, t)| ((*s).to_string(), *t)).collect(),
            tone,
            editable: false,
        }
    }

    pub fn editable(label: &str, key: char, placeholder: &str) -> Self {
        Self {
            label: label.to_string(),
            key,
            lines: vec![(placeholder.to_string(), Tone::Dim)],
            tone: Tone::Normal,
            editable: true,
        }
    }
}

/// §B9's approval overlay content.
///
/// **States blast radius, not the command.** Not `Run: rm -rf ./build?` but `Delete 1,204 files in
/// ./build · not recoverable`. The type has no field for the command string, which is the point:
/// a surface cannot show what it was never given.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BlastRadius {
    /// What will happen, in the user's terms.
    pub headline: String,
    /// The consequence. Renders in the risk tier's colour.
    pub consequence: String,
    /// Novelty gating explained in one line: `unusual · first send to this recipient`. Ceilings
    /// stated: `this class sits at its ceiling and cannot be promoted`.
    pub why: String,
    pub tier: RiskTier,
    /// The keys, including **the delegation escape hatch** — sending *as Marlowe* is the path that
    /// avoids impersonation entirely (Addendum A §A3).
    pub options: Vec<(char, &'static str)>,
}

/// §B9 is risk-tiered per v1.0 §8.2. The tier picks the doubled border's colour.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RiskTier {
    /// Routine writes, batched.
    Routine,
    /// Irreversible. Blocking.
    Irreversible,
}

impl RiskTier {
    pub fn tone(self) -> Tone {
        match self {
            RiskTier::Routine => Tone::Amber,
            RiskTier::Irreversible => Tone::Red,
        }
    }
}

/// The ambient numbers on the message field's right (§B8).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Ambient {
    pub fill_pct: u8,
    pub spend_cents: u32,
    pub elapsed_min: u32,
}

impl Ambient {
    /// **Context pressure is a colour, not a bar** (§B8): dim until 60%, amber at 60%, accent at
    /// the 70% compaction trigger (v1.0 §6).
    pub fn context_tone(&self) -> Tone {
        match self.fill_pct {
            0..=59 => Tone::Dim,
            60..=69 => Tone::Amber,
            _ => Tone::Accent,
        }
    }
}
