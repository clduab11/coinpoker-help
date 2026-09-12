//! Parsing and validation of VLM output into a structured [`GameState`].
//!
//! Validates the JSON returned by the vision model, fills defaults for
//! missing fields, and degrades gracefully: callers keep the last valid
//! state when parsing fails.

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::vlm::VlmOutput;

/// Errors produced while parsing or validating VLM output.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum ParseError {
    /// No JSON object could be located in the model output.
    #[error("no JSON object found in VLM output")]
    NoJson,
    /// The JSON was malformed.
    #[error("malformed JSON: {0}")]
    Malformed(String),
    /// The JSON parsed but violates game-state invariants.
    #[error("invalid game state: {0}")]
    InvalidState(String),
}

/// A single playing card.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Card {
    /// Short rank name: A, K, Q, J, T, 9..2.
    pub rank: String,
    /// One of: spades, hearts, diamonds, clubs.
    pub suit: String,
}

/// The phase of the current hand.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum GamePhase {
    #[default]
    Lobby,
    Preflop,
    Flop,
    Turn,
    River,
    Showdown,
}

impl GamePhase {
    /// Number of community cards expected on the board in this phase.
    pub fn expected_board_cards(&self) -> usize {
        match self {
            GamePhase::Lobby | GamePhase::Preflop => 0,
            GamePhase::Flop => 3,
            GamePhase::Turn => 4,
            GamePhase::River | GamePhase::Showdown => 5,
        }
    }
}

/// Observed state of one player at the table.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlayerState {
    pub name: String,
    pub chips: u32,
    #[serde(default)]
    pub last_action: Option<String>,
    #[serde(default)]
    pub bet_amount: u32,
}

/// Structured description of the visible table state.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GameState {
    pub game_phase: GamePhase,
    #[serde(default)]
    pub hero_cards: Vec<Card>,
    #[serde(default)]
    pub board: Vec<Card>,
    #[serde(default)]
    pub pot_size: u32,
    #[serde(default)]
    pub to_call: u32,
    #[serde(default)]
    pub hero_chips: u32,
    #[serde(default)]
    pub players: Vec<PlayerState>,
    #[serde(default)]
    pub action_required: bool,
    #[serde(default)]
    pub available_actions: Vec<String>,
}

/// Parse and validate a [`VlmOutput`] into a [`GameState`].
pub fn parse_vlm_output(output: &VlmOutput) -> Result<GameState, ParseError> {
    let json = extract_json_object(&output.text).ok_or(ParseError::NoJson)?;
    let state: GameState =
        serde_json::from_str(&json).map_err(|e| ParseError::Malformed(e.to_string()))?;
    validate(&state)?;
    Ok(state)
}

/// Extract the first balanced JSON object from model output, tolerating
/// markdown fences and stray prose around the JSON.
fn extract_json_object(text: &str) -> Option<String> {
    // Fast path: the whole text is a JSON object.
    if let Ok(value) = serde_json::from_str::<serde_json::Value>(text.trim()) {
        if value.is_object() {
            return Some(text.trim().to_string());
        }
    }

    // Fallback: scan for the first '{' and match braces, respecting strings.
    let bytes = text.as_bytes();
    let start = bytes.iter().position(|&b| b == b'{')?;
    let mut depth = 0usize;
    let mut in_string = false;
    let mut escaped = false;

    for (i, &b) in bytes[start..].iter().enumerate() {
        if in_string {
            if escaped {
                escaped = false;
            } else if b == b'\\' {
                escaped = true;
            } else if b == b'"' {
                in_string = false;
            }
            continue;
        }
        match b {
            b'"' => in_string = true,
            b'{' => depth += 1,
            b'}' => {
                depth -= 1;
                if depth == 0 {
                    return Some(text[start..start + i + 1].to_string());
                }
            }
            _ => {}
        }
    }
    None
}

