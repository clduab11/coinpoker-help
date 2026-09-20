//! Environment-driven configuration for capture and VLM endpoints.

use ingest::capture::CaptureConfig;
use ingest::vlm::VlmConfig;

/// Build the window-capture configuration from the environment.
///
/// `COINPOKER_WINDOW_TITLE` and `COINPOKER_APP_NAME` override the default
/// CoinPoker selectors; empty values are ignored.
pub fn capture_config_from_env() -> CaptureConfig {
    let mut config = CaptureConfig::default();
    if let Ok(title) = std::env::var("COINPOKER_WINDOW_TITLE") {
        if !title.trim().is_empty() {
            config.window_title = title;
        }
    }
    if let Ok(app_name) = std::env::var("COINPOKER_APP_NAME") {
        if !app_name.trim().is_empty() {
            config.app_name = app_name;
        }
    }
    config
}

/// Build the VLM client configuration from the environment.
///
/// `COINPOKER_VLM_ENDPOINT` overrides the local server base URL and
/// `COINPOKER_VLM_MODEL` the model identifier. Non-loopback endpoints are
/// refused unless `COINPOKER_ALLOW_REMOTE_VLM` is explicitly enabled and
/// the endpoint uses HTTPS.
///
/// # Errors
///
/// Returns a human-readable message when the endpoint is missing, invalid,
/// or violates the loopback/HTTPS policy.
pub fn vlm_config_from_env() -> Result<VlmConfig, String> {
    let mut config = VlmConfig::default();
    if let Ok(endpoint) = std::env::var("COINPOKER_VLM_ENDPOINT") {
        if !endpoint.trim().is_empty() {
            config.base_url = endpoint;
        }
    }
    if let Ok(model) = std::env::var("COINPOKER_VLM_MODEL") {
        if !model.trim().is_empty() {
            config.model = model;
        }
    }

    let remote_allowed = std::env::var("COINPOKER_ALLOW_REMOTE_VLM")
        .map(|value| value == "1" || value.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    validate_vlm_endpoint(&config.base_url, remote_allowed)?;

    Ok(config)
}

/// Enforce the VLM endpoint policy.
///
/// Loopback endpoints are always allowed. Remote endpoints require an
/// explicit opt-in and HTTPS, because frames are screenshots of the
/// player's screen.
///
/// # Errors
///
/// Returns a human-readable message describing the violated policy.
pub fn validate_vlm_endpoint(endpoint: &str, remote_allowed: bool) -> Result<(), String> {
    let parsed = url::Url::parse(endpoint)
        .map_err(|error| format!("invalid COINPOKER_VLM_ENDPOINT: {error}"))?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err("VLM endpoint must use HTTP or HTTPS".to_string());
    }
    let loopback = match parsed.host() {
        Some(url::Host::Domain(host)) => host.eq_ignore_ascii_case("localhost"),
        Some(url::Host::Ipv4(address)) => address.is_loopback(),
        Some(url::Host::Ipv6(address)) => address.is_loopback(),
        None => return Err("VLM endpoint must include a host".to_string()),
    };

    if loopback {
        return Ok(());
    }
    if !remote_allowed {
        return Err(
            "refusing non-loopback COINPOKER_VLM_ENDPOINT; set COINPOKER_ALLOW_REMOTE_VLM=1 only after reviewing screenshot privacy"
                .to_string(),
        );
    }
    if parsed.scheme() != "https" {
        return Err("remote VLM endpoints must use HTTPS".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_vlm_endpoints_are_allowed_without_opt_in() {
        for endpoint in [
            "http://127.0.0.1:8080/v1/chat/completions",
            "http://localhost:8080/v1/chat/completions",
            "https://[::1]:8443/v1/chat/completions",
        ] {
            validate_vlm_endpoint(endpoint, false).expect("loopback endpoint");
        }
    }

    #[test]
    fn remote_vlm_endpoint_requires_opt_in_and_https() {
        let endpoint = "https://vlm.example.com/v1/chat/completions";
        assert!(validate_vlm_endpoint(endpoint, false).is_err());
        validate_vlm_endpoint(endpoint, true).expect("opted-in HTTPS endpoint");
        assert!(validate_vlm_endpoint("http://vlm.example.com/v1", true).is_err());
    }

    #[test]
    fn deceptive_or_invalid_hosts_are_rejected() {
        assert!(validate_vlm_endpoint("http://localhost:8080@evil.example/v1", false).is_err());
        assert!(validate_vlm_endpoint("file:///tmp/socket", true).is_err());
        assert!(validate_vlm_endpoint("not a URL", true).is_err());
    }
}
