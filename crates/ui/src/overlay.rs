//! Overlay event model and headless state transitions.
//!
//! The live capture loop feeds the overlay through a channel of
//! [`OverlayEvent`]s, and [`OverlayState`] applies them without any GPU or
//! windowing dependency. Keeping the transition logic here — separate from
//! the `desktop`-gated egui rendering in [`crate::app`] — makes every state
//! transition unit-testable on any host.

use crate::widgets::DecisionView;

/// Side of the table where the overlay is placed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PositionPreset {
    Right,
    Left,
    Above,
    Below,
}

impl PositionPreset {
    /// Parse a CLI-friendly position name.
    pub fn parse(value: &str) -> Result<Self, String> {
        match value {
            "right" => Ok(Self::Right),
            "left" => Ok(Self::Left),
            "above" => Ok(Self::Above),
            "below" => Ok(Self::Below),
            _ => Err(format!(
                "invalid overlay position {value:?}; expected right, left, above, or below"
            )),
        }
    }
}

/// User-configurable presentation settings for the study overlay.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct OverlaySettings {
    /// Fractional opacity applied to every rendered overlay element.
    pub opacity: f32,
    /// Preferred placement relative to the captured table window.
    pub position: PositionPreset,
}

impl Default for OverlaySettings {
    fn default() -> Self {
        Self {
            opacity: 0.9,
            position: PositionPreset::Right,
        }
    }
}

impl OverlaySettings {
    /// Validate settings received from a CLI or other untrusted input.
    pub fn validate(&self) -> Result<(), String> {
        if !self.opacity.is_finite() || !(0.0..=1.0).contains(&self.opacity) {
            return Err("overlay opacity must be a finite number between 0.0 and 1.0".to_string());
        }
        Ok(())
    }
}

/// The captured table window's on-screen bounds in display points.
#[derive(Debug, Clone, Copy, PartialEq, serde::Serialize)]
pub struct TableBounds {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// An event sent from the live capture loop to the overlay.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(tag = "event", content = "payload", rename_all = "snake_case")]
pub enum OverlayEvent {
    /// A decision to display.
    Decision(DecisionView),
    /// Clear the displayed decision (it is no longer actionable).
    Clear(String),
    /// The table window moved or resized.
    Position(TableBounds),
}

/// The overlay's display state.
#[derive(Debug, Default, Clone, PartialEq)]
pub struct OverlayState {
    view: Option<DecisionView>,
    table: Option<TableBounds>,
}

impl OverlayState {
    pub fn new() -> Self {
        Self::default()
    }

    /// The decision currently on display, if any.
    pub fn view(&self) -> Option<&DecisionView> {
        self.view.as_ref()
    }

    /// The most recently observed table bounds, if any.
    pub fn table(&self) -> Option<TableBounds> {
        self.table
    }

