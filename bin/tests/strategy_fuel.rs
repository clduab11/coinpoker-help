//! Fuel validation: `strategy/` data must stay engine-true (strategy/README).
//!
//! Guards drift between the authored doctrine files and the compiled engine:
//! - `preflop_ranges.json` tokens parse with `core_engine::ranges` dialect.
//! - `exploits.json` multipliers equal `ExploitEngine::adjust` exactly.
//! - `odds_tables.json` stays monotonic and break-even consistent.

use std::path::PathBuf;

fn load(name: &str) -> serde_json::Value {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../strategy")
        .join(name);
    let bytes = std::fs::read(&path).unwrap_or_else(|error| panic!("read {path:?}: {error}"));
    serde_json::from_slice(&bytes).unwrap_or_else(|error| panic!("parse {path:?}: {error}"))
}

#[test]
fn every_range_token_parses_with_the_engine_dialect() {
    let ranges = load("preflop_ranges.json");
    fn walk(value: &serde_json::Value, checked: &mut usize) {
        match value {
            serde_json::Value::String(text) if !text.is_empty() && !text.contains(' ') => {
                core_engine::ranges::expand_notation(text)
                    .unwrap_or_else(|error| panic!("token {text}: {error}"));
                *checked += 1;
            }
            serde_json::Value::Array(items) => {
                for item in items {
                    walk(item, checked);
                }
            }
            serde_json::Value::Object(map) => {
                for item in map.values() {
                    walk(item, checked);
                }
            }
            _ => {}
        }
    }
    let mut checked = 0;
    walk(&ranges, &mut checked);
    assert!(checked >= 30, "only {checked} tokens checked");
}

#[test]
fn exploit_multipliers_match_the_engine_exactly() {
    use core_engine::opponent::classifier::Archetype;
    use core_engine::opponent::exploit::ExploitEngine;

    let exploits = load("exploits.json");
    let engine = ExploitEngine::new();
    let archetypes = [
        ("Lag", Archetype::Lag),
        ("Tag", Archetype::Tag),
        ("LoosePassive", Archetype::LoosePassive),
        ("TightPassive", Archetype::TightPassive),
        ("Unknown", Archetype::Unknown),
    ];
    for (key, archetype) in archetypes {
        let block = &exploits["archetypes"][key];
        let adjustment = engine.adjust(archetype);
        assert_eq!(
            block["fold_equity_multiplier"].as_f64().unwrap(),
            adjustment.fold_equity_multiplier,
            "{key} fold equity drifted"
        );
        assert_eq!(
            block["raise_size_multiplier"].as_f64().unwrap(),
            adjustment.raise_size_multiplier,
            "{key} raise size drifted"
        );
    }
}

#[test]
fn odds_tables_are_monotonic_and_break_even_consistent() {
    let odds = load("odds_tables.json");
    let mut previous = 0.0;
    for row in odds["outs_to_equity_pct"].as_array().unwrap() {
        let one_card = row["unseen47"].as_f64().unwrap();
        assert!(one_card > previous, "outs row {}", row["outs"]);
        previous = one_card;
        assert!(row["two_streets"].as_f64().unwrap() > one_card);
    }
    for row in odds["pot_odds_break_even"].as_array().unwrap() {
        let (antecedent, consequent) = row["pot_odds"].as_str().unwrap().split_once(':').unwrap();
        let ratio = antecedent.parse::<f64>().unwrap() / consequent.parse::<f64>().unwrap();
        let expected = 100.0 / (1.0 + ratio);
        let value = row["required_equity_pct"].as_f64().unwrap();
        assert!((expected - value).abs() < 0.15, "{row}");
    }
}

#[test]
fn open_lists_mirror_the_reference_card_exactly() {
    use core_engine::ranges::{Position6max, RANGE_TIERS};

    let ranges = load("preflop_ranges.json");
    let positions = [
        ("UTG", Position6max::Utg),
        ("HJ", Position6max::Hj),
        ("CO", Position6max::Co),
        ("BTN", Position6max::Btn),
        ("SB", Position6max::Sb),
    ];
    for (key, position) in positions {
        let mut expected: Vec<String> = RANGE_TIERS
            .iter()
            .filter(|tier| tier.added_by.contains(&position))
            .flat_map(|tier| tier.notation.iter().map(|t| t.to_string()))
            .collect();
        let mut listed: Vec<String> = ranges["positions"][key]["open"]
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_str().unwrap().to_string())
            .collect();
        expected.sort();
        listed.sort();
        assert_eq!(listed, expected, "{key} opens drifted from the card");
    }
    assert!(ranges["positions"]["BB"]["open"]
        .as_array()
        .unwrap()
        .is_empty());
}
