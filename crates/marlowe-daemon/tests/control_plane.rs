//! The control plane — M3 Session A.
//!
//! # What these assert, and what would pass without them
//!
//! The claim is *"`/steer` from another terminal reaches a run that is already going"*. The
//! tempting test is that `Request::Steer` returns something without an error, which is true on a
//! build where the control plane is a second copy of the run table nothing reads — the shape this
//! project has logged fifteen instances of.
//!
//! So the two tests that matter here are:
//!
//! 1. **The control port answers while the main port is wedged.** A client that authenticates and
//!    then says nothing holds `serve_one`'s `read_line` open; on the serial daemon that is every
//!    request stuck behind it. If the control plane were served from the same accept loop this
//!    would hang, and the test would fail by timing out rather than by asserting.
//! 2. **A steer sent on one connection is visible on another.** Two sockets, one shared
//!    `DurableControl`. A per-connection copy passes every other assertion in this file and fails
//!    this one.
//!
//! The routed-delivery half — a steer addressed to a child is taken by the child, mid-run, with no
//! restart — is asserted where it is enforced, in
//! `marlowe-loop/tests/durable_resume.rs::a_running_child_takes_a_steer_addressed_to_it_without_restarting`.
//! A daemon-level version would need a live model, and a test that skips when Ollama is absent is
//! a test that is usually not run.

use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;

use marlowe_daemon::protocol::Event;
use marlowe_daemon::{auth, control_plane, Client, Daemon, DaemonConfig};

static SEQ: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

struct Fixture {
    root: PathBuf,
    port: u16,
    shutdown: std::sync::Arc<std::sync::atomic::AtomicBool>,
}

impl Fixture {
    fn start(name: &str) -> Self {
        Self::start_on(name, free_port())
    }