    /// Apply one event, updating the display state.
    pub fn apply(&mut self, event: &OverlayEvent) {
        match event {
            OverlayEvent::Decision(view) => self.view = Some(view.clone()),
            OverlayEvent::Clear(_) => self.view = None,
            OverlayEvent::Position(bounds) => self.table = Some(*bounds),
        }
    }
}

/// Default overlay panel size in points.
pub const PANEL_SIZE: (f32, f32) = (320.0, 420.0);

/// Margin kept between the table window and the overlay panel.
pub const PANEL_MARGIN: f32 = 24.0;

/// Desired top-left position for the panel: to the right of the table and
/// vertically centered, clamped to non-negative coordinates.
pub fn panel_position(table: &TableBounds) -> (f32, f32) {
    panel_position_for(table, PositionPreset::Right)
}

/// Desired top-left position for the panel using a chosen relative placement.
pub fn panel_position_for(table: &TableBounds, position: PositionPreset) -> (f32, f32) {
    let centered_x = table.x + (table.width - f64::from(PANEL_SIZE.0)) / 2.0;
    let centered_y = table.y + (table.height - f64::from(PANEL_SIZE.1)) / 2.0;
    let (x, y) = match position {
        PositionPreset::Right => (table.x + table.width + f64::from(PANEL_MARGIN), centered_y),
        PositionPreset::Left => (
            table.x - f64::from(PANEL_SIZE.0) - f64::from(PANEL_MARGIN),
            centered_y,
        ),
        PositionPreset::Above => (
            centered_x,
            table.y - f64::from(PANEL_SIZE.1) - f64::from(PANEL_MARGIN),
        ),
        PositionPreset::Below => (centered_x, table.y + table.height + f64::from(PANEL_MARGIN)),
    };
    (x.max(0.0) as f32, y.max(0.0) as f32)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decision() -> DecisionView {
        DecisionView {
            action: "call".to_string(),
            amount: 0,
            sizing_provenance: None,
            ev: 0.42,
            pot_odds: Some(0.238),
            equity: 0.412,
            break_even: Some(0.238),
            opponent: Some("lag".to_string()),
            confidence: Some(0.82),
        }
    }

    fn bounds(x: f64, y: f64, width: f64, height: f64) -> TableBounds {
        TableBounds {
            x,
            y,
            width,
            height,
        }
    }

    #[test]
    fn state_starts_empty() {
        let state = OverlayState::new();
        assert!(state.view().is_none());
        assert!(state.table().is_none());
    }

    #[test]
    fn decision_sets_and_clear_clears_the_view() {
        let mut state = OverlayState::new();
        state.apply(&OverlayEvent::Decision(decision()));
        assert!(state.view().is_some());

        state.apply(&OverlayEvent::Clear("action-not-required".to_string()));
        assert!(state.view().is_none());
    }

    #[test]
    fn position_sets_the_table_and_survives_a_clear() {
        let mut state = OverlayState::new();
        state.apply(&OverlayEvent::Position(bounds(10.0, 20.0, 800.0, 600.0)));
        assert_eq!(state.table(), Some(bounds(10.0, 20.0, 800.0, 600.0)));

        state.apply(&OverlayEvent::Decision(decision()));
        state.apply(&OverlayEvent::Clear("action-not-required".to_string()));
        assert!(state.view().is_none());
        assert_eq!(state.table(), Some(bounds(10.0, 20.0, 800.0, 600.0)));
    }

    #[test]
    fn a_new_decision_replaces_the_previous_one() {
        let mut state = OverlayState::new();
        state.apply(&OverlayEvent::Decision(decision()));

        let mut raised = decision();
        raised.action = "raise".to_string();
        raised.amount = 750;
        state.apply(&OverlayEvent::Decision(raised.clone()));

        assert_eq!(state.view(), Some(&raised));
    }

    #[test]
    fn panel_position_offsets_right_and_centers_vertically() {
        let table = bounds(100.0, 200.0, 800.0, 600.0);
        let (x, y) = panel_position(&table);
        assert_eq!(x, 100.0 + 800.0 + f64::from(PANEL_MARGIN) as f32);
        assert!((y - (200.0 + (600.0 - 420.0) / 2.0) as f32).abs() < 1e-6);
    }

    #[test]
    fn panel_position_clamps_negative_coordinates() {
        let table = bounds(-2000.0, -2000.0, 800.0, 600.0);
        let (x, y) = panel_position(&table);
        assert_eq!(x, 0.0);
        assert_eq!(y, 0.0);
    }

    #[test]
    fn position_presets_place_the_panel_on_each_requested_side() {
        let table = bounds(500.0, 400.0, 800.0, 600.0);
        assert_eq!(
            panel_position_for(&table, PositionPreset::Left),
            (156.0, 490.0)
        );
        assert_eq!(
            panel_position_for(&table, PositionPreset::Above),
            (740.0, 0.0)
        );
        assert_eq!(
            panel_position_for(&table, PositionPreset::Below),
            (740.0, 1024.0)
        );
    }

    #[test]
    fn settings_default_and_validation_are_stable() {
        assert_eq!(OverlaySettings::default().opacity, 0.9);
        assert_eq!(OverlaySettings::default().position, PositionPreset::Right);
        assert!(OverlaySettings::default().validate().is_ok());
        assert!(OverlaySettings {
            opacity: f32::NAN,
            position: PositionPreset::Right,
        }
        .validate()
        .is_err());
        assert!(OverlaySettings {
            opacity: 1.1,
            position: PositionPreset::Right,
        }
        .validate()
        .is_err());
    }

    #[test]
    fn position_preset_parser_rejects_unknown_names() {
        assert_eq!(PositionPreset::parse("left"), Ok(PositionPreset::Left));
        assert!(PositionPreset::parse("corner").is_err());
    }
}
