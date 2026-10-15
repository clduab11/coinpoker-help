use super::*;

fn approval() -> Approval {
    Approval {
        version: 1,
        mode: "capture-only".into(),
        operator_assertion: Some("I am seated and ready".into()),
        source_policy: SourcePolicy::Manual,
        automatic_assertion: None,
        confirmed_at_unix_ms: 1_000,
        max_seconds: 600,
        max_frames: 1_200,
        inference_assertion: None,
        service_instance_id: None,
        experimental_bet_action: false,
        cpu_visual_board: false,
        source: WindowInfo {
            hwnd: 11,
            process_id: 22,
            exe_name: "CoinPoker.exe".into(),
            title: Some("SYNTHETIC PRIVATE TITLE".into()),
            on_screen: true,
            width: 800,
            height: 600,
        },
    }
}

#[test]
fn manual_capture_approval_is_fresh_strict_and_bounded() {
    let mut value = approval();
    assert!(valid_approval(&value, 31_000));
    assert!(!valid_approval(&value, 31_001));
    assert!(!valid_approval(&value, 999));
    value.max_frames = 1_201;
    assert!(!valid_approval(&value, 1_000));
    value.max_frames = 1_200;
    value.max_seconds = 601;
    assert!(!valid_approval(&value, 1_000));
    value.max_seconds = 600;
    value.operator_assertion = None;
    assert!(valid_approval(&value, 1_000));
    value.operator_assertion = Some("ready".into());
    assert!(!valid_approval(&value, 1_000));
}

#[test]
fn experimental_approval_is_bounded_automatic_only_and_capture_flag_is_explicit() {
    let mut value = approval();
    value.experimental_bet_action = true;
    assert!(!valid_approval(&value, 1_000));
    value.mode = "inference-enabled".into();
    value.inference_assertion = Some("USE INSTALLED IT1 FOR THIS SESSION".into());
    value.service_instance_id = Some("a1".repeat(16));
    assert!(!valid_approval(&value, 1_000));
    value.source_policy = SourcePolicy::AutomaticBounded;
    value.operator_assertion = None;
    value.automatic_assertion = Some("AUTHORIZE BOUNDED AUTOMATIC OBSERVATION".into());
    assert!(valid_approval(&value, 1_000));
    assert!(!valid_approval(&value, 31_001));
    for args in [
        vec![
            "--capture-only",
            "--experimental-bet-action",
            "--approval-file",
            "approval.json",
        ],
        vec![
            "--manual-inference",
            "--approval-file",
            "approval.json",
            "--experimental-bet-action",
        ],
        vec![
            "--manual-inference",
            "--experimental-bet-action",
            "approval.json",
        ],
    ] {
        assert!(run(&args.into_iter().map(String::from).collect::<Vec<_>>()).is_err());
    }
}

#[test]
fn manual_capture_identity_allows_only_resize_not_replacement() {
    let expected = approval().source;
    let mut current = expected.clone();
    current.width = 900;
    assert!(same_source(&expected, &current));
    current.hwnd += 1;
    assert!(!same_source(&expected, &current));
    current = expected.clone();
    current.process_id += 1;
    assert!(!same_source(&expected, &current));
    current = expected.clone();
    current.title = Some("REPLACEMENT".into());
    assert!(!same_source(&expected, &current));
}

#[test]
fn manual_inference_requires_separate_assertion_mode_and_service_instance() {
    let mut value = approval();
    value.mode = "inference-enabled".into();
    assert!(!valid_approval(&value, 1_000));
    value.inference_assertion = Some("USE INSTALLED IT1 FOR THIS SESSION".into());
    assert!(!valid_approval(&value, 1_000));
    value.service_instance_id = Some("a1".repeat(16));
    assert!(valid_approval(&value, 1_000));
    assert!(!valid_approval(&value, 31_001));
    assert!(!valid_approval(&value, 999));
    value.mode = "capture-only".into();
    assert!(!valid_approval(&value, 1_000));
    value.mode = "inference-enabled".into();
    value.inference_assertion = Some("yes".into());
    assert!(!valid_approval(&value, 1_000));
    assert!(run(&[
        "--manual-inference".into(),
        "--approval-file".into(),
        "approval.json".into()
    ])
    .is_err());
    assert!(run(&["--manual-inference".into(), "--enable-inference".into()]).is_err());
}

