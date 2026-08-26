# ADR-056 · `Ctrl-V` belongs to paste, and the footer grows an `Alt` namespace to give it up

**Status:** accepted, 2026-08-26 (M3 F2)
**Amends:** §B8's footer, §B10's *"Ctrl-modified keys are the footer's"*

## The decision

`Ctrl-V` is **paste**. `^v Voice` — §B5's state-cycling demo affordance — moves to **`Alt-V`**, and
the footer gains a second modifier namespace to hold it.

## Why the chord could not stay where it was

`^v` had `Ctrl-V` because §B10 gave every footer key to `Ctrl`, and at the time nothing else wanted
it. Two things have changed.

**1. The terminal takes it first, so `^v` was already mostly unreachable.** Windows Terminal —
ADR-002's development platform — binds `Ctrl-V` to paste and delivers the text as a bracketed-paste
event. The application never sees the chord. So the footer has been advertising a key the primary
platform intercepts, and `b13_keyboard.rs` could not notice because it dispatches `Key::Ctrl('v')`
into `App` directly and never crosses a terminal. **A test on the dispatch table cannot see a
binding the terminal ate** — the same family as a pipe-tested hook, one layer up.

**2. The composer now has a clipboard story that needs the chord.** M3 F2 added `Ctrl-A`
(select-all) and `Ctrl-C` (copy). `Ctrl-V` is the third of that set, and a composer answering two
of three is worse than one answering none: the hand has been taught the pattern and the third
press does something unrelated. Before this ADR that "something unrelated" was cycling the status
band — the screen changes, nothing is pasted, and the change reads as though the paste worked.

## Why `Alt` and not another `Ctrl` letter

Every unclaimed `Ctrl` letter is unclaimed for a reason — `Ctrl-S`, `Ctrl-Z`, `Ctrl-Q` are taken by
terminals, shells or flow control, and the ones that are free are free because they are
unmemorable. Moving a demo affordance onto a worse `Ctrl` chord spends the scarce namespace on the
least important key in the footer.

`Alt` is unclaimed in this application, unclaimed by Windows Terminal's defaults, and is the
established second namespace in terminal applications (`Meta-` in readline, `M-` in emacs). It
costs a new `Key` variant and one arm in each driver's `translate`.

**The cost, named:** `Alt`-letter is less reliable than `Ctrl`-letter across emulators — some send
`ESC` + the letter rather than a modifier, and crossterm reports those differently. `^v` is a
demonstration affordance, so it is the right key to spend that risk on; **no capability depends on
it.** If `Alt` proves unreliable the answer is to drop the demo from the footer, not to take
`Ctrl-V` back.

## What is NOT decided here

**The footer's `Ctrl`-first rule survives.** This adds `Alt` as a place to put a key that had to
move; it does not open the footer to arbitrary modifiers. §B10's requirement — *every footer key
works from inside a text field* — is unchanged and still asserted, now on `Alt-V`.

**`Ctrl-C` is untouched by this ADR.** It copies or confirms-then-quits, decided separately in the
same session.

## The acceptance test moved, and that is recorded rather than quiet

`b13_keyboard.rs::ctrl_keys_work_even_from_inside_a_text_field` pressed `Ctrl('v')` and asserted all
seven §B5 states are reachable while typing. It now presses `Alt('v')`. **The property is
unchanged** — a footer key must work inside a text field — and only the chord moved, because the
footer moved. An acceptance test is not edited to accommodate an implementation; it is edited when
the requirement it encodes changes, and this ADR is that change.

## What a terminal that does not paste now gets

`Ctrl-V` reaching the application at all means the terminal did **not** handle it. There is no
portable way to read the system clipboard from a TUI — OSC 52 reads are refused by most emulators
for good reason — so the honest answer is a notice naming the fallback (`Shift-Insert`, or
right-click) rather than a silent no-op or an invented capability.
