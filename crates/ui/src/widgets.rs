//! Decision panel and probability metric widgets.
//!
//! Renders the primary decision (Fold/Call/Raise) and the underlying
//! probability metrics with high signal-to-noise ratio. Formatting logic is
//! pure and unit-tested; the egui rendering is a thin presentation layer.

use serde::Serialize;

/// Everything the panel needs to display for one decision point.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DecisionView {
    /// Recommended action: fold, check, call, raise, or allin.
    pub action: String,
    /// Recommended total amount for a raise; 0 otherwise.
    pub amount: u32,
    /// Ghost-layer path used to derive a raise size, when applicable.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sizing_provenance: Option<String>,
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
        let action = action_badge_with_provenance(
            &self.action,
            self.amount,
            self.sizing_provenance.as_deref(),
        )
        .to_ascii_lowercase();
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

/// A point in panel-local coordinates (y grows downward, matching egui).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Point {
    pub x: f32,
    pub y: f32,
}

impl Point {
    pub const fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }
}

/// Clamp a value into the unit interval, mapping non-finite values to zero.
pub fn clamp_unit(value: f64) -> f64 {
    if value.is_finite() {
        value.clamp(0.0, 1.0)
    } else {
        0.0
    }
}

/// Map a unit fraction to a sweep angle in radians (a full turn at `1.0`).
pub fn sweep_for_fraction(fraction: f64) -> f32 {
    clamp_unit(fraction) as f32 * std::f32::consts::TAU
}

/// Sample `segments + 1` points along a circular arc.
///
/// `start_angle` and `sweep` are in radians. Angle `0` points right
/// (3 o'clock) and positive angles sweep clockwise, matching egui's
/// y-down coordinate system. `segments` is clamped to at least `2`.
pub fn arc_points(
    center: Point,
    radius: f32,
    start_angle: f32,
    sweep: f32,
    segments: usize,
) -> Vec<Point> {
    let segments = segments.max(2);
    (0..=segments)
        .map(|index| {
            let t = index as f32 / segments as f32;
            let angle = start_angle + sweep * t;
            Point::new(
                center.x + radius * angle.cos(),
                center.y + radius * angle.sin(),
            )
        })
        .collect()
}

/// The action badge label for a decision (for example `RAISE 750`).
///
/// The amount is appended only when the action moves chips.
pub fn action_badge(action: &str, amount: u32) -> String {
    let action = action.trim().to_ascii_uppercase();
    if amount > 0 {
        format!("{action} {amount}")
    } else {
        action
    }
}

/// The action badge with its ghost-layer sizing provenance, when available.
pub fn action_badge_with_provenance(
    action: &str,
    amount: u32,
    sizing_provenance: Option<&str>,
) -> String {
    let badge = action_badge(action, amount);
    match sizing_provenance {
        Some(provenance) => format!("{badge} [{provenance}]"),
        None => badge,
    }
}

/// Render the overlay panel for one decision point.
#[cfg(feature = "desktop")]
pub fn render_overlay(ui: &mut egui::Ui, view: &DecisionView, opacity: f32) {
    let rect = ui.max_rect().shrink(16.0);
    let painter = ui.painter();

    painter.rect_filled(
        rect,
        12.0,
        with_opacity(egui::Color32::from_black_alpha(150), opacity),
    );

    painter.text(
        rect.left_top() + egui::vec2(0.0, 8.0),
        egui::Align2::LEFT_TOP,
        action_badge_with_provenance(&view.action, view.amount, view.sizing_provenance.as_deref()),
        egui::FontId::proportional(30.0),
        with_opacity(action_color(&view.action), opacity),
    );

    let metrics = rect.left_top() + egui::vec2(0.0, 52.0);
    painter.text(
        metrics,
        egui::Align2::LEFT_TOP,
        format!("EV {}", view.ev_label()),
        egui::FontId::proportional(16.0),
        with_opacity(egui::Color32::from_gray(230), opacity),
    );
    painter.text(
        metrics + egui::vec2(0.0, 22.0),
        egui::Align2::LEFT_TOP,
        format!(
            "Pot odds: {}",
            view.pot_odds_ratio_label()
                .unwrap_or_else(|| "-".to_string())
        ),
        egui::FontId::proportional(16.0),
        with_opacity(egui::Color32::from_gray(230), opacity),
    );
    if let Some(break_even) = view.break_even_percent() {
        painter.text(
            metrics + egui::vec2(0.0, 44.0),
            egui::Align2::LEFT_TOP,
            format!("Break-even: {break_even}"),
            egui::FontId::proportional(16.0),
            with_opacity(egui::Color32::from_gray(230), opacity),
        );
    }

    let equity_center = egui::pos2(rect.left() + 72.0, rect.bottom() - 64.0);
    draw_equity_arc(painter, equity_center, 56.0, view.equity, opacity);
    painter.text(
        equity_center + egui::vec2(0.0, 8.0),
        egui::Align2::CENTER_CENTER,
        view.equity_percent(),
        egui::FontId::proportional(16.0),
        with_opacity(egui::Color32::from_gray(240), opacity),
    );

    if let Some(confidence) = view.confidence {
        let ring_center = egui::pos2(rect.right() - 52.0, rect.bottom() - 52.0);
        draw_confidence_ring(painter, ring_center, 40.0, confidence, opacity);
        painter.text(
            ring_center + egui::vec2(0.0, 12.0),
            egui::Align2::CENTER_CENTER,
            format!("{:.0}%", confidence * 100.0),
            egui::FontId::proportional(13.0),
            with_opacity(egui::Color32::from_gray(230), opacity),
        );
    }

    if let Some(opponent) = &view.opponent {
        painter.text(
            rect.left_bottom() + egui::vec2(0.0, -8.0),
            egui::Align2::LEFT_BOTTOM,
            format!("Opponent: {opponent}"),
            egui::FontId::proportional(14.0),
            with_opacity(egui::Color32::from_gray(200), opacity),
        );
    }
}