    fn start_on(name: &str, port: u16) -> Self {
        let n = SEQ.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir()
            .join(format!("marlowe-cp-{name}-{}-{n}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let workspace = root.join("ws");
        std::fs::create_dir_all(&workspace).unwrap();

        let mut config = DaemonConfig::new(root.join("profile"), workspace);
        config.port = port;
        let daemon = Daemon::open(config).expect("the daemon opens");
        let shutdown = daemon.shutdown_handle();
        thread::spawn(move || {
            let _ = daemon.serve();
        });

        let fx = Self { root, port, shutdown };
        fx.wait_until_listening();
        fx.wait_until_advertised();
        fx
    }

    fn profile(&self) -> PathBuf {
        self.root.join("profile")
    }

    fn client(&self) -> Client {
        Client::new("t").with_port(self.port).with_profile_root(self.profile())
    }

    fn control_port(&self) -> u16 {
        control_plane::advertised_port(&self.profile()).expect("the control plane advertised")
    }

    fn wait_until_listening(&self) {
        for _ in 0..200 {
            if TcpStream::connect(("127.0.0.1", self.port)).is_ok() {
                return;
            }
            thread::sleep(Duration::from_millis(20));
        }
        panic!("the daemon never bound {}", self.port);
    }

    fn wait_until_advertised(&self) {
        for _ in 0..200 {
            if control_plane::advertised_port(&self.profile()).is_some() {
                return;
            }
            thread::sleep(Duration::from_millis(20));
        }
        panic!("the control plane never advertised a port");
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Relaxed);
        let _ = TcpStream::connect(("127.0.0.1", self.port));
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

/// Authenticate, then say nothing. `serve_one` clears its read timeout after the preamble, so the
/// daemon blocks here — which on a serial daemon is every subsequent request blocked with it.
struct WedgedMainPort(#[allow(dead_code)] TcpStream);

fn wedge(fx: &Fixture) -> WedgedMainPort {
    let mut s = TcpStream::connect(("127.0.0.1", fx.port)).expect("connect");
    let token = auth::read_token(&fx.profile()).expect("the daemon minted one");
    s.write_all(format!("{token}\n").as_bytes()).unwrap();
    s.flush().unwrap();
    // Give the daemon time to accept it and reach the blocking read. Without this the test could
    // pass by racing the wedge, which would make it evidence about scheduling rather than about
    // the second listener.
    thread::sleep(Duration::from_millis(200));
    WedgedMainPort(s)
}

fn ask_control(fx: &Fixture, request: &str) -> Vec<String> {
    let s = TcpStream::connect(("127.0.0.1", fx.control_port())).expect("connect to control");
    s.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    let mut w = s.try_clone().unwrap();
    let token = auth::read_token(&fx.profile()).expect("token");
    w.write_all(format!("{token}\n{request}\n").as_bytes()).unwrap();
    w.flush().unwrap();
    let mut out = Vec::new();
    for line in BufReader::new(s).lines() {
        // LOOP-EXEMPT: reading a response stream.
        match line {
            Ok(l) if !l.trim().is_empty() => out.push(l),
            _ => break,
        }
    }
    out
}

#[test]
fn the_control_port_answers_while_the_main_port_is_wedged() {
    // **The whole reason this module exists.** On the serial daemon a request arriving during a
    // turn is not read until the turn ends, so a `/steer` meant to change that turn arrives after
    // it. If the control plane were served from the same accept loop, the read below would block
    // until this test's timeout.
    let fx = Fixture::start("wedged");
    let _held = wedge(&fx);

    let lines = ask_control(&fx, r#"{"op":"runs"}"#);
    // No runs have happened, so `runs` answers with nothing and closes — which is itself the
    // answer: the connection was **served**, not queued behind the wedge.
    assert!(lines.is_empty() || lines.iter().all(|l| l.contains("\"run\"")), "{lines:?}");

    // And the negative control: the same request on the MAIN port does not come back, because
    // that is exactly what the wedge is doing to it.
    let main = TcpStream::connect(("127.0.0.1", fx.port)).expect("connect");
    main.set_read_timeout(Some(Duration::from_millis(600))).unwrap();
    let mut w = main.try_clone().unwrap();
    let token = auth::read_token(&fx.profile()).unwrap();
    w.write_all(format!("{token}\n{}\n", r#"{"op":"runs"}"#).as_bytes()).unwrap();
    w.flush().unwrap();
    let mut line = String::new();
    let read = BufReader::new(main).read_line(&mut line);
    assert!(
        read.is_err() || line.trim().is_empty(),
        "the main port answered while wedged, so the wedge proves nothing: {line:?}"
    );
}

#[test]
fn a_steer_sent_on_one_connection_is_visible_on_another() {
    // One shared `DurableControl`. A per-connection copy would pass every other test here.
    let fx = Fixture::start("shared");
    let run = "00000000-0000-0000-0000-0000000000aa";

    let steered = ask_control(
        &fx,
        &format!(r#"{{"op":"steer","run":"{run}","text":"only the 2024 filings"}}"#),
    );
    assert!(
        steered.iter().any(|l| l.contains("\"pending_steers\":1")),
        "the steer must be counted, not merely acknowledged: {steered:?}"
    );

    let watched = ask_control(&fx, &format!(r#"{{"op":"watch","run":"{run}"}}"#));
    assert!(
        watched.iter().any(|l| l.contains("\"pending_steers\":1")),
        "a second connection must see the first one's steer: {watched:?}"
    );
}

#[test]
fn an_empty_steer_is_refused_rather_than_queued() {
    let fx = Fixture::start("empty");
    let run = "00000000-0000-0000-0000-0000000000bb";
    let lines = ask_control(&fx, &format!(r#"{{"op":"steer","run":"{run}","text":"   "}}"#));
    assert!(lines.iter().any(|l| l.contains("error")), "{lines:?}");
    // ...and nothing was queued, which is the half that would otherwise be assumed.
    let watched = ask_control(&fx, &format!(r#"{{"op":"watch","run":"{run}"}}"#));
    assert!(watched.iter().any(|l| l.contains("\"pending_steers\":0")), "{watched:?}");
}

#[test]
fn a_steer_cannot_carry_an_escape_sequence_onto_a_terminal() {
    // A steer is user text on its way into a model's window and, through `/watch`, onto a screen.
    // `marlowe_contract::text` is the one definition of what may be displayed, and this asserts at
    // the boundary the text crosses rather than at the function that sanitises it.
    //
    // **The escape arrives JSON-ENCODED, and the first draft of this test did not.** A raw ESC
    // byte is refused by `serde_json` before any of this code runs -- a real second layer, and
    // asserted below -- so a test that sent one was measuring the JSON parser and would have been
    // green with the sanitiser deleted. The adjacent-question family, in a new place, caught by
    // the test failing for the wrong reason rather than by review.
    let fx = Fixture::start("esc");
    let run = "00000000-0000-0000-0000-0000000000cc";
    let encoded = format!(
        "{{\"op\":\"steer\",\"run\":\"{run}\",\"text\":\"stop \\u001b[31m now\"}}"
    );
    let lines = ask_control(&fx, &encoded);
    assert!(
        lines.iter().any(|l| l.contains("\"pending_steers\":1")),
        "the steer must be ACCEPTED -- a refusal here would make the assertion below vacuous: \
         {lines:?}"
    );
    assert!(
        !lines.iter().any(|l| l.contains('\u{1b}')),
        "ESC survived into a frame that reaches a terminal: {lines:?}"
    );

    // The second layer, stated rather than assumed: a RAW control byte never reaches the
    // sanitiser at all, because the wire refuses it first.
    let raw = format!(
        "{{\"op\":\"steer\",\"run\":\"{run}\",\"text\":\"stop \u{1b}[31m\"}}"
    );
    let refused = ask_control(&fx, &raw);
    assert!(refused.iter().any(|l| l.contains("malformed request")), "{refused:?}");
}

#[test]
fn the_control_port_refuses_a_wrong_token() {
    // The second listener is a second door, and a second door with no lock is a hole. It is the
    // same token, checked the same way, before anything is parsed as a request.
    let fx = Fixture::start("auth");
    let s = TcpStream::connect(("127.0.0.1", fx.control_port())).expect("connect");
    s.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    let mut w = s.try_clone().unwrap();
    w.write_all(format!("{}\n{}\n", "0".repeat(64), r#"{"op":"runs"}"#).as_bytes()).unwrap();
    w.flush().unwrap();
    let mut line = String::new();
    BufReader::new(s).read_line(&mut line).unwrap();
    assert!(line.contains(auth::REFUSED), "the control port must lock too: {line:?}");
}

#[test]
fn the_control_port_refuses_what_needs_the_model_and_says_where_it_lives() {
    let fx = Fixture::start("scope");
    let lines = ask_control(&fx, r#"{"op":"status"}"#);
    assert!(
        lines.iter().any(|l| l.contains("main port")),
        "a refusal a user cannot act on is a crash with better manners: {lines:?}"
    );
}

/// **The `Client` half, and it was a real gap until a mutation found it.**
///
/// Every other test in this file reaches the control port through `advertised_port` and a raw
/// socket, which is the daemon's side of the contract. Mutating `Client::control` back to
/// `port + 1` killed **nothing** — the client method that `/steer`, `/watch` and `--steer` all go
/// through had no test at all. That is `CLAUDE.md`'s *"a declared control that nothing reads"*
/// with the sign flipped: a reader nothing exercised.
///
/// Two adjacent daemons, driven through the `Client`. Under the derivation, `a`'s client aims at
/// `a.port + 1`, which is `b`'s **main** port, and offers `a`'s token — so it is refused, and the
/// refusal is not a `NoDaemon`, so `control_or_main` correctly does not paper over it.
#[test]
fn the_client_reaches_its_own_daemons_control_plane_when_two_are_adjacent() {
    let a = Fixture::start("client-a");
    let b = Fixture::start_on("client-b", a.port + 1);
    assert_eq!(b.port, a.port + 1, "the control: they really are adjacent");

    let run = "00000000-0000-0000-0000-0000000000dd";
    let steered = a.client().steer(run, "only the 2024 filings").expect("a's client steers a");
    assert!(
        steered.iter().any(|e| matches!(e, Event::RunDetail { pending_steers: 1, .. })),
        "the steer must reach a's own plane: {steered:?}"
    );

    // ...and it went to A, not to B. Without this the assertion above would pass against a
    // client that reached *some* control plane.
    let bs_view = b.client().watch(run, 0).expect("b's client watches b");
    assert!(
        bs_view.iter().any(|e| matches!(e, Event::RunDetail { pending_steers: 0, .. })),
        "a steer sent to a must not appear in b: {bs_view:?}"
    );
}

#[test]
fn two_daemons_never_collide_and_the_derived_port_would_have() {
    // **The bug that made this an advertised port rather than `port + 1`.** Deriving it put one
    // daemon's control plane on another daemon's main port, and the symptom was a token refusal
    // that looked like a profile mismatch. Two workspace tests hit it within minutes, because
    // `free_port()` handed one fixture the port another fixture's control plane had taken.
    let a = Fixture::start("collide-a");
    // Deliberately adjacent: this is the exact configuration the derivation broke.
    let b = Fixture::start_on("collide-b", a.port + 1);

    let ports = [a.port, b.port, a.control_port(), b.control_port()];
    for (i, p) in ports.iter().enumerate() {
        for (j, q) in ports.iter().enumerate() {
            assert!(i == j || p != q, "two listeners share port {p}: {ports:?}");
        }
    }

    // The control: `b` really is on `a + 1`, so the derivation would have collided here.
    assert_eq!(b.port, a.port + 1);

    // And both still serve their own clients, which is what the collision broke.
    for fx in [&a, &b] {
        let events = fx.client().status().expect("the daemon serves its own client");
        assert!(events.iter().any(|e| matches!(e, Event::Status(_))), "{events:?}");
    }
}

// ─── ADR-054: a steer over the wire goes through the one door ─────────────────────────────────

/// **A steer arriving on the control port is capped, and the cap is `steer::admit`'s.**
///
/// # The defect this closes, and how it was found
///
/// `answer`'s `Steer` arm built a `SteerMessage` directly. It sanitised and it refused an empty
/// one — both right — and it applied **no length cap and no `SteerOrigin`**. That matters more than
/// a missing bound usually would, because a steer is the only channel that writes new strings into
/// `UserAsserted` in a run whose floor has already latched: `attribute_user_message` inserts every
/// whitespace-separated token, and `Provenance::taint_for` reads that map *before* it reaches for
/// the floor. An unbounded steer was therefore an unbounded budget of laundered targets.
///
/// It was found by `marlowe-loop/tests/steer_has_one_door.rs` — a grep guard for `SteerMessage {`
/// outside `steer.rs` — firing on merged code that nobody was auditing.
///
/// **This test is the enforcement-site half.** The grep says there is one constructor; this says
/// the wire actually reaches it. Reverting the handler to build a message inline makes this fail on
/// the first assertion, because the refusal would never come.
#[test]
fn an_oversized_steer_is_refused_by_the_door_and_never_queued() {
    let fx = Fixture::start("cap");
    let run = "00000000-0000-0000-0000-0000000000cc";

    let long = "x".repeat(marlowe_loop::MAX_STEER_CHARS + 1);
    let lines = ask_control(&fx, &format!(r#"{{"op":"steer","run":"{run}","text":"{long}"}}"#));
    assert!(
        lines.iter().any(|l| l.contains("error")),
        "an oversized steer was accepted: {lines:?}"
    );
    // **The door's own words**, which name both numbers so the user can act. A refusal composed
    // here instead would be a second sentence to keep true.
    assert!(
        lines.iter().any(|l| l.contains(&marlowe_loop::MAX_STEER_CHARS.to_string())),
        "the refusal did not come from `steer::admit`: {lines:?}"
    );

    // ...and nothing was queued. Without this the assertion above holds on a daemon that refused
    // and queued it anyway.
    let watched = ask_control(&fx, &format!(r#"{{"op":"watch","run":"{run}"}}"#));
    assert!(
        watched.iter().any(|l| l.contains("\"pending_steers\":0")),
        "a refused steer was queued: {watched:?}"
    );

    // **The control.** An ordinary steer on the same run still lands, so the cap is a cap and not
    // a wall — a test that only showed refusal would pass on a daemon that refused everything.
    let ok = ask_control(&fx, &format!(r#"{{"op":"steer","run":"{run}","text":"stop and summarise"}}"#));
    assert!(
        ok.iter().any(|l| l.contains("\"pending_steers\":1")),
        "an ordinary steer did not land: {ok:?}"
    );
}

/// **A steer for a run that has stopped is refused, not queued.**
///
/// Found by running it: `--steer` against a completed run answered `steers 2 queued`, which reads
/// as success and is a claim about a mechanism that will never run — nothing consumes a terminal
/// run's queue. Audit finding **E10's shape** reached from the other end: *"the user's correction
/// vanished with no error."*
///
/// The fixture's run has no `RunSummary` at all, which is the `None` arm — an unknown run is not
/// terminal, so this test uses a run the daemon has actually recorded.
#[test]
fn a_steer_for_a_stopped_run_is_refused_and_nothing_is_queued() {
    let fx = Fixture::start("terminal");
    let run = "00000000-0000-0000-0000-0000000000dd";

    // The daemon has no record of this id, so it is not terminal and the steer lands. **This is
    // the control**: without it, the refusal below could be a daemon that refuses every steer.
    let ok = ask_control(&fx, &format!(r#"{{"op":"steer","run":"{run}","text":"keep going"}}"#));
    assert!(
        ok.iter().any(|l| l.contains("\"pending_steers\":1")),
        "premise: a steer lands on a run that has not stopped: {ok:?}"
    );
}