#[test]
fn manual_capture_budget_expiry_is_terminal_without_capture() {
    assert_eq!(
        budget_reason(600_000, 600_000, RecorderStatus::Active),
        Some("duration-limit")
    );
    assert_eq!(
        budget_reason(0, 600_000, RecorderStatus::CountLimit),
        Some("frame-limit")
    );
    assert_eq!(
        budget_reason(0, 600_000, RecorderStatus::IoFailure),
        Some("recorder-failure")
    );
    assert_eq!(budget_reason(0, 600_000, RecorderStatus::Active), None);
    assert!(run(&["--capture-only".into(), "--enable-inference".into()]).is_err());
}

#[test]
fn automatic_approval_requires_its_own_policy_and_never_a_seated_assertion() {
    let mut value = approval();
    value.mode = "inference-enabled".into();
    value.source_policy = SourcePolicy::AutomaticBounded;
    value.automatic_assertion = Some("AUTHORIZE BOUNDED AUTOMATIC OBSERVATION".into());
    value.inference_assertion = Some("USE INSTALLED IT1 FOR THIS SESSION".into());
    value.service_instance_id = Some("a1".repeat(16));
    assert!(!valid_approval(&value, 1_000));
    value.operator_assertion = None;
    assert!(valid_approval(&value, 1_000));
    assert!(!valid_approval(&value, 31_001));
    value.mode = "capture-only".into();
    assert!(!valid_approval(&value, 1_000));
    value.mode = "inference-enabled".into();
    value.source_policy = SourcePolicy::Manual;
    assert!(!valid_approval(&value, 1_000));
    value.source_policy = SourcePolicy::AutomaticBounded;
    value.automatic_assertion = Some("yes".into());
    assert!(!valid_approval(&value, 1_000));
}

#[test]
fn sustained_approval_version_consent_source_and_evidence_caps_are_strict() {
    let mut value = approval();
    value.mode = "inference-enabled".into();
    value.operator_assertion = None;
    value.inference_assertion = Some("USE INSTALLED IT1 FOR THIS SESSION".into());
    value.service_instance_id = Some("a1".repeat(16));
    value.source_policy = SourcePolicy::AutomaticSustained;
    value.automatic_assertion = Some("AUTHORIZE SUSTAINED SAME-SOURCE OBSERVATION".into());
    assert!(
        !valid_approval(&value, 1_000),
        "v1 must never authorize sustained"
    );
    value.version = 2;
    assert!(valid_approval(&value, 31_000));
    assert!(!valid_approval(&value, 31_001));
    assert!(!valid_approval(&value, 999));
    assert_eq!(
        serde_json::to_value(value.source_policy).unwrap(),
        "automatic-sustained"
    );
    assert!(value.source_policy.is_automatic());
    for policy in [SourcePolicy::Manual, SourcePolicy::AutomaticBounded] {
        value.source_policy = policy;
        assert!(
            !valid_approval(&value, 1_000),
            "v2 only authorizes sustained"
        );
    }
    value.source_policy = SourcePolicy::AutomaticSustained;
    for assertion in [
        None,
        Some("yes"),
        Some("AUTHORIZE BOUNDED AUTOMATIC OBSERVATION"),
    ] {
        value.automatic_assertion = assertion.map(String::from);
        assert!(!valid_approval(&value, 1_000));
    }
    value.automatic_assertion = Some("AUTHORIZE SUSTAINED SAME-SOURCE OBSERVATION".into());
    value.operator_assertion = Some("I am seated and ready".into());
    assert!(!valid_approval(&value, 1_000));
    value.operator_assertion = None;
    value.experimental_bet_action = true;
    assert!(!valid_approval(&value, 1_000));
    value.experimental_bet_action = false;
    value.mode = "capture-only".into();
    assert!(!valid_approval(&value, 1_000));
    value.mode = "inference-enabled".into();
    value.service_instance_id = None;
    assert!(!valid_approval(&value, 1_000));
    value.service_instance_id = Some("a1".repeat(16));
    value.inference_assertion = None;
    assert!(!valid_approval(&value, 1_000));
    value.inference_assertion = Some("USE INSTALLED IT1 FOR THIS SESSION".into());
    for seconds in [0, 601] {
        value.max_seconds = seconds;
        assert!(!valid_approval(&value, 1_000));
    }
    value.max_seconds = 600;
    for frames in [0, 1_201] {
        value.max_frames = frames;
        assert!(!valid_approval(&value, 1_000));
    }
    value.max_frames = 1_200;
    let original = value.source.clone();
    for field in [
        "hwnd",
        "pid",
        "exe",
        "title",
        "minimized",
        "width",
        "height",
    ] {
        value.source = original.clone();
        match field {
            "hwnd" => value.source.hwnd = 0,
            "pid" => value.source.process_id = 0,
            "exe" => value.source.exe_name = "other.exe".into(),
            "title" => value.source.title = None,
            "minimized" => value.source.on_screen = false,
            "width" => value.source.width = 0,
            _ => value.source.height = 0,
        }
        assert!(!valid_approval(&value, 1_000), "{field}");
    }
    value.source = original;
    assert!(valid_approval(&value, 1_000));
}

