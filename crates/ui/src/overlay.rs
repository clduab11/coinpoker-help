//! Overlay event model and headless state transitions.
//!
//! The live capture loop feeds the overlay through a channel of
//! [`OverlayEvent`]s, and [`OverlayState`] applies them without any GPU or
//! windowing dependency. Keeping the transition logic here — separate from
//! the `desktop`-gated egui rendering in [`crate::app`] — makes every state
//! transition unit-testable on any host.

use crate::widgets::DecisionView;

/// The captured table window's on-screen bounds in display points.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TableBounds {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// An event sent from the live capture loop to the overlay.
#[derive(Debug, Clone, PartialEq)]
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
    let x = (table.x + table.width + f64::from(PANEL_MARGIN)) as f32;
    let y = (table.y + (table.height - f64::from(PANEL_SIZE.1)) / 2.0) as f32;
    (x.max(0.0), y.max(0.0))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decision() -> DecisionView {
        DecisionView {
            action: "call".to_string(),
            amount: 0,
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
}
