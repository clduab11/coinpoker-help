//! egui application state.
//!
//! Owns the decision panel state and drives frame updates from the
//! decision-support pipeline.

use crate::widgets::{render_panel, DecisionView};

/// The egui application.
#[derive(Debug, Default)]
pub struct DecisionApp {
    /// The most recent decision to display.
    pub view: Option<DecisionView>,
}

impl DecisionApp {
    pub fn new() -> Self {
        Self::default()
    }

    /// Replace the displayed decision.
    pub fn set_decision(&mut self, view: DecisionView) {
        self.view = Some(view);
    }

    /// Clear the displayed decision.
    pub fn clear(&mut self) {
        self.view = None;
    }
}

impl eframe::App for DecisionApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        ui.heading("Decision Support");
        ui.add_space(8.0);
        match &self.view {
            Some(view) => render_panel(ui, view),
            None => {
                ui.label("Waiting for the next decision point…");
            }
        }
    }
}

/// Run the desktop panel.
pub fn run() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([320.0, 240.0])
            .with_title("Decision Support"),
        ..Default::default()
    };
    eframe::run_native(
        "coinpoker-help",
        options,
        Box::new(|_cc| Ok(Box::new(DecisionApp::new()))),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn app_starts_empty_and_accepts_decisions() {
        let mut app = DecisionApp::new();
        assert!(app.view.is_none());

        app.set_decision(DecisionView {
            action: "fold".to_string(),
            amount: 0,
            ev: 0.0,
            pot_odds: None,
            equity: 0.1,
            break_even: None,
            opponent: None,
            confidence: None,
        });
        assert!(app.view.is_some());

        app.clear();
        assert!(app.view.is_none());
    }
}
