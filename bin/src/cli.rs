//! Command-line interface: usage text, modes, and argument parsing.

/// The binary's usage text.
pub const USAGE: &str = "Usage: coinpoker [OPTION]\n\
\n\
Options:\n\
  (no option)      Run the macOS capture pipeline\n\
  --stdin          Read GameState JSON lines from stdin\n\
  --list-windows   List windows available for capture\n\
  --ui             Reserved; exits 2 because the interactive feed is not implemented\n\
  -h, --help       Print this help\n";

/// The execution mode selected by the command line.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// Headless capture pipeline (macOS).
    Capture,
    /// Read `GameState` JSON lines from stdin.
    Stdin,
    /// List capture candidates for calibration.
    ListWindows,
    /// Print the usage text.
    Help,
}

/// Parse the command-line arguments into a [`Mode`].
///
/// # Errors
///
/// Returns a human-readable message for unknown or unexpected arguments;
/// the caller prints it alongside [`USAGE`] and exits with status 2.
pub fn parse_args(args: impl IntoIterator<Item = impl Into<String>>) -> Result<Mode, String> {
    let args: Vec<String> = args.into_iter().map(Into::into).collect();
    match args.as_slice() {
        [] => Ok(Mode::Capture),
        [arg] if arg == "--stdin" => Ok(Mode::Stdin),
        [arg] if arg == "--list-windows" => Ok(Mode::ListWindows),
        [arg] if arg == "--help" || arg == "-h" => Ok(Mode::Help),
        // Exit status 2 is deliberate: the option is recognized but its live
        // pipeline-to-window feed has not been implemented.
        [arg] if arg == "--ui" => Err(
            "--ui is unavailable: the interactive feed is not implemented; use --stdin for JSON-lines output"
                .to_string(),
        ),
        [arg] => Err(format!("unknown option: {arg}")),
        [_, extra, ..] => Err(format!("unexpected extra argument: {extra}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_arguments_selects_capture_mode() {
        assert_eq!(parse_args(Vec::<String>::new()), Ok(Mode::Capture));
    }

    #[test]
    fn known_flags_select_their_modes() {
        assert_eq!(parse_args(["--stdin"]), Ok(Mode::Stdin));
        assert_eq!(parse_args(["--list-windows"]), Ok(Mode::ListWindows));
        assert_eq!(parse_args(["--help"]), Ok(Mode::Help));
        assert_eq!(parse_args(["-h"]), Ok(Mode::Help));
    }

    #[test]
    fn ui_flag_reports_the_reserved_exit_status() {
        let error = parse_args(["--ui"]).expect_err("reserved mode");
        assert!(error.contains("--ui is unavailable"));
    }

    #[test]
    fn unknown_and_extra_arguments_are_rejected() {
        assert!(parse_args(["--frobnicate"]).is_err());
        assert!(parse_args(["--stdin", "--stdin"]).is_err());
    }
}
