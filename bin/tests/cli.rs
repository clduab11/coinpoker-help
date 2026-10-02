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

const REJECTED_SENTINEL: &str = "SYNTHETIC_REJECTED_FIELD_SENTINEL";

fn assert_private_output(output: &Output) {
    for bytes in [&output.stdout, &output.stderr] {
        let text = String::from_utf8_lossy(bytes);
        for forbidden in [
            REJECTED_SENTINEL,
            "invalid game state",
            "invalid card rank",
            "unknown available action",
            "duplicate player name",
            "missing field",
            "unknown variant",
            "expects exactly",
        ] {
            assert!(
                !text.contains(forbidden),
                "leaked rejected input or parser prose"
            );
        }
    }
}

fn assert_stdin_category(input: &str, category: &str) {
    let output = run_with_stdin(&["--stdin"], &format!("{input}\n"));
    assert!(output.status.success());
    assert!(
        output.stdout.is_empty(),
        "rejected input must not produce advice"
    );
    assert_eq!(String::from_utf8_lossy(&output.stderr).trim(), category);
    assert_private_output(&output);
}

fn rejected_state(category: &str) -> serde_json::Value {
    let mut state: serde_json::Value = serde_json::from_str(ACTION_STATE).unwrap();
    state["players"][1]["name"] = serde_json::json!(REJECTED_SENTINEL);
    match category {
        "board-count" => {
            state["board"] = serde_json::json!([
                {"rank": REJECTED_SENTINEL, "suit": "clubs"}
            ])
        }
        "hero-cards" => state["hero_cards"][0]["rank"] = serde_json::json!(REJECTED_SENTINEL),
        "action-required" => state["available_actions"] = serde_json::json!([REJECTED_SENTINEL]),
        "schema" => state["game_phase"] = serde_json::json!(REJECTED_SENTINEL),
        "invalid-observation" => state["players"][0]["name"] = serde_json::json!(REJECTED_SENTINEL),
        _ => panic!("unknown test category"),
    }
    state
}

fn assert_evaluation_category(response: serde_json::Value, category: &str) {
    let directory =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../target/category-tests");
    std::fs::create_dir_all(&directory).unwrap();
    let path = directory.join(format!("{}-{category}.json", std::process::id()));
    let manifest = serde_json::json!({
        "format": 2, "source": "synthetic", "cases": [{
            "id": "synthetic-reject", "sequence": "synthetic-reject",
            "identity": {"exe_name": "Synthetic.exe", "process_id": 42, "hwnd": "0x7"},
            "metadata": "table_title", "expected_kind": "unknown", "expected_state": null,
            "recommendation_allowed": false, "tags": ["synthetic-reject"], "image": null,
            "synthetic_image": {"width": 160, "height": 120, "seed": 7},
            "response": response, "freshness": null
        }]
    });
    std::fs::write(&path, manifest.to_string()).unwrap();
    let output = run(&[
        "--evaluate",
        path.to_str().unwrap(),
        "--vlm-endpoint",
        "http://127.0.0.1:0/v1/chat/completions",
    ]);
    std::fs::remove_file(path).unwrap();
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        report["rejection_categories"],
        serde_json::json!({category: 1})
    );
    assert_eq!(report["recommendations_emitted"], 0);
    assert_eq!(report["request_errors"], 0);
    assert_eq!(report["source"], "synthetic");
    assert_eq!(report["beta_acceptance"], false);
    assert_private_output(&output);
}

fn rejection_response(category: &str) -> serde_json::Value {
    serde_json::json!({
        "screen_kind": "poker_table",
        "evidence": {"table_layout": true, "hero_cards": true, "board_area": true,
            "pot": true, "action_controls": true, "readable": true},
        "state": rejected_state(category)
    })
}

#[test]
fn safe_category_stdin_board_count() {
    assert_stdin_category(&rejected_state("board-count").to_string(), "board-count");
}

#[test]
fn safe_category_stdin_hero_cards() {
    assert_stdin_category(&rejected_state("hero-cards").to_string(), "hero-cards");
}

#[test]
fn safe_category_stdin_action_required() {
    assert_stdin_category(
        &rejected_state("action-required").to_string(),
        "action-required",
    );
}

#[test]
fn safe_category_stdin_schema_malformed_and_unknown_are_private() {
    for category in ["schema", "invalid-observation"] {
        assert_stdin_category(&rejected_state(category).to_string(), category);
    }
    assert_stdin_category(&format!("{{{REJECTED_SENTINEL}}}"), "malformed");
}

#[test]
fn safe_category_evaluation_board_count() {
    assert_evaluation_category(rejection_response("board-count"), "board-count");
}

#[test]
fn safe_category_evaluation_hero_cards() {
    assert_evaluation_category(rejection_response("hero-cards"), "hero-cards");
}

#[test]
fn safe_category_evaluation_action_required() {
    assert_evaluation_category(rejection_response("action-required"), "action-required");
}

#[test]
fn safe_category_evaluation_schema_and_unknown_are_private() {
    for category in ["schema", "invalid-observation"] {
        assert_evaluation_category(rejection_response(category), category);
    }
    let mut response = rejection_response("board-count");
    response[REJECTED_SENTINEL] = serde_json::json!(REJECTED_SENTINEL);
    assert_evaluation_category(response, "schema");
}

#[test]
fn help_prints_usage_and_succeeds() {
    let output = run(&["--help"]);
    assert!(output.status.success());
    let stdout = String::from_utf8(output.stdout).expect("utf-8 stdout");
    assert!(stdout.contains("Usage: coinpoker [OPTION]"));
    assert!(stdout.contains("--stdin"));
    assert!(stdout.contains("--list-windows"));
    assert!(stdout.contains("--exe-name"));
    assert!(stdout.contains("--window-hwnd"));
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
    assert_eq!(stderr.trim(), "board-count");
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
    assert_eq!(stderr.trim(), "schema");
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
    assert_eq!(stderr.trim(), "malformed");
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
    assert_eq!(stderr.trim(), "invalid-observation");
}

#[test]
fn a_valid_state_recovers_after_invalid_input_without_duplicate_clears() {
    let input = format!("{ACTION_STATE}\n{{invalid}}\n{{invalid}}\n{ACTION_STATE}\n");
    let output = run_with_stdin(&["--stdin"], &input);
    assert!(output.status.success());
    let events: Vec<serde_json::Value> = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    assert_eq!(events.len(), 3);
    assert!(events[0]["action"].is_string());
    assert_eq!(events[1]["event"], "clear");
    assert!(events[2]["action"].is_string());
}

#[test]
fn evaluates_synthetic_image_contracts_without_a_server() {
    let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../fixtures/synthetic/manifest.json");
    let output = run(&["--evaluate", manifest.to_str().unwrap()]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["format"], 2);
    assert_eq!(report["beta_acceptance"], false);
    assert_eq!(report["critical_actionable_false_positives"], 0);
    assert_eq!(report["stale_result_suppression_failures"], 0);
    assert_eq!(report["source"], "synthetic");
}

#[cfg(not(target_os = "windows"))]
#[test]
fn non_windows_live_capture_fails_actionably() {
    let output = run(&[]);
    assert!(!output.status.success());
    assert!(String::from_utf8(output.stderr)
        .unwrap()
        .contains("Windows"));
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