/// Color for an action badge.
#[cfg(feature = "desktop")]
fn action_color(action: &str) -> egui::Color32 {
    match action.trim().to_ascii_lowercase().as_str() {
        "fold" => egui::Color32::from_rgb(230, 90, 90),
        "check" => egui::Color32::from_rgb(120, 200, 120),
        "call" => egui::Color32::from_rgb(240, 200, 90),
        "raise" => egui::Color32::from_rgb(240, 150, 70),
        "allin" => egui::Color32::from_rgb(210, 90, 220),
        _ => egui::Color32::from_gray(200),
    }
}

/// Apply the user-selected opacity to a color, safely handling invalid input.
#[cfg(feature = "desktop")]
fn with_opacity(color: egui::Color32, opacity: f32) -> egui::Color32 {
    let opacity = if opacity.is_finite() {
        opacity.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let alpha = (f32::from(color.a()) * opacity).round() as u8;
    egui::Color32::from_rgba_unmultiplied(color.r(), color.g(), color.b(), alpha)
}

/// Paint a 270-degree equity gauge arc filled proportionally to `equity`.
#[cfg(feature = "desktop")]
fn draw_equity_arc(
    painter: &egui::Painter,
    center: egui::Pos2,
    radius: f32,
    equity: f64,
    opacity: f32,
) {
    const START: f32 = -std::f32::consts::FRAC_PI_2;
    const FULL_SWEEP: f32 = std::f32::consts::TAU * 0.75;
    let background = arc_points(
        Point::new(center.x, center.y),
        radius,
        START,
        FULL_SWEEP,
        64,
    );
    let filled = arc_points(
        Point::new(center.x, center.y),
        radius,
        START,
        sweep_for_fraction(equity) * 0.75,
        64,
    );
    painter.add(egui::Shape::line(
        to_pos2(&background),
        egui::Stroke::new(10.0, with_opacity(egui::Color32::from_gray(60), opacity)),
    ));
    painter.add(egui::Shape::line(
        to_pos2(&filled),
        egui::Stroke::new(
            10.0,
            with_opacity(egui::Color32::from_rgb(90, 190, 255), opacity),
        ),
    ));
}

/// Paint a full-circle confidence ring filled proportionally to `confidence`.
#[cfg(feature = "desktop")]
fn draw_confidence_ring(
    painter: &egui::Painter,
    center: egui::Pos2,
    radius: f32,
    confidence: f64,
    opacity: f32,
) {
    const START: f32 = -std::f32::consts::FRAC_PI_2;
    let background = arc_points(
        Point::new(center.x, center.y),
        radius,
        START,
        std::f32::consts::TAU,
        64,
    );
    let filled = arc_points(
        Point::new(center.x, center.y),
        radius,
        START,
        sweep_for_fraction(confidence),
        64,
    );
    painter.add(egui::Shape::line(
        to_pos2(&background),
        egui::Stroke::new(6.0, with_opacity(egui::Color32::from_gray(60), opacity)),
    ));
    painter.add(egui::Shape::line(
        to_pos2(&filled),
        egui::Stroke::new(
            6.0,
            with_opacity(egui::Color32::from_rgb(150, 240, 150), opacity),
        ),
    ));
}

/// Convert panel-space points into egui positions.
#[cfg(feature = "desktop")]
fn to_pos2(points: &[Point]) -> Vec<egui::Pos2> {
    points
        .iter()
        .map(|point| egui::pos2(point.x, point.y))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn view() -> DecisionView {
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

    #[test]
    fn clamp_unit_bounds_and_defuses_non_finite() {
        assert_eq!(clamp_unit(-0.5), 0.0);
        assert_eq!(clamp_unit(0.0), 0.0);
        assert_eq!(clamp_unit(0.5), 0.5);
        assert_eq!(clamp_unit(1.0), 1.0);
        assert_eq!(clamp_unit(1.5), 1.0);
        assert_eq!(clamp_unit(f64::NAN), 0.0);
        assert_eq!(clamp_unit(f64::INFINITY), 0.0);
    }

    #[test]
    fn sweep_for_fraction_maps_a_full_turn() {
        assert_eq!(sweep_for_fraction(0.0), 0.0);
        assert_eq!(sweep_for_fraction(1.0), std::f32::consts::TAU);
        assert_eq!(sweep_for_fraction(0.25), std::f32::consts::FRAC_PI_2);
        assert_eq!(sweep_for_fraction(-1.0), 0.0);
        assert_eq!(sweep_for_fraction(2.0), std::f32::consts::TAU);
    }

    #[test]
    fn arc_points_trace_a_quarter_turn_from_twelve_o_clock() {
        let points = arc_points(
            Point::new(0.0, 0.0),
            1.0,
            -std::f32::consts::FRAC_PI_2,
            std::f32::consts::FRAC_PI_2,
            4,
        );
        assert_eq!(points.len(), 5);
        let first = points.first().expect("first");
        let last = points.last().expect("last");
        assert!(first.x.abs() < 1e-6 && (first.y + 1.0).abs() < 1e-6);
        assert!((last.x - 1.0).abs() < 1e-6 && last.y.abs() < 1e-6);
    }

    #[test]
    fn arc_points_respects_radius_and_clamps_segments() {
        let points = arc_points(Point::new(10.0, 20.0), 5.0, 0.0, std::f32::consts::TAU, 1);
        assert_eq!(points.len(), 3);
        let first = points.first().expect("first");
        assert!((first.x - 15.0).abs() < 1e-6 && (first.y - 20.0).abs() < 1e-6);
    }

    #[test]
    fn action_badge_appends_amount_only_for_chip_moving_actions() {
        assert_eq!(action_badge("raise", 750), "RAISE 750");
        assert_eq!(action_badge("  call ", 500), "CALL 500");
        assert_eq!(action_badge("allin", 5000), "ALLIN 5000");
        assert_eq!(action_badge("fold", 0), "FOLD");
        assert_eq!(action_badge("check", 0), "CHECK");
        assert_eq!(
            action_badge_with_provenance("raise", 750, Some("ghost-menu")),
            "RAISE 750 [ghost-menu]"
        );
    }
}

#[cfg(test)]
mod snapshot_tests {
    use super::*;
    use insta::assert_json_snapshot;

    fn view() -> DecisionView {
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

    #[test]
    fn decision_view_call_snapshot() {
        let v = view();
        assert_json_snapshot!(v);
    }

    #[test]
    fn decision_view_raise_snapshot() {
        let mut v = view();
        v.action = "raise".to_string();
        v.amount = 750;
        v.ev = 1.23;
        v.equity = 0.55;
        assert_json_snapshot!(v);
    }

    #[test]
    fn decision_view_fold_snapshot() {
        let mut v = view();
        v.action = "fold".to_string();
        v.ev = -0.25;
        v.equity = 0.15;
        v.pot_odds = Some(0.33);
        v.break_even = Some(0.33);
        v.opponent = Some("tag".to_string());
        v.confidence = Some(0.95);
        assert_json_snapshot!(v);
    }

    #[test]
    fn decision_view_no_pot_odds_snapshot() {
        let mut v = view();
        v.action = "check".to_string();
        v.ev = 0.0;
        v.equity = 0.5;
        v.pot_odds = None;
        v.break_even = None;
        v.opponent = None;
        v.confidence = None;
        assert_json_snapshot!(v);
    }
}

#[cfg(all(test, feature = "desktop"))]
mod render_tests {
    use super::*;

    fn view() -> DecisionView {
        DecisionView {
            action: "raise".to_string(),
            amount: 750,
            sizing_provenance: Some("ghost-menu".to_string()),
            ev: 1.23,
            pot_odds: Some(0.238),
            equity: 0.55,
            break_even: Some(0.238),
            opponent: Some("tag".to_string()),
            confidence: Some(0.9),
        }
    }

    #[test]
    fn overlay_renders_headlessly() {
        let ctx = egui::Context::default();
        let view = view();
        let output = ctx.run_ui(egui::RawInput::default(), |ui| {
            render_overlay(ui, &view, 0.9);
        });
        output.drop_without_applying_deltas();
    }

    #[test]
    fn overlay_renders_without_confidence() {
        let ctx = egui::Context::default();
        let mut view = view();
        view.confidence = None;
        view.opponent = None;
        view.break_even = None;
        let output = ctx.run_ui(egui::RawInput::default(), |ui| {
            render_overlay(ui, &view, 0.5);
        });
        output.drop_without_applying_deltas();
    }

    #[test]
    fn opacity_scales_alpha_and_defuses_invalid_values() {
        assert_eq!(with_opacity(egui::Color32::WHITE, 0.5).a(), 128);
        assert_eq!(with_opacity(egui::Color32::WHITE, f32::NAN).a(), 0);
    }
}
