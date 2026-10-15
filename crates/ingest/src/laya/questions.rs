//! The vendored Laya question set (`coinpoker-laya-question-set-vendored/2`).
//!
//! `criteria` is kept as raw JSON and forwarded unchanged to the server. The
//! workspace's `serde_json` has no `preserve_order` feature, so object key order
//! is not preserved in Rust; nothing here relies on it (the server answers by label).

use std::sync::OnceLock;

use serde::Deserialize;

const QUESTION_SET_JSON: &str = include_str!("../../assets/laya/question-set.json");

#[derive(Debug, Clone, Deserialize)]
pub struct QuestionSet {
    pub schema: String,
    pub version: String,
    pub thresholds: Thresholds,
    pub max_glyphs: u32,
    #[serde(default)]
    pub assembly_rules: Vec<String>,
    pub passes: Vec<Pass>,
}

#[derive(Debug, Clone, Copy, Deserialize)]
pub struct Thresholds {
    pub initial: f64,
    pub calibrated: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Layout {
    Full,
    Slots,
    Glyphs,
}

impl Layout {
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Full => "full",
            Self::Slots => "slots",
            Self::Glyphs => "glyphs",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Calibration {
    Trained,
    UntrainedProvisional,
    Uncalibrated,
    Calibrated,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QuestionType {
    Choice,
    Noul,
}

impl QuestionType {
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Choice => "choice",
            Self::Noul => "noul",
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct Pass {
    pub id: String,
    pub tier: u8,
    pub layout: Layout,
    pub regions: Vec<String>,
    pub calibration: Calibration,
    pub note: String,
    pub threshold: f64,
    #[serde(default)]
    pub glyph_style: Option<String>,
    #[serde(default)]
    pub amount: Option<String>,
    pub questions: Vec<Question>,
}

impl Pass {
    pub fn question(&self, id: &str) -> Option<&Question> {
        self.questions.iter().find(|question| question.id == id)
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct Question {
    pub id: String,
    #[serde(rename = "type")]
    pub kind: QuestionType,
    pub instructions: String,
    /// Object `label -> description` or array of labels, forwarded unchanged.
    #[serde(default)]
    pub criteria: Option<serde_json::Value>,
    pub on_low_confidence: String,
    pub envelope: String,
    #[serde(default)]
    pub image: Option<u32>,
    #[serde(default)]
    pub vocab: Option<String>,
    /// Canonical option order (Laya's option order is part of the model input; object keys
    /// lose their order when parsed without serde_json's `preserve_order`).
    #[serde(default)]
    pub option_order: Option<Vec<String>>,
}

impl Question {
    /// Criteria in wire form: object criteria become ordered `[label, description]` pairs in
    /// `option_order`; array criteria are forwarded unchanged.
    pub fn wire_criteria(&self) -> Option<serde_json::Value> {
        match (&self.criteria, &self.option_order) {
            (Some(serde_json::Value::Object(map)), Some(order)) => Some(serde_json::Value::Array(
                order
                    .iter()
                    .map(|label| {
                        serde_json::json!([label, map.get(label).cloned().unwrap_or_default()])
                    })
                    .collect(),
            )),
            (criteria, _) => criteria.clone(),
        }
    }

    /// Option labels (unordered for object criteria; never rely on the order).
    pub fn options(&self) -> Vec<&str> {
        match &self.criteria {
            Some(serde_json::Value::Object(map)) => map.keys().map(String::as_str).collect(),
            Some(serde_json::Value::Array(items)) => {
                items.iter().filter_map(serde_json::Value::as_str).collect()
            }
            _ => Vec::new(),
        }
    }

    pub fn has_option(&self, label: &str) -> bool {
        match &self.criteria {
            Some(serde_json::Value::Object(map)) => map.contains_key(label),
            Some(serde_json::Value::Array(items)) => {
                items.iter().any(|item| item.as_str() == Some(label))
            }
            _ => false,
        }
    }
}

/// The vendored question set (parsed once).
pub fn question_set() -> &'static QuestionSet {
    static SET: OnceLock<QuestionSet> = OnceLock::new();
    SET.get_or_init(|| {
        serde_json::from_str(QUESTION_SET_JSON).expect("vendored question-set.json is valid")
    })
}

impl QuestionSet {
    pub fn pass(&self, id: &str) -> Option<&Pass> {
        self.passes.iter().find(|pass| pass.id == id)
    }
}

/// A pass of the vendored set by id.
pub fn pass(id: &str) -> Option<&'static Pass> {
    question_set().pass(id)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::laya::geometry::regions;
    use std::collections::BTreeMap;

    #[test]
    fn vendored_set_parses_with_expected_shape() {
        let set = question_set();
        assert_eq!(set.schema, "coinpoker-laya-question-set-vendored/2");
        assert_eq!(set.version, "0.4.0");
        assert_eq!(set.passes.len(), 14);
        assert_eq!(set.max_glyphs, 8);
        assert!(!set.thresholds.calibrated);
        let mut tiers = BTreeMap::new();
        for pass in &set.passes {
            *tiers.entry(pass.tier).or_insert(0) += pass.questions.len();
        }
        assert_eq!(tiers, BTreeMap::from([(0, 16), (1, 54), (2, 48)]));
        assert!(pass("p0_full").is_some());
        assert!(pass("p9_missing").is_none());
    }

    #[test]
    fn crop_passes_reference_known_regions_and_glyph_passes_ask_g1_to_g8() {
        let regions = regions();
        let glyphs: Vec<String> = (1..=8).map(|k| format!("g{k}")).collect();
        for pass in &question_set().passes {
            match pass.layout {
                Layout::Full => assert!(pass.regions.is_empty()),
                Layout::Slots | Layout::Glyphs => {
                    assert!(!pass.regions.is_empty(), "{}", pass.id);
                    for region in &pass.regions {
                        assert!(regions.regions.contains_key(region), "{region}");
                    }
                }
            }
            if pass.layout == Layout::Glyphs {
                assert_eq!(pass.regions.len(), 1);
                assert!(pass.glyph_style.is_some());
                let ids: Vec<&String> = pass.questions.iter().map(|q| &q.id).collect();
                assert_eq!(ids, glyphs.iter().collect::<Vec<_>>(), "{}", pass.id);
            }
        }
    }

    #[test]
    fn vocabularies_have_the_expected_option_counts_and_no_placeholders() {
        for pass in &question_set().passes {
            assert!(!pass.note.contains("{i}") && !pass.note.contains("<i>"));
            for question in &pass.questions {
                let options = question.options().len();
                match question.vocab.as_deref() {
                    Some("rank") => assert_eq!(options, 15),
                    Some("suit") => assert_eq!(options, 6),
                    Some("glyph") => assert_eq!(options, 13),
                    _ => {}
                }
                match question.kind {
                    QuestionType::Choice => assert!(options >= 2, "{}", question.id),
                    QuestionType::Noul => assert!(question.criteria.is_none()),
                }
                for text in [&question.instructions, &question.envelope] {
                    assert!(!text.contains("{i}") && !text.contains("<i>"), "{text}");
                }
                if let Some(criteria) = &question.criteria {
                    let text = criteria.to_string();
                    assert!(!text.contains("{i}") && !text.contains("<i>"));
                }
            }
        }
        let board = pass("p2_board").unwrap();
        assert!(board.question("board_1_rank").unwrap().has_option("T"));
        assert!(!board.question("board_1_rank").unwrap().has_option("10"));
    }

    #[test]
    fn wire_criteria_keep_the_canonical_option_order() {
        for pass in &question_set().passes {
            for question in &pass.questions {
                if let Some(serde_json::Value::Object(map)) = &question.criteria {
                    let order = question.option_order.as_ref().expect("option_order");
                    let mut sorted = order.clone();
                    sorted.sort();
                    let mut keys: Vec<String> = map.keys().cloned().collect();
                    keys.sort();
                    assert_eq!(sorted, keys, "{}", question.id);
                    let wire = question.wire_criteria().unwrap();
                    let labels: Vec<&str> = wire
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|pair| pair[0].as_str().unwrap())
                        .collect();
                    assert_eq!(labels, order.iter().map(String::as_str).collect::<Vec<_>>());
                }
            }
        }
        let rank = pass("p2_board")
            .unwrap()
            .question("board_1_rank")
            .unwrap()
            .wire_criteria()
            .unwrap();
        assert_eq!(rank[0], serde_json::json!(["2", "two"]));
        assert_eq!(rank[14][0], "unreadable");
    }
}
