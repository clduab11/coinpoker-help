use std::io::Write;
use std::process::{Command, Output, Stdio};

fn run(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_coinpoker"))
        .args(args)
        .output()
        .expect("run coinpoker")
}

fn run_with_stdin(args: &[&str], input: &str) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_coinpoker"))
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn coinpoker");
    child
        .stdin
        .take()
        .expect("piped stdin")
        .write_all(input.as_bytes())
        .expect("write stdin");
    child.wait_with_output().expect("wait for coinpoker")
}

const ACTION_STATE: &str = r#"{"game_phase":"flop","hero_cards":[{"rank":"A","suit":"spades"},{"rank":"A","suit":"hearts"}],"board":[{"rank":"K","suit":"diamonds"},{"rank":"7","suit":"clubs"},{"rank":"2","suit":"spades"}],"pot_size":1000,"to_call":0,"hero_chips":5000,"min_raise_to":500,"max_raise_to":5000,"players":[{"name":"Hero","chips":5000,"last_action":"check","bet_amount":0},{"name":"Villain","chips":5000,"last_action":"check","bet_amount":0}],"action_required":true,"available_actions":["check","raise"]}"#;

#[test]
fn help_prints_usage_and_succeeds() {
    let output = run(&["--help"]);
    assert!(output.status.success());
    let stdout = String::from_utf8(output.stdout).expect("utf-8 stdout");
    assert!(stdout.contains("Usage: coinpoker [OPTION]"));
    assert!(stdout.contains("--stdin"));
    assert!(stdout.contains("--list-windows"));
}

#[test]
fn unknown_and_extra_arguments_exit_with_usage() {
    for args in [&["--unknown"][..], &["--stdin", "extra"][..]] {
        let output = run(args);
        assert_eq!(output.status.code(), Some(2));
        let stderr = String::from_utf8(output.stderr).expect("utf-8 stderr");
        assert!(stderr.contains("Usage: coinpoker [OPTION]"));
    }
}

#[test]
fn ui_option_truthfully_reports_unimplemented_feed() {
    let output = run(&["--ui"]);
    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8(output.stderr).expect("utf-8 stderr");
    assert!(stderr.contains("interactive feed is not implemented"));
    assert!(stderr.contains("--stdin"));
}

#[test]
fn stdin_rejects_deserialized_but_invalid_states() {
    let invalid_state = concat!(
        r#"{"game_phase":"flop","hero_cards":[{"rank":"A","suit":"spades"},"#,
        r#"{"rank":"K","suit":"hearts"}],"board":[],"pot_size":100,"#,
        r#""to_call":0,"hero_chips":1000,"players":[],"action_required":true,"#,
        r#""available_actions":["check","raise"]}"#,
        "\n"
    );
    let output = run_with_stdin(&["--stdin"], invalid_state);
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8(output.stderr).expect("utf-8 stderr");
    assert!(stderr.contains("invalid game state"));
    assert!(stderr.contains("expects exactly 3 board cards"));
}

#[test]
fn stdin_rejects_states_missing_critical_numeric_fields() {
    let incomplete = concat!(
        r#"{"game_phase":"preflop","hero_cards":[],"board":[],"players":[],"#,
        r#""action_required":false,"available_actions":[]}"#,
        "\n"
    );
    let output = run_with_stdin(&["--stdin"], incomplete);
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8(output.stderr).expect("utf-8 stderr");
    assert!(stderr.contains("missing field `pot_size`"));
}