struct FakeSource {
    windows: Vec<WindowInfo>,
    captures: usize,
    selected: Vec<WindowInfo>,
    resize: bool,
    replace_after_capture: bool,
    stale_first: bool,
}

impl CaptureSource for FakeSource {
    fn discover(
        &mut self,
    ) -> Result<ingest::capture::DiscoverySnapshot, ingest::capture::CaptureError> {
        if self.resize && self.captures == 1 {
            self.windows[0].width = 900;
        }
        if self.replace_after_capture && self.captures > 0 {
            self.windows[0].hwnd += 1;
        }
        Ok(ingest::capture::DiscoverySnapshot {
            windows: self.windows.clone(),
            ..Default::default()
        })
    }
    fn select(&mut self, window: &WindowInfo) -> Result<(), ingest::capture::CaptureError> {
        self.selected.push(window.clone());
        Ok(())
    }
    fn capture(&mut self) -> Result<ingest::capture::Frame, ingest::capture::CaptureError> {
        self.captures += 1;
        if self.stale_first && self.captures == 1 {
            return Err(ingest::capture::CaptureError::StaleWindow {
                hwnd: self.windows[0].hwnd,
            });
        }
        Ok(ingest::capture::Frame::new(2, 2, [1, 2, 3, 255].repeat(4)).unwrap())
    }
    fn reset(&mut self) {}
}

#[test]
fn manual_capture_fake_source_count_resize_and_stop_are_one_shot() {
    let base = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join(".local/laya/train/manual-inference-20261012/native/capture-only-fixtures");
    for case in [
        "count",
        "resize",
        "replacement",
        "replacement_after",
        "stop",
        "time",
        "stale_unchanged",
        "stale_resize",
    ] {
        let root = base.join(format!(
            "{case}-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        let mut approval = approval();
        approval.max_frames = if case == "resize" { 2 } else { 1 };
        let mut source = FakeSource {
            windows: vec![approval.source.clone()],
            captures: 0,
            selected: vec![],
            resize: matches!(case, "resize" | "stale_resize"),
            replace_after_capture: case == "replacement_after",
            stale_first: case.starts_with("stale_"),
        };
        let clock = std::cell::Cell::new(if case == "time" { 600_000 } else { 0 });
        if case == "stop" {
            fs::write(root.join("STOP"), b"stop").unwrap();
        }
        if case == "replacement" {
            source.windows[0].hwnd += 1;
        }
        capture_loop(
            &mut source,
            &approval,
            &root,
            &root.join("STOP"),
            || clock.get(),
            || clock.set(clock.get() + 500),
        )
        .unwrap();
        assert_eq!(
            source.captures,
            match case {
                "count" | "replacement_after" | "stale_unchanged" => 1,
                "resize" | "stale_resize" => 2,
                _ => 0,
            }
        );
        if matches!(case, "resize" | "stale_resize") {
            assert_eq!(
                source
                    .selected
                    .iter()
                    .map(|window| window.width)
                    .collect::<Vec<_>>(),
                [800, 900]
            );
        }
        assert_eq!(
            fs::read_dir(root.join(".local/captures")).unwrap().count(),
            1
        );
        if matches!(case, "replacement_after" | "stale_unchanged") {
            let session = fs::read_dir(root.join(".local/captures"))
                .unwrap()
                .next()
                .unwrap()
                .unwrap()
                .path();
            assert_eq!(
                fs::metadata(session.join("manifest.jsonl")).unwrap().len(),
                0
            );
        }
    }
}
