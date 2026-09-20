//! egui overlay application.
//!
//! Drains [`OverlayEvent`]s from a channel and paints a transparent,
//! click-through study overlay. The state machine itself lives in
//! [`crate::overlay`] and is unit-tested headlessly; this module is only the
//! thin `eframe` presentation layer.

use std::sync::mpsc;
use std::time::Duration;

use crate::overlay::{panel_position, OverlayEvent, OverlayState};
use crate::widgets::render_overlay;

/// The egui overlay application.
pub struct DecisionApp {
    state: OverlayState,
    receiver: mpsc::Receiver<OverlayEvent>,
    last_position: Option<egui::Pos2>,
}

impl DecisionApp {
    pub fn new(receiver: mpsc::Receiver<OverlayEvent>) -> Self {
        Self {
            state: OverlayState::new(),
            receiver,
            last_position: None,
        }
    }

    /// Drain all pending events into the state machine (headless-safe).
    pub fn drain_events(&mut self) {
        while let Ok(event) = self.receiver.try_recv() {
            self.state.apply(&event);
        }
    }

    /// The current display state.
    pub fn state(&self) -> &OverlayState {
        &self.state
    }

    /// Move the overlay window next to the table, deduplicating repeats.
    fn reposition(&mut self, ctx: &egui::Context) {
        let Some(table) = self.state.table() else {
            return;
        };
        let (x, y) = panel_position(&table);
        let position = egui::Pos2::new(x, y);
        if self.last_position != Some(position) {
            ctx.send_viewport_cmd(egui::ViewportCommand::OuterPosition(position));
            self.last_position = Some(position);
        }
    }
}

impl eframe::App for DecisionApp {
    /// A transparent overlay must clear to fully-transparent black.
    fn clear_color(&self, _visuals: &egui::Visuals) -> [f32; 4] {
        [0.0, 0.0, 0.0, 0.0]
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.drain_events();
        self.reposition(ui.ctx());

        match self.state.view() {
            Some(view) => render_overlay(ui, view),
            None => {
                ui.label("Waiting for a decision point…");
            }
        }

        ui.ctx().request_repaint_after(Duration::from_millis(100));
    }
}

/// Run the overlay window.
pub fn run_overlay(receiver: mpsc::Receiver<OverlayEvent>) -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([crate::overlay::PANEL_SIZE.0, crate::overlay::PANEL_SIZE.1])
            .with_title("CoinPoker Study Overlay")
            .with_transparent(true)
            .with_decorations(false)
            .with_resizable(false)
            .with_always_on_top()
            .with_mouse_passthrough(true)
            .with_active(false)
            .with_has_shadow(false),
        ..Default::default()
    };
    eframe::run_native(
        "coinpoker-help-overlay",
        options,
        Box::new(move |_cc| Ok(Box::new(DecisionApp::new(receiver)))),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::overlay::TableBounds;
    use crate::widgets::DecisionView;
    use eframe::App as _;

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

    #[test]
    fn app_drains_decisions_clears_and_positions_headlessly() {
        let (tx, rx) = mpsc::channel();
        let mut app = DecisionApp::new(rx);
        assert!(app.state().view().is_none());

        tx.send(OverlayEvent::Decision(decision())).expect("send");
        tx.send(OverlayEvent::Position(TableBounds {
            x: 0.0,
            y: 0.0,
            width: 800.0,
            height: 600.0,
        }))
        .expect("send");
        drop(tx);

        app.drain_events();
        assert!(app.state().view().is_some());
        assert!(app.state().table().is_some());
    }

    #[test]
    fn clear_overrides_a_decision_and_reposition_tracks_once() {
        let (tx, rx) = mpsc::channel();
        let mut app = DecisionApp::new(rx);
        tx.send(OverlayEvent::Decision(decision())).expect("send");
        tx.send(OverlayEvent::Clear("action-not-required".to_string()))
            .expect("send");
        tx.send(OverlayEvent::Position(TableBounds {
            x: 100.0,
            y: 200.0,
            width: 800.0,
            height: 600.0,
        }))
        .expect("send");
        drop(tx);

        app.drain_events();
        assert!(app.state().view().is_none());

        let ctx = egui::Context::default();
        app.reposition(&ctx);
        assert!(app.last_position.is_some());
        let first = app.last_position;
        app.reposition(&ctx);
        assert_eq!(app.last_position, first);
    }

    #[test]
    fn clear_color_is_fully_transparent() {
        let (_, rx) = mpsc::channel();
        let app = DecisionApp::new(rx);
        assert_eq!(
            app.clear_color(&egui::Visuals::dark()),
            [0.0, 0.0, 0.0, 0.0]
        );
    }
}