#[test]
fn stdin_emits_legal_decision_then_clear_event() {
    let clear_state = r#"{"game_phase":"flop","hero_cards":[{"rank":"A","suit":"spades"},{"rank":"A","suit":"hearts"}],"board":[{"rank":"K","suit":"diamonds"},{"rank":"7","suit":"clubs"},{"rank":"2","suit":"spades"}],"pot_size":1000,"to_call":0,"hero_chips":5000,"min_raise_to":null,"max_raise_to":null,"players":[{"name":"Hero","chips":5000,"last_action":"check","bet_amount":0},{"name":"Villain","chips":5000,"last_action":"check","bet_amount":0}],"action_required":false,"available_actions":[]}"#;
    let input = format!("{ACTION_STATE}\n{clear_state}\n");

    let output = run_with_stdin(&["--stdin"], &input);
    assert!(output.status.success());
    assert!(output.stderr.is_empty());

    let stdout = String::from_utf8(output.stdout).expect("utf-8 stdout");
    let lines: Vec<&str> = stdout.lines().collect();
    assert_eq!(lines.len(), 2);

    let decision: serde_json::Value = serde_json::from_str(lines[0]).expect("decision json");
    assert_eq!(decision["action"], "raise");
    let amount = decision["amount"].as_u64().expect("raise amount");
    assert!((500..=5000).contains(&amount));

    let clear: serde_json::Value = serde_json::from_str(lines[1]).expect("clear json");
    assert_eq!(clear["event"], "clear");
    assert_eq!(clear["reason"], "action-not-required");
}

#[test]
fn malformed_stdin_invalidates_an_active_decision() {
    let input = format!("{ACTION_STATE}\n{{not-json}}\n");
    let output = run_with_stdin(&["--stdin"], &input);
    assert!(output.status.success());

    let stdout = String::from_utf8(output.stdout).expect("utf-8 stdout");
    let lines: Vec<&str> = stdout.lines().collect();
    assert_eq!(lines.len(), 2);
    let clear: serde_json::Value = serde_json::from_str(lines[1]).expect("clear json");
    assert_eq!(clear["event"], "clear");
    assert_eq!(clear["reason"], "invalid-state");

    let stderr = String::from_utf8(output.stderr).expect("utf-8 stderr");
    assert!(stderr.contains("invalid state line"));
}

#[test]
fn invalid_stdin_state_invalidates_an_active_decision() {
    let invalid_state = ACTION_STATE.replace("\"chips\":5000", "\"chips\":4999");
    let input = format!("{ACTION_STATE}\n{invalid_state}\n");
    let output = run_with_stdin(&["--stdin"], &input);
    assert!(output.status.success());

    let stdout = String::from_utf8(output.stdout).expect("utf-8 stdout");
    let lines: Vec<&str> = stdout.lines().collect();
    assert_eq!(lines.len(), 2);
    let clear: serde_json::Value = serde_json::from_str(lines[1]).expect("clear json");
    assert_eq!(clear["event"], "clear");
    assert_eq!(clear["reason"], "invalid-state");

    let stderr = String::from_utf8(output.stderr).expect("utf-8 stderr");
    assert!(stderr.contains("do not match hero_chips"));
}

#[test]
fn multiway_state_does_not_recommend_a_raise() {
    let multiway = ACTION_STATE.replace(
        "],\"action_required\":true",
        ",{\"name\":\"Villain2\",\"chips\":5000,\"last_action\":\"check\",\"bet_amount\":0}],\"action_required\":true",
    );
    let output = run_with_stdin(&["--stdin"], &format!("{multiway}\n"));
    assert!(output.status.success());
    assert!(output.stderr.is_empty());

    let decision: serde_json::Value =
        serde_json::from_slice(&output.stdout).expect("decision json");
    assert_ne!(decision["action"], "raise");
    assert_eq!(decision["action"], "check");
}

#[test]
fn multiway_all_in_state_is_suppressed_until_side_pots_are_modeled() {
    let side_pot = ACTION_STATE.replace(
        r#"{"name":"Villain","chips":5000,"last_action":"check","bet_amount":0}"#,
        concat!(
            r#"{"name":"Villain","chips":0,"last_action":"allin","bet_amount":0},"#,
            r#"{"name":"Villain2","chips":5000,"last_action":"check","bet_amount":0}"#,
        ),
    );
    let output = run_with_stdin(&["--stdin"], &format!("{side_pot}\n"));
    assert!(output.status.success());
    assert!(output.stdout.is_empty());

    let stderr = String::from_utf8(output.stderr).expect("utf-8 stderr");
    assert!(stderr.contains("side-pot-aware EV"));
}