/// Validate game-state invariants that would indicate hallucination.
fn validate(state: &GameState) -> Result<(), ParseError> {
    if state.hero_cards.len() > 2 {
        return Err(ParseError::InvalidState(format!(
            "hero cannot hold more than 2 cards, got {}",
            state.hero_cards.len()
        )));
    }

    let expected = state.game_phase.expected_board_cards();
    if state.game_phase != GamePhase::Lobby && state.board.len() > expected {
        return Err(ParseError::InvalidState(format!(
            "phase {:?} expects at most {} board cards, got {}",
            state.game_phase,
            expected,
            state.board.len()
        )));
    }

    // A state requiring action must offer at least one action.
    if state.action_required && state.available_actions.is_empty() {
        return Err(ParseError::InvalidState(
            "action_required is true but no actions are available".to_string(),
        ));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn output(text: &str) -> VlmOutput {
        VlmOutput {
            text: text.to_string(),
        }
    }

    const VALID_STATE: &str = r#"{
        "game_phase": "flop",
        "hero_cards": [{"rank": "A", "suit": "spades"}, {"rank": "K", "suit": "hearts"}],
        "board": [{"rank": "Q", "suit": "diamonds"}, {"rank": "7", "suit": "clubs"}, {"rank": "2", "suit": "spades"}],
        "pot_size": 1250,
        "to_call": 500,
        "hero_chips": 2500,
        "players": [{"name": "Hero", "chips": 2500, "last_action": "raise", "bet_amount": 500}],
        "action_required": true,
        "available_actions": ["fold", "call", "raise"]
    }"#;

    #[test]
    fn parses_clean_json() {
        let state = parse_vlm_output(&output(VALID_STATE)).expect("valid state");
        assert_eq!(state.game_phase, GamePhase::Flop);
        assert_eq!(state.hero_cards.len(), 2);
        assert_eq!(state.board.len(), 3);
        assert_eq!(state.pot_size, 1250);
        assert!(state.action_required);
    }

    #[test]
    fn tolerates_markdown_fences() {
        let fenced = format!("```json\n{VALID_STATE}\n```");
        let state = parse_vlm_output(&output(&fenced)).expect("fenced state");
        assert_eq!(state.game_phase, GamePhase::Flop);
    }

    #[test]
    fn tolerates_stray_prose() {
        let prose = format!("Here is the table state:\n{VALID_STATE}\nHope that helps!");
        let state = parse_vlm_output(&output(&prose)).expect("prose-wrapped state");
        assert_eq!(state.pot_size, 1250);
    }

    #[test]
    fn fills_defaults_for_missing_fields() {
        let minimal = r#"{"game_phase": "preflop"}"#;
        let state = parse_vlm_output(&output(minimal)).expect("minimal state");
        assert_eq!(state.game_phase, GamePhase::Preflop);
        assert!(state.hero_cards.is_empty());
        assert_eq!(state.pot_size, 0);
        assert!(!state.action_required);
    }

    #[test]
    fn rejects_non_json_output() {
        let err = parse_vlm_output(&output("I cannot see a table here.")).expect_err("must fail");
        assert_eq!(err, ParseError::NoJson);
    }

    #[test]
    fn rejects_too_many_hero_cards() {
        let bad = VALID_STATE.replace(
            "\"hero_cards\": [{\"rank\": \"A\", \"suit\": \"spades\"}, {\"rank\": \"K\", \"suit\": \"hearts\"}]",
            "\"hero_cards\": [{\"rank\":\"A\",\"suit\":\"spades\"},{\"rank\":\"K\",\"suit\":\"hearts\"},{\"rank\":\"Q\",\"suit\":\"clubs\"}]",
        );
        assert!(matches!(
            parse_vlm_output(&output(&bad)),
            Err(ParseError::InvalidState(_))
        ));
    }

    #[test]
    fn rejects_board_larger_than_phase_allows() {
        let bad = VALID_STATE.replace("\"game_phase\": \"flop\"", "\"game_phase\": \"preflop\"");
        assert!(matches!(
            parse_vlm_output(&output(&bad)),
            Err(ParseError::InvalidState(_))
        ));
    }

    #[test]
    fn rejects_action_required_without_actions() {
        let bad = VALID_STATE.replace(
            "\"available_actions\": [\"fold\", \"call\", \"raise\"]",
            "\"available_actions\": []",
        );
        assert!(matches!(
            parse_vlm_output(&output(&bad)),
            Err(ParseError::InvalidState(_))
        ));
    }

    #[test]
    fn expected_board_cards_by_phase() {
        assert_eq!(GamePhase::Lobby.expected_board_cards(), 0);
        assert_eq!(GamePhase::Preflop.expected_board_cards(), 0);
        assert_eq!(GamePhase::Flop.expected_board_cards(), 3);
        assert_eq!(GamePhase::Turn.expected_board_cards(), 4);
        assert_eq!(GamePhase::River.expected_board_cards(), 5);
        assert_eq!(GamePhase::Showdown.expected_board_cards(), 5);
    }
}
