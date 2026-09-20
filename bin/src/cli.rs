//! Command-line interface: usage text, modes, and argument parsing.

use ui::overlay::{OverlaySettings, PositionPreset};

/// The binary's usage text.
pub const USAGE: &str = "Usage: coinpoker [OPTION] [OVERLAY OPTION]\n\
\n\
Options:\n\
  (no option)      Run the macOS capture pipeline\n\
  --stdin          Read GameState JSON lines from stdin\n\
  --list-windows   List windows available for capture\n\
  --ui             Run the live pipeline with a desktop study overlay\n\
\n\
Overlay options (require --ui):\n\
  --overlay-opacity <0.0..=1.0>\n\
                   Set overlay opacity (default: 0.9)\n\
  --overlay-position <right|left|above|below>\n\
                   Position the overlay beside the table (default: right)\n\
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
    /// Live pipeline with a desktop study overlay.
    Ui,
    /// Print the usage text.
    Help,
}

/// Fully parsed command-line settings.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CliOptions {
    pub mode: Mode,
    pub overlay_settings: OverlaySettings,
}

/// Parse the command-line arguments into a [`Mode`].
///
/// # Errors
///
/// Returns a human-readable message for unknown or unexpected arguments;
/// the caller prints it alongside [`USAGE`] and exits with status 2.
pub fn parse_args(args: impl IntoIterator<Item = impl Into<String>>) -> Result<Mode, String> {
    parse_options(args).map(|options| options.mode)
}

/// Parse the command-line arguments and overlay settings.
///
/// # Errors
///
/// Returns a human-readable message for malformed settings, unrecognized
/// options, or overlay settings used without [`Mode::Ui`].
pub fn parse_options(
    args: impl IntoIterator<Item = impl Into<String>>,
) -> Result<CliOptions, String> {
    let args: Vec<String> = args.into_iter().map(Into::into).collect();
    let mut mode = None;
    let mut overlay_settings = OverlaySettings::default();
    let mut has_overlay_option = false;
    let mut index = 0;

    while index < args.len() {
        let argument = &args[index];
        match argument.as_str() {
            "--stdin" => select_mode(&mut mode, Mode::Stdin)?,
            "--list-windows" => select_mode(&mut mode, Mode::ListWindows)?,
            "--ui" => select_mode(&mut mode, Mode::Ui)?,
            "--help" | "-h" => select_mode(&mut mode, Mode::Help)?,
            "--overlay-opacity" => {
                has_overlay_option = true;
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| "--overlay-opacity requires a value".to_string())?;
                overlay_settings.opacity = value.parse::<f32>().map_err(|_| {
                    format!("invalid --overlay-opacity value {value:?}; expected 0.0 through 1.0")
                })?;
                index += 1;
            }
            "--overlay-position" => {
                has_overlay_option = true;
                let value = args
                    .get(index + 1)
                    .ok_or_else(|| "--overlay-position requires a value".to_string())?;
                overlay_settings.position = PositionPreset::parse(value)?;
                index += 1;
            }
            _ if argument.starts_with('-') => return Err(format!("unknown option: {argument}")),
            _ => return Err(format!("unexpected argument: {argument}")),
        }
        index += 1;
    }

    let mode = mode.unwrap_or(Mode::Capture);
    if has_overlay_option && mode != Mode::Ui {
        return Err("overlay options require --ui".to_string());
    }
    overlay_settings.validate()?;
    Ok(CliOptions {
        mode,
        overlay_settings,
    })
}

fn select_mode(selected: &mut Option<Mode>, mode: Mode) -> Result<(), String> {
    if selected.replace(mode).is_some() {
        return Err("only one execution mode may be selected".to_string());
    }
    Ok(())
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
        assert_eq!(parse_args(["--ui"]), Ok(Mode::Ui));
        assert_eq!(parse_args(["--help"]), Ok(Mode::Help));
        assert_eq!(parse_args(["-h"]), Ok(Mode::Help));
    }

    #[test]
    fn ui_options_override_validated_defaults() {
        let options = parse_options([
            "--ui",
            "--overlay-opacity",
            "0.5",
            "--overlay-position",
            "left",
        ])
        .expect("valid UI options");
        assert_eq!(options.mode, Mode::Ui);
        assert_eq!(options.overlay_settings.opacity, 0.5);
        assert_eq!(options.overlay_settings.position, PositionPreset::Left);
    }

    #[test]
    fn unknown_and_extra_arguments_are_rejected() {
        assert!(parse_args(["--frobnicate"]).is_err());
        assert!(parse_args(["--stdin", "--stdin"]).is_err());
        assert!(parse_args(["--ui", "--overlay-opacity", "1.1"]).is_err());
        assert!(parse_args(["--stdin", "--overlay-position", "left"]).is_err());
    }
}
