use ingest::discovery::DiscoveryConfig;
use ingest::recorder::{RecorderConfig, PRIVATE_CAPTURE_DIR};
use ingest::runtime::RuntimeConfig;
use ingest::vlm::VlmConfig;
use std::collections::HashMap;

pub const USAGE: &str = "Usage: coinpoker [OPTION] [CONFIGURATION]\n\n\
  (no option)        Run the Windows capture pipeline\n\
  --stdin            Read legacy GameState JSON lines (all platforms)\n\
  --list-windows     Print application/window identity JSON lines; no pixels\n\
  --doctor           Run local installation/model/capture diagnostics\n\
  --evaluate PATH    Evaluate a version-2 local visual fixture manifest\n\
  --ui               Rejected: use the read-only browser dashboard (exit 2)\n\
  -h, --help         Print this help\n\n\
Configuration (CLI > nonempty environment > defaults):\n\
  --exe-name NAME             COINPOKER_EXE_NAME (exact; calibrate first)\n\
  --pid PID                   COINPOKER_PID (optional restriction)\n\
  --window-hwnd HWND          COINPOKER_WINDOW_HWND (hex or decimal; hard pin)\n\
  --table-title TEXT          COINPOKER_WINDOW_TITLE (calibrated substring)\n\
  --lobby-title TEXT          COINPOKER_LOBBY_TITLE (lobby veto substring)\n\
  --lobby-size WIDTHxHEIGHT   COINPOKER_LOBBY_SIZE (observed lobby size)\n\
  --vlm-endpoint URL          COINPOKER_VLM_ENDPOINT (loopback port 18090; /v1/laya/predict)\n\
  --vlm-model NAME            COINPOKER_VLM_MODEL (Laya server model alias)\n\
  --laya-threshold N          COINPOKER_LAYA_THRESHOLD (0.80..0.99; only raises)\n\
  --timeout-secs N            COINPOKER_VLM_TIMEOUT_SECS (1..120, default 5)\n\
  --decision-budget-ms N      COINPOKER_DECISION_BUDGET_MS (500..5000, default 5000 total)\n\
  --poll-ms N                 COINPOKER_POLL_MS (50..1000)\n\
  --discovery-ms N            COINPOKER_DISCOVERY_MS (500..5000)\n\
  --retry-ms N                COINPOKER_RETRY_MS (500..30000)\n\
  --stable-ms N               COINPOKER_STABLE_MS (100..5000)\n\
  --stable-captures N         COINPOKER_STABLE_CAPTURES (2..50)\n\
  --refresh-ms N              COINPOKER_REFRESH_MS (1000..10000)\n\
  --max-frame-age-ms N        COINPOKER_MAX_FRAME_AGE_MS (500..10000)\n\
  --channel-delta N           COINPOKER_CHANNEL_DELTA (1..128)\n\
  --changed-fraction N        COINPOKER_CHANGED_FRACTION (0.000001..1)\n\
  --local-fraction N          COINPOKER_LOCAL_FRACTION (0.000001..1)\n\
  --tile-size N               COINPOKER_TILE_SIZE (8..128)\n\
  --sample-stride N           COINPOKER_SAMPLE_STRIDE (1..64)\n\n\
Approved observing capabilities (capture mode, CLI opt-in only):\n\
  --wager-registry .local/PATH.json   Versioned per-seat proof; unapproved seats stay unknown\n\n\
  --scene-registry .local/PATH.json   Versioned seat-scene proof; disabled without approval\n\n\
Private recording (capture mode, CLI opt-in only):\n\
  --record-dir .local/captures  Fixed private base; new UTC practice session only\n\
  --record-max-frames N        1..20000, default 7200\n\
  --record-max-bytes N         1..2147483648, default 1073741824 (PNG + manifest)\n\
  --record-interval-ms N       250..60000, default 500; sampled, not every frame\n";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Mode {
    Capture,
    Stdin,
    ListWindows,
    Doctor,
    Evaluate(String),
    Help,
}
#[derive(Debug, Clone)]
pub struct Options {
    pub mode: Mode,
    pub discovery: DiscoveryConfig,
    pub runtime: RuntimeConfig,
    pub vlm: VlmConfig,
    pub recording: Option<RecorderConfig>,
    pub wager_registry: Option<String>,
    pub scene_registry: Option<String>,
}

