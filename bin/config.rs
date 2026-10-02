use ingest::discovery::DiscoveryConfig;
use ingest::runtime::RuntimeConfig;
use ingest::vlm::VlmConfig;
use std::collections::HashMap;

pub const USAGE: &str = "Usage: coinpoker [OPTION] [CONFIGURATION]\n\n\
  (no option)        Run the Windows capture pipeline\n\
  --stdin            Read legacy GameState JSON lines (all platforms)\n\
  --list-windows     Print application/window identity JSON lines; no pixels\n\
  --doctor           Run local installation/model/capture diagnostics\n\
  --evaluate PATH    Evaluate a version-2 local visual fixture manifest\n\
  --ui               Rejected: no interactive feed is implemented (exit 2)\n\
  -h, --help         Print this help\n\n\
Configuration (CLI > nonempty environment > defaults):\n\
  --exe-name NAME             COINPOKER_EXE_NAME (exact; calibrate first)\n\
  --pid PID                   COINPOKER_PID (optional restriction)\n\
  --window-hwnd HWND          COINPOKER_WINDOW_HWND (hex or decimal; hard pin)\n\
  --table-title TEXT          COINPOKER_WINDOW_TITLE (calibrated substring)\n\
  --lobby-title TEXT          COINPOKER_LOBBY_TITLE (lobby veto substring)\n\
  --lobby-size WIDTHxHEIGHT   COINPOKER_LOBBY_SIZE (observed lobby size)\n\
  --vlm-endpoint URL          COINPOKER_VLM_ENDPOINT (loopback by default)\n\
  --vlm-model NAME            COINPOKER_VLM_MODEL (local server model name)\n\
  --allow-remote-vlm          COINPOKER_ALLOW_REMOTE_VLM=1 (HTTPS only)\n\
  --timeout-secs N            COINPOKER_VLM_TIMEOUT_SECS (1..120)\n\
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
  --sample-stride N           COINPOKER_SAMPLE_STRIDE (1..64)\n";

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
}

const FLAGS: &[(&str, &str)] = &[
    ("--exe-name", "COINPOKER_EXE_NAME"),
    ("--pid", "COINPOKER_PID"),
    ("--window-hwnd", "COINPOKER_WINDOW_HWND"),
    ("--table-title", "COINPOKER_WINDOW_TITLE"),
    ("--lobby-title", "COINPOKER_LOBBY_TITLE"),
    ("--lobby-size", "COINPOKER_LOBBY_SIZE"),
    ("--vlm-endpoint", "COINPOKER_VLM_ENDPOINT"),
    ("--vlm-model", "COINPOKER_VLM_MODEL"),
    ("--timeout-secs", "COINPOKER_VLM_TIMEOUT_SECS"),
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
    let mut allow_remote = false;
    while let Some(arg) = args.next() {
        let next_mode = match arg.as_str() {
            "--stdin" => Some(Mode::Stdin), "--list-windows" => Some(Mode::ListWindows),
            "--doctor" => Some(Mode::Doctor),
            "--help" | "-h" => Some(Mode::Help),
            "--evaluate" => Some(Mode::Evaluate(args.next().ok_or("--evaluate requires a manifest path")?)),
            "--ui" => return Err("--ui is unavailable: the interactive feed is not implemented; use --stdin for JSON-lines output".into()),
            "--allow-remote-vlm" => { allow_remote = true; None },
            _ => {
                if let Some((flag, _)) = FLAGS.iter().find(|(flag, _)| *flag == arg) {
                    let value = args.next().filter(|v| !v.trim().is_empty() && !v.starts_with("--"))
                        .ok_or_else(|| format!("{flag} requires a nonempty value"))?;
                    if overrides.insert(*flag, value).is_some() { return Err(format!("duplicate option {flag}")); }
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
    };
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
    options.runtime.validate()?;
    if !(1..=120).contains(&options.vlm.timeout_secs) {
        return Err("timeout must be 1..120 seconds".into());
    }
    let allowed = allow_remote
        || env("COINPOKER_ALLOW_REMOTE_VLM")
            .is_some_and(|v| v == "1" || v.eq_ignore_ascii_case("true"));
    options.vlm.allow_remote = allowed && matches!(options.mode, Mode::Capture);
    // Offline calibration doesn't make HTTP requests. Doctor/evaluation NEVER opt in to remote screenshots.
    if !matches!(options.mode, Mode::ListWindows) {
        validate_vlm_endpoint(&options.vlm.endpoint, options.vlm.allow_remote)?;
    }
    Ok(options)
}

fn parse_lobby_size(value: &str) -> Result<(u32, u32), String> {
    let invalid = "--lobby-size requires positive WIDTHxHEIGHT";
    let mut parts = value
        .trim()
        .split(|c: char| c == 'x' || c == 'X' || c == '×');
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

pub fn validate_vlm_endpoint(endpoint: &str, remote_allowed: bool) -> Result<(), String> {
    let parsed = url::Url::parse(endpoint).map_err(|_| "invalid COINPOKER_VLM_ENDPOINT")?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err("VLM endpoint must use HTTP or HTTPS".into());
    }
    if !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.fragment().is_some()
        || parsed.query().is_some()
    {
        return Err(
            "VLM endpoint must not contain credentials, query strings, or fragments".into(),
        );
    }
    let loopback = match parsed.host() {
        Some(url::Host::Domain(host)) => host.eq_ignore_ascii_case("localhost"),
        Some(url::Host::Ipv4(address)) => address.is_loopback(),
        Some(url::Host::Ipv6(address)) => address.is_loopback(),
        None => return Err("VLM endpoint must include a host".into()),
    };
    if loopback {
        return Ok(());
    }
    if !remote_allowed {
        return Err("refusing non-loopback COINPOKER_VLM_ENDPOINT; capture requires COINPOKER_ALLOW_REMOTE_VLM=1 after reviewing privacy; doctor/evaluation are local-only".into());
    }
    if parsed.scheme() != "https" {
        return Err("remote VLM endpoints must use HTTPS".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
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
    fn diagnostics_cannot_opt_in_to_remote_data() {
        assert!(parse(
            [
                "--doctor",
                "--allow-remote-vlm",
                "--vlm-endpoint",
                "https://example.com/v1/chat/completions"
            ]
            .map(String::from),
            |_| None
        )
        .is_err());
    }

    #[test]
    fn capture_remote_opt_in_reaches_backend_config() {
        let endpoint = "https://example.com/v1/chat/completions";
        assert!(parse(["--vlm-endpoint", endpoint].map(String::from), |_| None).is_err());
        let options = parse(
            ["--allow-remote-vlm", "--vlm-endpoint", endpoint].map(String::from),
            |_| None,
        )
        .expect("explicit HTTPS opt-in");
        assert!(options.vlm.allow_remote);
        assert!(parse(
            [
                "--allow-remote-vlm",
                "--vlm-endpoint",
                "http://example.com/v1/chat/completions"
            ]
            .map(String::from),
            |_| None
        )
        .is_err());
    }
}
