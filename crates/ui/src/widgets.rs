//! Decision panel and probability metric widgets.
//!
//! Renders the primary decision (Fold/Call/Raise) and the underlying
//! probability metrics with high signal-to-noise ratio. Formatting logic is
//! pure and unit-tested; the egui rendering is a thin presentation layer.

use serde::Serialize;

/// Everything the panel needs to display for one decision point.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DecisionView {
    /// Recommended action: fold, check, call, or raise.
    pub action: String,
    /// Recommended total amount for a raise; 0 otherwise.
    pub amount: u32,
    /// Expected value of the recommended action, in chips.
    pub ev: f64,
    /// Pot odds as a fraction of the final pot (None when facing no bet).
    pub pot_odds: Option<f64>,
    /// Equity used for the decision.
    pub equity: f64,
    /// Break-even equity required to call (None when facing no bet).
    pub break_even: Option<f64>,
    /// Opponent archetype label, when available.
    pub opponent: Option<String>,
    /// Classification confidence in [0, 1], when available.
    pub confidence: Option<f64>,
}

impl DecisionView {
    /// Format pot odds as `3.2:1` (None when facing no bet).
    pub fn pot_odds_ratio_label(&self) -> Option<String> {
        self.pot_odds.map(|f| {
            if f <= 0.0 {
                return "0:1".to_string();
            }
            let ratio = (1.0 - f) / f;
            format!("{ratio:.1}:1")
        })
    }

    /// Format equity as a percentage.
    pub fn equity_percent(&self) -> String {
        format!("{:.1}%", self.equity * 100.0)
    }

    /// Format break-even equity as a percentage.
    pub fn break_even_percent(&self) -> Option<String> {
        self.break_even.map(|f| format!("{:.1}%", f * 100.0))
    }

    /// Format the EV in chips with sign.
    pub fn ev_label(&self) -> String {
        format!("{:+.2}", self.ev)
    }

    /// A single-line summary for logging and headless output.
    pub fn summary(&self) -> String {
        let action = if self.amount > 0 {
            format!("{} {}", self.action, self.amount)
        } else {
            self.action.clone()
        };
        format!(
            "{} | EV {} | equity {} | pot odds {}",
            action,
            self.ev_label(),
            self.equity_percent(),
            self.pot_odds_ratio_label()
                .unwrap_or_else(|| "-".to_string())
        )
    }
}

/// Render the decision panel into an egui frame.
pub fn render_panel(ui: &mut egui::Ui, view: &DecisionView) {
    egui::Frame::group(ui.style())
        .inner_margin(egui::Margin::same(12))
        .show(ui, |ui| {
            ui.vertical_centered(|ui| {
                ui.heading(format!("EV {}", view.ev_label()));
                ui.add_space(6.0);
                ui.label(format!("Equity: {}", view.equity_percent()));
                if let Some(be) = view.break_even_percent() {
                    ui.label(format!("Break-even: {be}"));
                }
                if let Some(odds) = view.pot_odds_ratio_label() {
                    ui.label(format!("Pot odds: {odds}"));
                }
                if let (Some(opponent), Some(confidence)) = (&view.opponent, view.confidence) {
                    ui.add_space(4.0);
                    ui.label(format!("Opponent: {opponent}"));
                    ui.label(format!("Confidence: {:.0}%", confidence * 100.0));
                }
            });
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn view() -> DecisionView {
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
    fn pot_odds_ratio_label_formats_as_ratio() {
        // 0.238 fraction -> ratio (1 - 0.238) / 0.238 = 3.2.
        let v = view();
        assert_eq!(v.pot_odds_ratio_label().as_deref(), Some("3.2:1"));
    }

    #[test]
    fn no_pot_odds_when_facing_no_bet() {
        let mut v = view();
        v.pot_odds = None;
        v.break_even = None;
        assert_eq!(v.pot_odds_ratio_label(), None);
        assert_eq!(v.break_even_percent(), None);
    }

    #[test]
    fn equity_and_ev_formatting() {
        let v = view();
        assert_eq!(v.equity_percent(), "41.2%");
        assert_eq!(v.ev_label(), "+0.42");
    }

    #[test]
    fn summary_includes_action_and_metrics() {
        let v = view();
        let s = v.summary();
        assert!(s.contains("call"));
        assert!(s.contains("EV +0.42"));
        assert!(s.contains("41.2%"));
        assert!(s.contains("3.2:1"));
    }

    #[test]
    fn summary_annotates_raise_amounts() {
        let mut v = view();
        v.action = "raise".to_string();
        v.amount = 750;
        assert!(v.summary().starts_with("raise 750"));
    }
}