const RECORD_FLAGS: &[&str] = &[
    "--record-dir",
    "--record-max-frames",
    "--record-max-bytes",
    "--record-interval-ms",
];

const FLAGS: &[(&str, &str)] = &[
    ("--exe-name", "COINPOKER_EXE_NAME"),
    ("--pid", "COINPOKER_PID"),
    ("--window-hwnd", "COINPOKER_WINDOW_HWND"),
    ("--table-title", "COINPOKER_WINDOW_TITLE"),
    ("--lobby-title", "COINPOKER_LOBBY_TITLE"),
    ("--lobby-size", "COINPOKER_LOBBY_SIZE"),
    ("--vlm-endpoint", "COINPOKER_VLM_ENDPOINT"),
    ("--vlm-model", "COINPOKER_VLM_MODEL"),
    ("--laya-threshold", "COINPOKER_LAYA_THRESHOLD"),
    ("--timeout-secs", "COINPOKER_VLM_TIMEOUT_SECS"),
    ("--decision-budget-ms", "COINPOKER_DECISION_BUDGET_MS"),
    ("--poll-ms", "COINPOKER_POLL_MS"),
    ("--discovery-ms", "COINPOKER_DISCOVERY_MS"),
    ("--retry-ms", "COINPOKER_RETRY_MS"),
    ("--stable-ms", "COINPOKER_STABLE_MS"),
    ("--stable-captures", "COINPOKER_STABLE_CAPTURES"),
    ("--refresh-ms", "COINPOKER_REFRESH_MS"),
    ("--max-frame-age-ms", "COINPOKER_MAX_FRAME_AGE_MS"),
    ("--channel-delta", "COINPOKER_CHANNEL_DELTA"),
    ("--changed-fraction", "COINPOKER_CHANGED_FRACTION"),
    ("--local-fraction", "COINPOKER_LOCAL_FRACTION"),
    ("--tile-size", "COINPOKER_TILE_SIZE"),
    ("--sample-stride", "COINPOKER_SAMPLE_STRIDE"),
];

