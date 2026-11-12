//! JSON Schema for the VLM's structured game-state output.
//!
//! The schema is sent alongside each request via the OpenAI-compatible
//! `response_format: json_schema` field so servers that support guided
//! decoding constrain the model to the exact contract up front. Servers
//! without schema support ignore the field; the parser remains the trust
//! boundary either way (see [`crate::parser`]).

use serde_json::{json, Value};

/// The schema name used in `response_format` requests.
pub const SCHEMA_NAME: &str = "game_state";

/// Build the `response_format` request value for schema-constrained output.
///
/// `strict: false` keeps the schema advisory for servers that validate it:
/// the model is told to emit every field, but optional fields may be
/// omitted and filled from defaults during parsing.
pub fn response_format() -> Value {
    json!({
        "type": "json_schema",
        "json_schema": {
            "name": SCHEMA_NAME,
            "schema": game_state_schema(),
            "strict": false,
        }
    })
}

/// The JSON Schema describing a valid [`GameState`](crate::parser::GameState)
/// observation.
///
/// Mirrors the contract in [`crate::prompt::SYSTEM_PROMPT`]: short rank
/// names, suit names, integer chip amounts, and the exact field set.
pub fn game_state_schema() -> Value {
    let rank = json!({
        "type": "string",
        "enum": ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"],
    });
    let suit = json!({
        "type": "string",
        "enum": ["spades", "hearts", "diamonds", "clubs"],
    });
    let card = json!({
        "type": "object",
        "properties": {
            "rank": rank,
            "suit": suit,
        },
        "required": ["rank", "suit"],
        "additionalProperties": false,
    });
    let player = json!({
        "type": "object",
        "properties": {
            "name": { "type": "string" },
            "chips": { "type": "integer", "minimum": 0 },
            "last_action": {
                "type": ["string", "null"],
                "enum": ["fold", "check", "call", "raise", "bet", "allin", null],
            },
            "bet_amount": { "type": "integer", "minimum": 0 },
        },
        "required": ["name", "chips"],
        "additionalProperties": false,
    });

    json!({
        "type": "object",
        "properties": {
            "game_phase": {
                "type": "string",
                "enum": ["lobby", "preflop", "flop", "turn", "river", "showdown"],
            },
            "hero_cards": { "type": "array", "items": card, "maxItems": 2 },
            "board": { "type": "array", "items": card, "maxItems": 5 },
            "pot_size": { "type": "integer", "minimum": 0 },
            "to_call": { "type": "integer", "minimum": 0 },
            "hero_chips": { "type": "integer", "minimum": 0 },
            "min_raise_to": { "type": ["integer", "null"], "minimum": 0 },
            "max_raise_to": { "type": ["integer", "null"], "minimum": 0 },
            "players": { "type": "array", "items": player },
            "action_required": { "type": "boolean" },
            "available_actions": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["fold", "check", "call", "raise", "allin"],
                },
            },
            "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        },
        "required": [
            "game_phase",
            "pot_size",
            "to_call",
            "hero_chips",
            "action_required",
        ],
        "additionalProperties": false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn response_format_wraps_the_schema_with_the_expected_name() {
        let format = response_format();
        assert_eq!(format["type"], "json_schema");
        assert_eq!(format["json_schema"]["name"], SCHEMA_NAME);
        assert_eq!(format["json_schema"]["strict"], false);
        assert_eq!(format["json_schema"]["schema"], game_state_schema());
    }

    #[test]
    fn schema_covers_every_game_state_field() {
        let schema = game_state_schema();
        let properties = schema["properties"].as_object().expect("properties");
        for field in [
            "game_phase",
            "hero_cards",
            "board",
            "pot_size",
            "to_call",
            "hero_chips",
            "min_raise_to",
            "max_raise_to",
            "players",
            "action_required",
            "available_actions",
            "confidence",
        ] {
            assert!(
                properties.contains_key(field),
                "missing schema field {field}"
            );
        }
    }

    #[test]
    fn schema_enums_match_the_parser_contract() {
        let schema = game_state_schema();
        assert_eq!(
            schema["properties"]["game_phase"]["enum"],
            json!(["lobby", "preflop", "flop", "turn", "river", "showdown"])
        );
        assert_eq!(
            schema["properties"]["available_actions"]["items"]["enum"],
            json!(["fold", "check", "call", "raise", "allin"])
        );
        let rank = &schema["properties"]["hero_cards"]["items"]["properties"]["rank"]["enum"];
        assert!(rank.as_array().expect("ranks").len() == 13);
    }

    #[test]
    fn schema_requires_the_critical_numeric_fields() {
        let schema = game_state_schema();
        let required = schema["required"].as_array().expect("required");
        for field in [
            "game_phase",
            "pot_size",
            "to_call",
            "hero_chips",
            "action_required",
        ] {
            assert!(required.contains(&json!(field)), "missing required {field}");
        }
    }

    #[test]
    fn schema_confidence_is_bounded() {
        let schema = game_state_schema();
        assert_eq!(schema["properties"]["confidence"]["minimum"], 0.0);
        assert_eq!(schema["properties"]["confidence"]["maximum"], 1.0);
    }
}
