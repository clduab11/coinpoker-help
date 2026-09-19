//! Parsing and validation of VLM output into a structured [`GameState`].
//!
//! Validates the JSON returned by the vision model and degrades gracefully:
//! callers keep the last valid state when parsing fails.

use std::collections::HashSet;

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
    pub pot_size: u32,
    pub to_call: u32,
    pub hero_chips: u32,
    #[serde(default)]
    pub min_raise_to: Option<u32>,
    #[serde(default)]
    pub max_raise_to: Option<u32>,
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
    validate_game_state(&state)?;
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
///
/// This is public so non-VLM inputs, such as stdin JSON, can enforce the same
/// contract before passing a state to downstream decision logic.
pub fn validate_game_state(state: &GameState) -> Result<(), ParseError> {
    if !matches!(state.hero_cards.len(), 0 | 2) {
        return Err(ParseError::InvalidState(format!(
            "hero must hold either 0 or exactly 2 cards, got {}",
            state.hero_cards.len()
        )));
    }

    if state.action_required && state.hero_cards.len() != 2 {
        return Err(ParseError::InvalidState(
            "actionable state requires exactly 2 hero cards".to_string(),
        ));
    }

    let expected = state.game_phase.expected_board_cards();
    if state.board.len() != expected {
        return Err(ParseError::InvalidState(format!(
            "phase {:?} expects exactly {} board cards, got {}",
            state.game_phase,
            expected,
            state.board.len()
        )));
    }

    let mut seen_cards = HashSet::new();
    for card in state.hero_cards.iter().chain(&state.board) {
        if !matches!(
            card.rank.as_str(),
            "A" | "K" | "Q" | "J" | "T" | "9" | "8" | "7" | "6" | "5" | "4" | "3" | "2"
        ) {
            return Err(ParseError::InvalidState(format!(
                "invalid card rank: {}",
                card.rank
            )));
        }
        if !matches!(
            card.suit.as_str(),
            "spades" | "hearts" | "diamonds" | "clubs"
        ) {
            return Err(ParseError::InvalidState(format!(
                "invalid card suit: {}",
                card.suit
            )));
        }
        if !seen_cards.insert((card.rank.as_str(), card.suit.as_str())) {
            return Err(ParseError::InvalidState(format!(
                "duplicate card: {} of {}",
                card.rank, card.suit
            )));
        }
    }

    let mut seen_names = HashSet::new();
    let mut hero = None;
    let mut active_opponent = false;
    for player in &state.players {
        let name = player.name.as_str();
        if name.trim().is_empty() {
            return Err(ParseError::InvalidState(
                "player names cannot be empty".to_string(),
            ));
        }
        if name != name.trim() {
            return Err(ParseError::InvalidState(format!(
                "player name cannot contain surrounding whitespace: {name:?}"
            )));
        }
        if !seen_names.insert(name) {
            return Err(ParseError::InvalidState(format!(
                "duplicate player name: {name}"
            )));
        }

        if name == "Hero" {
            hero = Some(player);
        } else if !matches!(
            player.last_action.as_deref(),
            Some(action) if action.eq_ignore_ascii_case("fold")
        ) {
            active_opponent = true;
        }
    }

    let mut seen_actions = HashSet::new();
    for action in &state.available_actions {
        if !matches!(
            action.as_str(),
            "fold" | "check" | "call" | "raise" | "allin"
        ) {
            return Err(ParseError::InvalidState(format!(
                "unknown available action: {action}"
            )));
        }
        if !seen_actions.insert(action.as_str()) {
            return Err(ParseError::InvalidState(format!(
                "duplicate available action: {action}"
            )));
        }
    }

    if state.action_required && matches!(state.game_phase, GamePhase::Lobby | GamePhase::Showdown) {
        return Err(ParseError::InvalidState(format!(
            "action cannot be required during {:?}",
            state.game_phase
        )));
    }

    if state.action_required {
        if hero.is_none() {
            return Err(ParseError::InvalidState(
                "actionable state requires a Hero player".to_string(),
            ));
        }
        if !active_opponent {
            return Err(ParseError::InvalidState(
                "actionable state requires at least one non-Hero player who has not folded"
                    .to_string(),
            ));
        }
        if state.pot_size == 0 {
            return Err(ParseError::InvalidState(
                "actionable state requires a positive pot".to_string(),
            ));
        }
        if state.hero_chips == 0 {
            return Err(ParseError::InvalidState(
                "actionable state requires a positive hero stack".to_string(),
            ));
        }
        if state.available_actions.is_empty() {
            return Err(ParseError::InvalidState(
                "action_required is true but no actions are available".to_string(),
            ));
        }

        let hero = hero.expect("checked above");
        let highest_opponent_bet = state
            .players
            .iter()
            .filter(|player| player.name != "Hero")
            .filter(|player| {
                !matches!(
                    player.last_action.as_deref(),
                    Some(action) if action.eq_ignore_ascii_case("fold")
                )
            })
            .map(|player| player.bet_amount)
            .max()
            .unwrap_or(0);
        let observed_to_call = highest_opponent_bet.saturating_sub(hero.bet_amount);
        if observed_to_call != state.to_call {
            return Err(ParseError::InvalidState(format!(
                "to_call {actual} is inconsistent with visible street contributions (expected {expected})",
                actual = state.to_call,
                expected = observed_to_call,
            )));
        }
    } else if !state.available_actions.is_empty() {
        return Err(ParseError::InvalidState(
            "available_actions must be empty when action_required is false".to_string(),
        ));
    }

    if let Some(hero) = hero {
        if hero.chips != state.hero_chips {
            return Err(ParseError::InvalidState(format!(
                "Hero player chips {} do not match hero_chips {}",
                hero.chips, state.hero_chips
            )));
        }
    }

    let has_check = seen_actions.contains("check");
    let has_call = seen_actions.contains("call");
    let has_fold = seen_actions.contains("fold");
    let has_raise = seen_actions.contains("raise");
    let has_all_in = seen_actions.contains("allin");

    if state.to_call == 0 {
        if has_call || has_fold {
            return Err(ParseError::InvalidState(
                "call and fold are only available when to_call is positive".to_string(),
            ));
        }
        if state.action_required && !has_check {
            return Err(ParseError::InvalidState(
                "actionable state with nothing to call must offer check".to_string(),
            ));
        }
    } else {
        if has_check {
            return Err(ParseError::InvalidState(
                "check is only available when to_call is zero".to_string(),
            ));
        }
        let short_all_in_call = has_all_in && state.hero_chips <= state.to_call;
        if state.action_required && !has_call && !short_all_in_call {
            return Err(ParseError::InvalidState(
                "actionable state with a positive to_call must offer call or a short all-in"
                    .to_string(),
            ));
        }
        if state.action_required && !has_fold {
            return Err(ParseError::InvalidState(
                "actionable state with a positive to_call must offer fold".to_string(),
            ));
        }
    }

    if has_raise {
        let hero = hero
            .ok_or_else(|| ParseError::InvalidState("raise requires a Hero player".to_string()))?;
        let min_raise_to = state
            .min_raise_to
            .ok_or_else(|| ParseError::InvalidState("raise requires min_raise_to".to_string()))?;
        let max_raise_to = state
            .max_raise_to
            .ok_or_else(|| ParseError::InvalidState("raise requires max_raise_to".to_string()))?;

        if min_raise_to > max_raise_to {
            return Err(ParseError::InvalidState(
                "min_raise_to cannot exceed max_raise_to".to_string(),
            ));
        }

        let call_target = u64::from(hero.bet_amount) + u64::from(state.to_call);
        if u64::from(min_raise_to) <= call_target {
            return Err(ParseError::InvalidState(
                "min_raise_to must exceed Hero's current bet plus to_call".to_string(),
            ));
        }

        let all_in_target = u64::from(hero.bet_amount) + u64::from(state.hero_chips);
        if u64::from(max_raise_to) > all_in_target {
            return Err(ParseError::InvalidState(
                "max_raise_to cannot exceed Hero's current bet plus remaining stack".to_string(),
            ));
        }
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

    fn card(rank: &str, suit: &str) -> Card {
        Card {
            rank: rank.to_string(),
            suit: suit.to_string(),
        }
    }

    const VALID_STATE: &str = r#"{
        "game_phase": "flop",
        "hero_cards": [{"rank": "A", "suit": "spades"}, {"rank": "K", "suit": "hearts"}],
        "board": [{"rank": "Q", "suit": "diamonds"}, {"rank": "7", "suit": "clubs"}, {"rank": "2", "suit": "spades"}],
        "pot_size": 1250,
        "to_call": 500,
        "hero_chips": 2500,
        "min_raise_to": 1500,
        "max_raise_to": 3000,
        "players": [
            {"name": "Hero", "chips": 2500, "last_action": "raise", "bet_amount": 500},
            {"name": "Villain", "chips": 3200, "last_action": "call", "bet_amount": 1000}
        ],
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
    fn fills_defaults_for_optional_fields() {
        let minimal = r#"{
            "game_phase": "preflop",
            "pot_size": 0,
            "to_call": 0,
            "hero_chips": 0,
            "players": [
                {"name": "Hero", "chips": 0},
                {"name": "Villain", "chips": 1000}
            ]
        }"#;
        let state = parse_vlm_output(&output(minimal)).expect("minimal state");
        assert_eq!(state.game_phase, GamePhase::Preflop);
        assert!(state.hero_cards.is_empty());
        assert_eq!(state.min_raise_to, None);
        assert_eq!(state.max_raise_to, None);
        assert!(!state.action_required);
    }

    #[test]
    fn requires_critical_numeric_fields_during_deserialization() {
        for field in ["pot_size", "to_call", "hero_chips"] {
            let mut value: serde_json::Value =
                serde_json::from_str(VALID_STATE).expect("valid fixture JSON");
            value.as_object_mut().expect("fixture object").remove(field);
            let text = serde_json::to_string(&value).expect("serialize fixture");

            assert!(matches!(
                parse_vlm_output(&output(&text)),
                Err(ParseError::Malformed(message)) if message.contains(field)
            ));
        }
    }

    #[test]
    fn rejects_non_json_output() {
        let err = parse_vlm_output(&output("I cannot see a table here.")).expect_err("must fail");
        assert_eq!(err, ParseError::NoJson);
    }

    #[test]
    fn rejects_invalid_hero_card_counts() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_cards.pop();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("0 or exactly 2")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_cards.push(card("Q", "clubs"));
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("0 or exactly 2")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_cards.clear();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("requires exactly 2")
        ));

        state.action_required = false;
        state.available_actions.clear();
        validate_game_state(&state).expect("zero hero cards are valid when no action is required");
    }

    #[test]
    fn rejects_board_inconsistent_with_phase() {
        let preflop_with_board =
            VALID_STATE.replace("\"game_phase\": \"flop\"", "\"game_phase\": \"preflop\"");
        assert!(matches!(
            parse_vlm_output(&output(&preflop_with_board)),
            Err(ParseError::InvalidState(_))
        ));

        let flop_without_board = VALID_STATE.replace(
            "\"board\": [{\"rank\": \"Q\", \"suit\": \"diamonds\"}, {\"rank\": \"7\", \"suit\": \"clubs\"}, {\"rank\": \"2\", \"suit\": \"spades\"}]",
            "\"board\": []",
        );
        assert!(matches!(
            parse_vlm_output(&output(&flop_without_board)),
            Err(ParseError::InvalidState(_))
        ));

        let lobby_with_board =
            VALID_STATE.replace("\"game_phase\": \"flop\"", "\"game_phase\": \"lobby\"");
        assert!(matches!(
            parse_vlm_output(&output(&lobby_with_board)),
            Err(ParseError::InvalidState(_))
        ));
    }

    #[test]
    fn validates_exact_board_count_for_every_phase() {
        let phases = [
            GamePhase::Lobby,
            GamePhase::Preflop,
            GamePhase::Flop,
            GamePhase::Turn,
            GamePhase::River,
            GamePhase::Showdown,
        ];
        let deck = [
            card("Q", "diamonds"),
            card("7", "clubs"),
            card("2", "spades"),
            card("9", "hearts"),
            card("J", "clubs"),
        ];

        for phase in phases {
            let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
            state.game_phase = phase;
            state.action_required = false;
            state.available_actions.clear();
            state.board = deck[..phase.expected_board_cards()].to_vec();
            validate_game_state(&state).expect("exact board count is valid");

            if state.board.is_empty() {
                state.board.push(deck[0].clone());
            } else {
                state.board.pop();
            }
            assert!(matches!(
                validate_game_state(&state),
                Err(ParseError::InvalidState(message)) if message.contains("board cards")
            ));
        }
    }

    #[test]
    fn rejects_actionable_state_without_positive_pot_stack_or_actions() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.pot_size = 0;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("positive pot")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_chips = 0;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("positive hero stack")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions.clear();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("no actions")
        ));
    }

    #[test]
    fn requires_hero_and_an_active_opponent() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players.remove(0);
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("Hero player")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players[1].last_action = Some("fold".to_string());
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("has not folded")
        ));
    }

    #[test]
    fn rejects_empty_whitespace_padded_and_duplicate_player_names() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players[1].name = "  ".to_string();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("empty")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players[0].name = " Hero ".to_string();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("surrounding whitespace")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players.push(PlayerState {
            name: "Villain".to_string(),
            chips: 1000,
            last_action: None,
            bet_amount: 0,
        });
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("duplicate player name")
        ));
    }

    #[test]
    fn rejects_mismatched_hero_stack_fields() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players[0].chips -= 1;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("do not match hero_chips")
        ));
    }

    #[test]
    fn enforces_available_action_consistency() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions = vec!["call".to_string(), "raise".to_string()];
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("must offer fold")
        ));

        state.available_actions = vec!["fold".to_string(), "raise".to_string()];
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("must offer call")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions.push("check".to_string());
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("check is only")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.to_call = 0;
        state.players[1].bet_amount = state.players[0].bet_amount;
        state.available_actions = vec!["check".to_string(), "raise".to_string()];
        validate_game_state(&state).expect("check is valid when nothing is owed");

        state.available_actions = vec!["raise".to_string()];
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("must offer check")
        ));

        state.available_actions = vec!["check".to_string(), "fold".to_string()];
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("only available")
        ));
    }

    #[test]
    fn validates_raise_bounds() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.min_raise_to = None;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("min_raise_to")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.max_raise_to = None;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("max_raise_to")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.min_raise_to = Some(3000);
        state.max_raise_to = Some(2500);
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("cannot exceed")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.min_raise_to = Some(1000);
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("current bet plus to_call")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.max_raise_to = Some(3001);
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("remaining stack")
        ));
    }

    #[test]
    fn rejects_invalid_card_rank_and_suit() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_cards[0].rank = "1".to_string();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("rank")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.board[0].suit = "stars".to_string();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("suit")
        ));
    }

    #[test]
    fn rejects_duplicate_cards_across_hero_and_board() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.board[0] = state.hero_cards[0].clone();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("duplicate card")
        ));
    }

    #[test]
    fn rejects_unknown_and_duplicate_available_actions() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions.push("wait".to_string());
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("unknown")
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions.push("call".to_string());
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState(message)) if message.contains("duplicate")
        ));
    }

    #[test]
    fn rejects_action_required_in_lobby_and_showdown() {
        for phase in [GamePhase::Lobby, GamePhase::Showdown] {
            let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
            state.game_phase = phase;
            state.board = match phase {
                GamePhase::Lobby => vec![],
                GamePhase::Showdown => vec![
                    card("Q", "diamonds"),
                    card("7", "clubs"),
                    card("2", "spades"),
                    card("9", "hearts"),
                    card("J", "clubs"),
                ],
                _ => unreachable!(),
            };

            assert!(matches!(
                validate_game_state(&state),
                Err(ParseError::InvalidState(message)) if message.contains("action cannot")
            ));
        }
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