pub fn parse(
    args: impl IntoIterator<Item = String>,
    env: impl Fn(&str) -> Option<String>,
) -> Result<Options, String> {
    let mut overrides = HashMap::new();
    let mut args = args.into_iter();
    let mut mode = None;
    while let Some(arg) = args.next() {
        let next_mode = match arg.as_str() {
            "--stdin" => Some(Mode::Stdin), "--list-windows" => Some(Mode::ListWindows),
            "--doctor" => Some(Mode::Doctor),
            "--help" | "-h" => Some(Mode::Help),
            "--evaluate" => Some(Mode::Evaluate(args.next().ok_or("--evaluate requires a manifest path")?)),
            "--ui" => return Err("--ui is unavailable: no native interactive UI; open the separately launched read-only dashboard at http://127.0.0.1:18090/ or use --stdin for legacy JSON-lines output".into()),
            _ => {
                if let Some(flag) = FLAGS.iter().map(|(flag, _)| *flag)
                    .chain(RECORD_FLAGS.iter().copied()).chain(["--wager-registry", "--scene-registry"]).find(|flag| *flag == arg) {
                    let value = args.next().filter(|v| !v.trim().is_empty() && !v.starts_with("--"))
                        .ok_or_else(|| format!("{flag} requires a nonempty value"))?;
                    if overrides.insert(flag, value).is_some() { return Err(format!("duplicate option {flag}")); }
                } else { return Err(format!("unknown option or extra argument: {arg}")); }
                None
            }
        };
        if let Some(next_mode) = next_mode {
            if mode.replace(next_mode).is_some() {
                return Err("choose only one mode".into());
            }
        }
    }
    let mode = mode.unwrap_or(Mode::Capture);
    let mut options = Options {
        mode,
        discovery: DiscoveryConfig::default(),
        runtime: RuntimeConfig::default(),
        vlm: VlmConfig::default(),
        recording: None,
        wager_registry: None,
        scene_registry: None,
    };
    let recording_requested = RECORD_FLAGS.iter().any(|flag| overrides.contains_key(flag));
    if recording_requested && !matches!(options.mode, Mode::Capture | Mode::Help) {
        return Err("private recording is available only in capture mode".into());
    }
    for flag in ["--wager-registry", "--scene-registry"] {
        if let Some(path) = overrides.get(flag) {
            if !matches!(options.mode, Mode::Capture | Mode::Help) {
                return Err("wager registry is available only in capture mode".into());
            }
            let file = std::path::Path::new(path);
            if path.len() > 4096
                || path.bytes().any(|b| b < 32 || b == 127)
                || path.contains(':')
                || file.is_absolute()
                || !file.starts_with(".local")
                || file.extension().is_none_or(|ext| ext != "json")
                || file
                    .components()
                    .any(|c| !matches!(c, std::path::Component::Normal(_)))
            {
                return Err("wager registry must be a private relative .local JSON path".into());
            }
            if flag == "--wager-registry" {
                options.wager_registry = Some(path.clone());
            } else {
                options.scene_registry = Some(path.clone());
            }
        }
    }
    // Replay/help must not depend on capture/VLM environment configuration.
    if matches!(options.mode, Mode::Stdin | Mode::Help) {
        return Ok(options);
    }
    let value = |flag: &str| -> Option<String> {
        overrides.get(flag).cloned().or_else(|| {
            FLAGS
                .iter()
                .find(|(f, _)| *f == flag)
                .and_then(|(_, key)| env(key))
                .filter(|s| !s.trim().is_empty())
        })
    };
    options.discovery.exe_name = value("--exe-name");
    options.discovery.table_title = value("--table-title");
    options.discovery.lobby_title = value("--lobby-title");
    if let Some(size) = value("--lobby-size") {
        let (width, height) = parse_lobby_size(&size)?;
        options.discovery.lobby_width = Some(width);
        options.discovery.lobby_height = Some(height);
    }
    fn number<T: std::str::FromStr>(
        value: Option<String>,
        flag: &str,
    ) -> Result<Option<T>, String> {
        value
            .map(|v| {
                v.parse()
                    .map_err(|_| format!("invalid numeric value for {flag}"))
            })
            .transpose()
    }
    options.discovery.process_id = number(value("--pid"), "--pid")?;
    options.discovery.window_hwnd = value("--window-hwnd")
        .map(|value| parse_hwnd(&value))
        .transpose()?;
    if options.discovery.process_id == Some(0) || options.discovery.window_hwnd == Some(0) {
        return Err("PID and window HWND must be positive".into());
    }
    if let Some(v) = value("--vlm-endpoint") {
        options.vlm.endpoint = v;
    }
    if let Some(v) = value("--vlm-model") {
        options.vlm.model = v;
    }
    macro_rules! set {
        ($field:expr, $flag:literal) => {
            if let Some(v) = number(value($flag), $flag)? {
                $field = v;
            }
        };
    }
    set!(options.vlm.timeout_secs, "--timeout-secs");
    set!(options.runtime.decision_budget_ms, "--decision-budget-ms");
    set!(options.runtime.poll_ms, "--poll-ms");
    set!(options.runtime.discovery_ms, "--discovery-ms");
    set!(options.runtime.retry_ms, "--retry-ms");
    set!(options.runtime.force_refresh_ms, "--refresh-ms");
    set!(options.runtime.max_frame_age_ms, "--max-frame-age-ms");
    set!(options.runtime.stability.stable_ms, "--stable-ms");
    set!(
        options.runtime.stability.stable_captures,
        "--stable-captures"
    );
    set!(options.runtime.change.channel_delta, "--channel-delta");
    set!(
        options.runtime.change.changed_fraction,
        "--changed-fraction"
    );
    set!(
        options.runtime.change.local_changed_fraction,
        "--local-fraction"
    );
    set!(options.runtime.change.tile_size, "--tile-size");
    set!(options.runtime.change.sample_stride, "--sample-stride");
    if recording_requested {
        let directory = overrides
            .get("--record-dir")
            .ok_or("recorder limits require --record-dir .local/captures opt-in")?;
        if directory != PRIVATE_CAPTURE_DIR && directory != ".local\\captures" {
            return Err("--record-dir accepts only .local/captures; arbitrary paths and traversal are refused".into());
        }
        let mut recording = RecorderConfig::default();
        set!(recording.max_frames, "--record-max-frames");
        set!(recording.max_bytes, "--record-max-bytes");
        set!(recording.interval_ms, "--record-interval-ms");
        recording.validate()?;
        options.recording = Some(recording);
    }
    options.runtime.validate()?;
    if !(1..=120).contains(&options.vlm.timeout_secs) {
        return Err("timeout must be 1..120 seconds".into());
    }
    if let Some(threshold) = number::<f32>(value("--laya-threshold"), "--laya-threshold")? {
        // The global threshold can only raise per-pass thresholds (0.80 in 0.4.0).
        if !(0.80..=0.99).contains(&threshold) {
            return Err("--laya-threshold must be 0.80..0.99".into());
        }
        options.vlm.threshold = Some(threshold);
    }
    // Offline calibration doesn't make HTTP requests. Screenshots never leave loopback.
    if !matches!(options.mode, Mode::ListWindows) {
        validate_vlm_endpoint(&options.vlm.endpoint)?;
    }
    Ok(options)
}

fn parse_lobby_size(value: &str) -> Result<(u32, u32), String> {
    let invalid = "--lobby-size requires positive WIDTHxHEIGHT";
    let mut parts = value.trim().split(['x', 'X', '×']);
    let (Some(width), Some(height), None) = (parts.next(), parts.next(), parts.next()) else {
        return Err(invalid.into());
    };
    let width: u32 = width.trim().parse().map_err(|_| invalid.to_string())?;
    let height: u32 = height.trim().parse().map_err(|_| invalid.to_string())?;
    if width == 0 || height == 0 {
        return Err(invalid.into());
    }
    Ok((width, height))
}

fn parse_hwnd(value: &str) -> Result<usize, String> {
    let value = value.trim();
    let parsed = if let Some(hex) = value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
    {
        usize::from_str_radix(hex, 16)
    } else {
        value.parse()
    };
    parsed.map_err(|_| {
        "invalid window HWND; use a positive decimal value or 0x-prefixed hexadecimal".into()
    })
}

/// Product endpoint policy; library transports retain arbitrary loopback test ports.
pub fn validate_vlm_endpoint(endpoint: &str) -> Result<(), String> {
    let parsed = ingest::vlm::validate_endpoint(endpoint)
        .map_err(|error| format!("refusing COINPOKER_VLM_ENDPOINT: {error}"))?;
    if parsed.port() != Some(18090) || parsed.path() != "/v1/laya/predict" {
        return Err("refusing COINPOKER_VLM_ENDPOINT: use the canonical loopback port 18090 and /v1/laya/predict (default http://127.0.0.1:18090/v1/laya/predict); alternate or retired product ports are not supported".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wager_registry_is_explicit_private_capture_only_and_not_an_environment_activation() {
        let defaults = parse([], |name| {
            (name == "COINPOKER_WAGER_REGISTRY").then(|| ".local/should-not-activate.json".into())
        })
        .unwrap();
        assert!(defaults.wager_registry.is_none());
        assert!(
            parse(["--stdin".into()], |_| Some(".local/ignored.json".into()))
                .unwrap()
                .wager_registry
                .is_none()
        );
        let valid = parse(
            ["--wager-registry", ".local/data/v2/wager.json"].map(String::from),
            |_| None,
        )
        .unwrap();
        assert_eq!(
            valid.wager_registry.as_deref(),
            Some(".local/data/v2/wager.json")
        );
        for mode in ["--stdin", "--doctor", "--list-windows"] {
            assert!(parse(
                [mode, "--wager-registry", ".local/v2.json"].map(String::from),
                |_| None
            )
            .is_err());
        }
        for path in [
            "models/approved.json",
            ".local/../secret.json",
            "C:\\data.json",
            "https://example.com/data.json",
            ".local/data.json:stream",
            ".local/data.txt",
        ] {
            assert!(parse(["--wager-registry", path].map(String::from), |_| None).is_err());
        }
        assert!(parse(
            [
                "--wager-registry",
                ".local/a.json",
                "--wager-registry",
                ".local/b.json"
            ]
            .map(String::from),
            |_| None
        )
        .is_err());
    }
    #[test]
    fn recorder_config_is_opt_in_cli_only_and_reports_bounded_defaults() {
        let default = parse(std::iter::empty(), |_| None).unwrap();
        assert!(default.recording.is_none());
        let ignored_env = parse(std::iter::empty(), |key| {
            key.starts_with("COINPOKER_RECORD_")
                .then(|| "unsafe".into())
        })
        .unwrap();
        assert!(ignored_env.recording.is_none());
        for directory in [".local/captures", ".local\\captures"] {
            let options = parse(["--record-dir", directory].map(String::from), |_| None).unwrap();
            assert_eq!(options.recording, Some(RecorderConfig::default()));
        }
        let options = parse(
            [
                "--record-dir",
                ".local/captures",
                "--record-max-frames",
                "20",
                "--record-max-bytes",
                "4096",
                "--record-interval-ms",
                "1000",
            ]
            .map(String::from),
            |_| None,
        )
        .unwrap();
        assert_eq!(
            options.recording,
            Some(RecorderConfig {
                max_frames: 20,
                max_bytes: 4096,
                interval_ms: 1000
            })
        );
        for flag in RECORD_FLAGS {
            assert!(USAGE.contains(flag));
        }
    }

    #[test]
    fn recorder_config_refuses_other_modes_paths_duplicates_and_unbounded_limits() {
        for directory in [
            ".",
            "captures",
            "public/captures",
            ".local/captures/session",
            ".local/../public",
            ".local/captures/../captures",
            ".local//captures",
            "C:\\captures",
            "C:\\private\\.local\\captures",
            "\\\\server\\captures",
        ] {
            assert!(
                parse(["--record-dir", directory].map(String::from), |_| None).is_err(),
                "{directory}"
            );
        }
        for mode in ["--stdin", "--doctor", "--list-windows"] {
            assert!(parse(
                [mode, "--record-dir", ".local/captures"].map(String::from),
                |_| None
            )
            .is_err());
        }
        assert!(parse(
            [
                "--evaluate",
                "synthetic.json",
                "--record-dir",
                ".local/captures"
            ]
            .map(String::from),
            |_| None
        )
        .is_err());
        assert!(parse(["--record-max-frames", "1"].map(String::from), |_| None).is_err());
        assert!(parse(
            [
                "--record-dir",
                ".local/captures",
                "--record-dir",
                ".local/captures"
            ]
            .map(String::from),
            |_| None
        )
        .is_err());
        for (flag, values) in [
            ("--record-max-frames", ["0", "20001", "-1", "NaN"]),
            (
                "--record-max-bytes",
                ["0", "2147483649", "-1", "18446744073709551616"],
            ),
            ("--record-interval-ms", ["0", "249", "60001", "NaN"]),
        ] {
            for value in values {
                assert!(
                    parse(
                        ["--record-dir", ".local/captures", flag, value].map(String::from),
                        |_| None
                    )
                    .is_err(),
                    "{flag} {value}"
                );
            }
        }
    }

    #[test]
    fn cli_overrides_environment_and_defaults() {
        let cfg = parse(
            ["--exe-name", "CoinPoker.exe", "--stable-ms", "700"].map(String::from),
            |key| match key {
                "COINPOKER_EXE_NAME" => Some("other.exe".into()),
                "COINPOKER_STABLE_MS" => Some("400".into()),
                _ => None,
            },
        )
        .unwrap();
        assert_eq!(cfg.discovery.exe_name.as_deref(), Some("CoinPoker.exe"));
        assert_eq!(cfg.runtime.stability.stable_ms, 700);
    }
    #[test]
    fn invalid_bounds_nan_and_duplicate_flags_are_rejected() {
        for args in [
            vec!["--stable-ms", "0"],
            vec!["--channel-delta", "255"],
            vec!["--local-fraction", "NaN"],
            vec!["--pid", "-2"],
            vec!["--window-hwnd", "0"],
            vec!["--window-hwnd", "0xGG"],
            vec!["--pid", "1", "--pid", "2"],
        ] {
            assert!(parse(args.into_iter().map(String::from), |_| None).is_err());
        }
    }
    #[test]
    fn lobby_size_is_a_positive_pair() {
        let cfg = parse(
            ["--lobby-size", "1280x1032", "--lobby-title", "Lobby"].map(String::from),
            |_| None,
        )
        .unwrap();
        assert_eq!(cfg.discovery.lobby_width, Some(1280));
        assert_eq!(cfg.discovery.lobby_height, Some(1032));
        let from_env = parse(["--exe-name".into(), "Client.exe".into()], |key| {
            (key == "COINPOKER_LOBBY_SIZE").then(|| "800X613".into())
        })
        .unwrap();
        assert_eq!(
            (
                from_env.discovery.lobby_width,
                from_env.discovery.lobby_height
            ),
            (Some(800), Some(613))
        );
        for bad in ["1280", "0x1032", "1280x0", "1280x1032x1", "x1032"] {
            assert!(
                parse(["--lobby-size", bad].map(String::from), |_| None).is_err(),
                "{bad}"
            );
        }
    }
    #[test]
    fn hwnd_accepts_decimal_and_hexadecimal() {
        for value in ["42", "0x2a", "0X2A"] {
            let cfg = parse(["--window-hwnd", value].map(String::from), |_| None).unwrap();
            assert_eq!(cfg.discovery.window_hwnd, Some(42));
        }
    }
    #[test]
    fn stdin_ignores_capture_environment() {
        assert!(parse(["--stdin".into()], |_| Some("bad value".into())).is_ok());
    }
    #[test]
    fn laya_defaults_apply_without_configuration() {
        let options = parse(std::iter::empty(), |_| None).unwrap();
        assert_eq!(options.mode, Mode::Capture);
        assert_eq!(options.vlm, VlmConfig::default());
        assert_eq!(
            options.vlm.endpoint,
            "http://127.0.0.1:18090/v1/laya/predict"
        );
        assert_eq!(options.vlm.model, "coinpoker-laya-vision");
        assert_eq!(options.vlm.timeout_secs, 5);
        assert_eq!(options.runtime.decision_budget_ms, 5_000);
        assert_eq!(options.runtime.max_frame_age_ms, 8_000);
        assert_eq!(options.vlm.threshold, None);
        assert!(USAGE.contains("--laya-threshold"));
        assert!(!USAGE.contains("allow-remote"));
    }

    #[test]
    fn laya_threshold_is_bounded_and_overridable_by_cli() {
        let options = parse(["--laya-threshold", "0.9"].map(String::from), |_| None).unwrap();
        assert_eq!(options.vlm.threshold, Some(0.9));
        let options = parse(["--laya-threshold", "0.85"].map(String::from), |key| {
            (key == "COINPOKER_LAYA_THRESHOLD").then(|| "0.95".into())
        })
        .unwrap();
        assert_eq!(options.vlm.threshold, Some(0.85));
        let from_env = parse(std::iter::empty(), |key| {
            (key == "COINPOKER_LAYA_THRESHOLD").then(|| "0.99".into())
        })
        .unwrap();
        assert_eq!(from_env.vlm.threshold, Some(0.99));
        for bad in ["0.79", "0.995", "1", "0", "NaN", "inf", "-0.9", "high"] {
            assert!(
                parse(["--laya-threshold", bad].map(String::from), |_| None).is_err(),
                "{bad}"
            );
        }
        for bad in ["0", "121"] {
            assert!(parse(["--timeout-secs", bad].map(String::from), |_| None).is_err());
        }
    }

    #[test]
    fn removed_remote_opt_in_is_a_usage_error_and_remote_is_always_refused() {
        let error = parse(["--allow-remote-vlm".to_string()], |_| None).unwrap_err();
        assert!(error.contains("unknown option"), "{error}");
        for mode in [None, Some("--doctor"), Some("--evaluate")] {
            let mut args: Vec<String> = mode.into_iter().map(String::from).collect();
            if args.first().is_some_and(|m| m == "--evaluate") {
                args.push("manifest.json".into());
            }
            args.extend(
                ["--vlm-endpoint", "https://example.com/v1/laya/predict"].map(String::from),
            );
            assert!(
                parse(args, |key| {
                    (key == "COINPOKER_ALLOW_REMOTE_VLM").then(|| "1".into())
                })
                .is_err(),
                "{mode:?}"
            );
        }
        assert!(parse(std::iter::empty(), |key| {
            (key == "COINPOKER_VLM_ENDPOINT").then(|| "http://192.168.1.2/v1/laya/predict".into())
        })
        .is_err());
        // Offline window listing makes no HTTP requests and skips the endpoint check.
        assert!(parse(
            ["--list-windows", "--vlm-endpoint", "https://example.com/"].map(String::from),
            |_| None
        )
        .is_ok());
    }

    #[test]
    fn total_decision_budget_is_independent_bounded_and_cli_overridable() {
        let options = parse(
            [
                "--decision-budget-ms",
                "3000",
                "--timeout-secs",
                "120",
                "--max-frame-age-ms",
                "8000",
            ]
            .map(String::from),
            |key| (key == "COINPOKER_DECISION_BUDGET_MS").then(|| "4000".into()),
        )
        .unwrap();
        assert_eq!(options.runtime.decision_budget_ms, 3_000);
        assert_eq!(options.vlm.timeout_secs, 120);
        assert_eq!(options.runtime.max_frame_age_ms, 8_000);
        let from_env = parse(std::iter::empty(), |key| {
            (key == "COINPOKER_DECISION_BUDGET_MS").then(|| "2500".into())
        })
        .unwrap();
        assert_eq!(from_env.runtime.decision_budget_ms, 2_500);
        for value in ["0", "499", "5001", "8000", "NaN"] {
            assert!(parse(["--decision-budget-ms", value].map(String::from), |_| None).is_err());
        }
    }

    #[test]
    fn product_cli_rejects_retired_alternate_ports_and_wrong_routes_before_io() {
        for endpoint in [
            "http://127.0.0.1:8080/v1/laya/predict",
            "http://localhost:18080/v1/laya/predict",
            "http://127.0.0.1:0/v1/laya/predict",
            "http://127.0.0.1/v1/laya/predict",
            "http://127.0.0.1:18090/v1/chat/completions",
        ] {
            let error = validate_vlm_endpoint(endpoint).unwrap_err();
            assert!(error.contains("18090"), "{error}");
            assert!(parse(
                ["--doctor", "--vlm-endpoint", endpoint].map(String::from),
                |_| None
            )
            .is_err());
            assert!(parse(std::iter::empty(), |key| {
                (key == "COINPOKER_VLM_ENDPOINT").then(|| endpoint.into())
            })
            .is_err());
        }
    }
}
