//! Parsing and validation of VLM output into a structured [`GameState`].
//!
//! Validates the JSON returned by the vision model and degrades gracefully:
//! callers keep the last valid state when parsing fails.

use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::vlm::VlmOutput;

/// Errors produced while parsing or validating VLM output.
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum ParseError {
    /// No JSON object could be located in the model output.
    #[error("no-json")]
    NoJson,
    /// The JSON was malformed.
    #[error("malformed")]
    Malformed,
    /// The JSON does not match the required schema.
    #[error("schema")]
    Schema,
    /// The JSON parsed but violates game-state invariants.
    #[error("invalid-observation")]
    InvalidState,
    /// The board count contradicts the declared phase.
    #[error("board-count")]
    BoardCount,
    /// Hero cards or their visibility evidence are invalid.
    #[error("hero-cards")]
    HeroCards,
    /// Action flags, controls, or legal actions are inconsistent.
    #[error("action-required")]
    ActionRequired,
    /// The response ended before the JSON was complete.
    #[error("truncated")]
    Truncated,
}

impl ParseError {
    /// Closed diagnostic codes; never retain rejected fields or parser prose.
    pub const fn code(&self) -> &'static str {
        match self {
            Self::NoJson => "no-json",
            Self::Malformed => "malformed",
            Self::Schema => "schema",
            Self::InvalidState => "invalid-observation",
            Self::BoardCount => "board-count",
            Self::HeroCards => "hero-cards",
            Self::ActionRequired => "action-required",
            Self::Truncated => "truncated",
        }
    }
}

impl From<serde_json::Error> for ParseError {
    fn from(error: serde_json::Error) -> Self {
        match error.classify() {
            serde_json::error::Category::Data => Self::Schema,
            serde_json::error::Category::Eof => Self::Truncated,
            serde_json::error::Category::Syntax | serde_json::error::Category::Io => {
                Self::Malformed
            }
        }
    }
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
///
/// Derives `PartialEq` only: the optional `confidence` is an `f64`, which
/// has no `Eq` implementation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
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
    /// Model-reported confidence that this observation is correct (0.0..=1.0).
    ///
    /// VLM output is untrusted: the value is validated like every other
    /// field, and callers must suppress decisions when it is low.
    #[serde(default)]
    pub confidence: Option<f64>,
}

/// Parse and validate a [`VlmOutput`] into a [`GameState`].
pub fn parse_vlm_output(output: &VlmOutput) -> Result<GameState, ParseError> {
    let json = extract_json_object(&output.text).ok_or(ParseError::NoJson)?;
    let state: GameState = serde_json::from_str(&json).map_err(ParseError::from)?;
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
        return Err(ParseError::HeroCards);
    }

    if state.action_required && state.hero_cards.len() != 2 {
        return Err(ParseError::HeroCards);
    }

    let expected = state.game_phase.expected_board_cards();
    if state.board.len() != expected {
        return Err(ParseError::BoardCount);
    }

    // VLM output is untrusted: an out-of-range confidence is treated as a
    // hallucination indicator and rejected like any other invalid field.
    if let Some(confidence) = state.confidence {
        if !confidence.is_finite() || !(0.0..=1.0).contains(&confidence) {
            return Err(ParseError::InvalidState);
        }
    }

    let mut seen_cards = HashSet::new();
    for (index, card) in state.hero_cards.iter().chain(&state.board).enumerate() {
        let invalid_card = if index < state.hero_cards.len() {
            ParseError::HeroCards
        } else {
            ParseError::InvalidState
        };
        if !matches!(
            card.rank.as_str(),
            "A" | "K" | "Q" | "J" | "T" | "9" | "8" | "7" | "6" | "5" | "4" | "3" | "2"
        ) {
            return Err(invalid_card);
        }
        if !matches!(
            card.suit.as_str(),
            "spades" | "hearts" | "diamonds" | "clubs"
        ) {
            return Err(invalid_card);
        }
        if !seen_cards.insert((card.rank.as_str(), card.suit.as_str())) {
            return Err(invalid_card);
        }
    }

    let mut seen_names = HashSet::new();
    let mut hero = None;
    let mut active_opponent = false;
    for player in &state.players {
        let name = player.name.as_str();
        if name.trim().is_empty() {
            return Err(ParseError::InvalidState);
        }
        if name != name.trim() {
            return Err(ParseError::InvalidState);
        }
        if !seen_names.insert(name) {
            return Err(ParseError::InvalidState);
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
            return Err(ParseError::ActionRequired);
        }
        if !seen_actions.insert(action.as_str()) {
            return Err(ParseError::ActionRequired);
        }
    }

    if state.action_required && matches!(state.game_phase, GamePhase::Lobby | GamePhase::Showdown) {
        return Err(ParseError::ActionRequired);
    }

    if state.action_required {
        if hero.is_none() {
            return Err(ParseError::ActionRequired);
        }
        if !active_opponent {
            return Err(ParseError::ActionRequired);
        }
        if state.pot_size == 0 {
            return Err(ParseError::ActionRequired);
        }
        if state.hero_chips == 0 {
            return Err(ParseError::ActionRequired);
        }
        if state.available_actions.is_empty() {
            return Err(ParseError::ActionRequired);
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
            return Err(ParseError::InvalidState);
        }
    } else if !state.available_actions.is_empty() {
        return Err(ParseError::ActionRequired);
    }

    if let Some(hero) = hero {
        if hero.chips != state.hero_chips {
            return Err(ParseError::InvalidState);
        }
    }

    let has_check = seen_actions.contains("check");
    let has_call = seen_actions.contains("call");
    let has_fold = seen_actions.contains("fold");
    let has_raise = seen_actions.contains("raise");
    let has_all_in = seen_actions.contains("allin");

    if state.to_call == 0 {
        if has_call || has_fold {
            return Err(ParseError::ActionRequired);
        }
        if state.action_required && !has_check {
            return Err(ParseError::ActionRequired);
        }
    } else {
        if has_check {
            return Err(ParseError::ActionRequired);
        }
        let short_all_in_call = has_all_in && state.hero_chips <= state.to_call;
        if state.action_required && !has_call && !short_all_in_call {
            return Err(ParseError::ActionRequired);
        }
        if state.action_required && !has_fold {
            return Err(ParseError::ActionRequired);
        }
    }

    if has_raise {
        let hero = hero.ok_or(ParseError::InvalidState)?;
        let min_raise_to = state.min_raise_to.ok_or(ParseError::InvalidState)?;
        let max_raise_to = state.max_raise_to.ok_or(ParseError::InvalidState)?;

        if min_raise_to > max_raise_to {
            return Err(ParseError::InvalidState);
        }

        let call_target = u64::from(hero.bet_amount) + u64::from(state.to_call);
        if u64::from(min_raise_to) <= call_target {
            return Err(ParseError::InvalidState);
        }

        let all_in_target = u64::from(hero.bet_amount) + u64::from(state.hero_chips);
        if u64::from(max_raise_to) > all_in_target {
            return Err(ParseError::InvalidState);
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
                Err(ParseError::Schema)
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
            Err(ParseError::HeroCards)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_cards.push(card("Q", "clubs"));
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::HeroCards)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_cards.clear();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::HeroCards)
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
            Err(ParseError::BoardCount)
        ));

        let flop_without_board = VALID_STATE.replace(
            "\"board\": [{\"rank\": \"Q\", \"suit\": \"diamonds\"}, {\"rank\": \"7\", \"suit\": \"clubs\"}, {\"rank\": \"2\", \"suit\": \"spades\"}]",
            "\"board\": []",
        );
        assert!(matches!(
            parse_vlm_output(&output(&flop_without_board)),
            Err(ParseError::BoardCount)
        ));

        let lobby_with_board =
            VALID_STATE.replace("\"game_phase\": \"flop\"", "\"game_phase\": \"lobby\"");
        assert!(matches!(
            parse_vlm_output(&output(&lobby_with_board)),
            Err(ParseError::BoardCount)
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
                Err(ParseError::BoardCount)
            ));
        }
    }

    #[test]
    fn rejects_actionable_state_without_positive_pot_stack_or_actions() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.pot_size = 0;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_chips = 0;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions.clear();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));
    }

    #[test]
    fn requires_hero_and_an_active_opponent() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players.remove(0);
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players[1].last_action = Some("fold".to_string());
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));
    }

    #[test]
    fn rejects_empty_whitespace_padded_and_duplicate_player_names() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players[1].name = "  ".to_string();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players[0].name = " Hero ".to_string();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
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
            Err(ParseError::InvalidState)
        ));
    }

    #[test]
    fn rejects_mismatched_hero_stack_fields() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.players[0].chips -= 1;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));
    }

    #[test]
    fn enforces_available_action_consistency() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions = vec!["call".to_string(), "raise".to_string()];
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));

        state.available_actions = vec!["fold".to_string(), "raise".to_string()];
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions.push("check".to_string());
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.to_call = 0;
        state.players[1].bet_amount = state.players[0].bet_amount;
        state.available_actions = vec!["check".to_string(), "raise".to_string()];
        validate_game_state(&state).expect("check is valid when nothing is owed");

        state.available_actions = vec!["raise".to_string()];
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));

        state.available_actions = vec!["check".to_string(), "fold".to_string()];
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));
    }

    #[test]
    fn validates_raise_bounds() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.min_raise_to = None;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.max_raise_to = None;
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.min_raise_to = Some(3000);
        state.max_raise_to = Some(2500);
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.min_raise_to = Some(1000);
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.max_raise_to = Some(3001);
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));
    }

    #[test]
    fn rejects_invalid_card_rank_and_suit() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.hero_cards[0].rank = "1".to_string();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::HeroCards)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.board[0].suit = "stars".to_string();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));
    }

    #[test]
    fn rejects_duplicate_cards_across_hero_and_board() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.board[0] = state.hero_cards[0].clone();
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::InvalidState)
        ));
    }

    #[test]
    fn rejects_unknown_and_duplicate_available_actions() {
        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions.push("wait".to_string());
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
        ));

        let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        state.available_actions.push("call".to_string());
        assert!(matches!(
            validate_game_state(&state),
            Err(ParseError::ActionRequired)
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
                Err(ParseError::ActionRequired)
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

    #[test]
    fn confidence_defaults_to_none_and_deserializes_when_present() {
        let state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
        assert_eq!(state.confidence, None);

        let with_confidence = VALID_STATE.replace(
            "\"action_required\": true",
            "\"action_required\": true, \"confidence\": 0.85",
        );
        let state = parse_vlm_output(&output(&with_confidence)).expect("valid state");
        assert_eq!(state.confidence, Some(0.85));
    }

    #[test]
    fn rejects_out_of_range_confidence() {
        for bad in [1.5, -0.1, f64::NAN, f64::INFINITY] {
            let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
            state.confidence = Some(bad);
            assert!(matches!(
                validate_game_state(&state),
                Err(ParseError::InvalidState)
            ));
        }

        for good in [0.0, 0.5, 1.0] {
            let mut state: GameState = serde_json::from_str(VALID_STATE).expect("fixture");
            state.confidence = Some(good);
            validate_game_state(&state).expect("in-range confidence is valid");
        }
    }
}

#[cfg(test)]
mod snapshot_tests {
    use super::*;
    use crate::vlm::VlmOutput;

    fn output(text: &str) -> VlmOutput {
        VlmOutput {
            text: text.to_string(),
        }
    }

    #[test]
    fn parses_representative_vlm_json() {
        let json = r#"{
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

        let state = parse_vlm_output(&output(json)).expect("valid state");
        insta::assert_json_snapshot!(state);
    }

    #[test]
    fn parses_minimal_preflop_state() {
        let json = r#"{
            "game_phase": "preflop",
            "pot_size": 0,
            "to_call": 0,
            "hero_chips": 1000,
            "players": [
                {"name": "Hero", "chips": 1000},
                {"name": "Villain", "chips": 1000}
            ]
        }"#;

        let state = parse_vlm_output(&output(json)).expect("valid state");
        insta::assert_json_snapshot!(state);
    }

    #[test]
    fn parses_river_allin_state() {
        let json = r#"{
            "game_phase": "river",
            "hero_cards": [{"rank": "A", "suit": "spades"}, {"rank": "A", "suit": "hearts"}],
            "board": [
                {"rank": "A", "suit": "diamonds"},
                {"rank": "K", "suit": "clubs"},
                {"rank": "Q", "suit": "hearts"},
                {"rank": "J", "suit": "spades"},
                {"rank": "T", "suit": "clubs"}
            ],
            "pot_size": 5000,
            "to_call": 2000,
            "hero_chips": 2000,
            "min_raise_to": 9000,
            "max_raise_to": 7000,
            "players": [
                {"name": "Hero", "chips": 2000, "last_action": "call", "bet_amount": 5000},
                {"name": "Villain", "chips": 5000, "last_action": "raise", "bet_amount": 7000}
            ],
            "action_required": true,
            "available_actions": ["fold", "call", "allin"]
        }"#;

        let state = parse_vlm_output(&output(json)).expect("valid state");
        insta::assert_json_snapshot!(state);
    }
}

#[cfg(test)]
mod proptests {
    use super::*;
    use proptest::prelude::*;

    fn arb_card() -> impl Strategy<Value = Card> {
        prop_oneof![
            Just("A"),
            Just("K"),
            Just("Q"),
            Just("J"),
            Just("T"),
            Just("9"),
            Just("8"),
            Just("7"),
            Just("6"),
            Just("5"),
            Just("4"),
            Just("3"),
            Just("2"),
        ]
        .prop_flat_map(|rank| {
            prop_oneof![
                Just("spades"),
                Just("hearts"),
                Just("diamonds"),
                Just("clubs"),
            ]
            .prop_map(move |suit| Card {
                rank: rank.to_string(),
                suit: suit.to_string(),
            })
        })
    }

    fn arb_game_phase() -> impl Strategy<Value = GamePhase> {
        prop_oneof![
            Just(GamePhase::Lobby),
            Just(GamePhase::Preflop),
            Just(GamePhase::Flop),
            Just(GamePhase::Turn),
            Just(GamePhase::River),
            Just(GamePhase::Showdown),
        ]
    }

    fn arb_player_state() -> impl Strategy<Value = PlayerState> {
        (
            "[a-zA-Z][a-zA-Z0-9_]{0,15}",
            0u32..1_000_000,
            prop::option::of("[a-zA-Z]{0,10}"),
            0u32..1_000_000,
        )
            .prop_map(|(name, chips, last_action, bet_amount)| PlayerState {
                name,
                chips,
                last_action,
                bet_amount,
            })
    }

    fn arb_game_state() -> impl Strategy<Value = GameState> {
        (
            arb_game_phase(),
            prop::collection::vec(arb_card(), 0..=2),
            prop::collection::vec(arb_card(), 0..=5),
            0u32..1_000_000,
            0u32..1_000_000,
            0u32..1_000_000,
            prop::option::of(0u32..1_000_000),
            prop::option::of(0u32..1_000_000),
            prop::collection::vec(arb_player_state(), 0..=9),
            prop::bool::ANY,
            prop::collection::vec(
                prop_oneof![
                    Just("fold".to_string()),
                    Just("check".to_string()),
                    Just("call".to_string()),
                    Just("raise".to_string()),
                    Just("allin".to_string()),
                ],
                0..=5,
            ),
        )
            .prop_map(
                |(
                    game_phase,
                    hero_cards,
                    board,
                    pot_size,
                    to_call,
                    hero_chips,
                    min_raise_to,
                    max_raise_to,
                    players,
                    action_required,
                    available_actions,
                )| {
                    GameState {
                        game_phase,
                        hero_cards,
                        board,
                        pot_size,
                        to_call,
                        hero_chips,
                        min_raise_to,
                        max_raise_to,
                        players,
                        action_required,
                        available_actions,
                        confidence: None,
                    }
                },
            )
            // Layer the optional confidence on top so the roundtrip test
            // also covers `Some` values without growing the tuple.
            .prop_flat_map(|state| {
                prop::option::of(0.0f64..=1.0).prop_map(move |confidence| GameState {
                    confidence,
                    ..state.clone()
                })
            })
    }

    proptest! {
        #[test]
        fn serialize_deserialize_roundtrip(state in arb_game_state()) {
            let json = serde_json::to_string(&state).unwrap();
            let deserialized: GameState = serde_json::from_str(&json).unwrap();
            prop_assert_eq!(state, deserialized);
        }

        #[test]
        fn validate_game_state_is_idempotent(state in arb_game_state()) {
            let result1 = validate_game_state(&state);
            let result2 = validate_game_state(&state);
            prop_assert_eq!(result1, result2);
        }

        #[test]
        fn valid_states_pass_validation(
            phase in arb_game_phase(),
            pot in 1..=1_000_000u32,
            to_call in 0..=1_000_000u32,
            hero_chips in 1..=1_000_000u32,
        ) {
            // This synthetic state models a passive observation of lobby,
            // preflop, and showdown, and an actionable postflop street. Skip
            // combinations it does not represent.
            if to_call > 0 && matches!(phase, GamePhase::Lobby | GamePhase::Preflop | GamePhase::Showdown) {
                return Ok(());
            }

            let expected_board = phase.expected_board_cards();
            let mut board = Vec::new();
            let ranks = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"];
            let suits = ["spades", "hearts", "diamonds", "clubs"];
            'board: for suit in suits {
                for rank in ranks {
                    if board.len() >= expected_board {
                        break 'board;
                    }
                    board.push(Card {
                        rank: rank.to_string(),
                        suit: suit.to_string(),
                    });
                }
            }

            // Non-spade hole cards never collide with the spade-only board above.
            let hero_cards = if matches!(phase, GamePhase::Lobby | GamePhase::Preflop) {
                vec![]
            } else {
                vec![
                    Card { rank: "A".to_string(), suit: "hearts".to_string() },
                    Card { rank: "K".to_string(), suit: "hearts".to_string() },
                ]
            };

            let state = GameState {
                game_phase: phase,
                hero_cards,
                board,
                pot_size: pot,
                to_call,
                hero_chips,
                min_raise_to: if to_call > 0 { Some(pot * 2) } else { None },
                max_raise_to: if to_call > 0 { Some(hero_chips + to_call) } else { None },
                players: vec![
                    PlayerState {
                        name: "Hero".to_string(),
                        chips: hero_chips,
                        last_action: if to_call > 0 { Some("call".to_string()) } else { None },
                        bet_amount: 0,
                    },
                    PlayerState {
                        name: "Villain".to_string(),
                        chips: 10_000,
                        last_action: if to_call > 0 { Some("raise".to_string()) } else { None },
                        bet_amount: to_call,
                    },
                ],
                action_required: to_call > 0,
                available_actions: if to_call > 0 {
                    vec!["fold".to_string(), "call".to_string()]
                } else {
                    vec![]
                },
                confidence: None,
            };

            let result = validate_game_state(&state);
            prop_assert!(result.is_ok(), "valid state rejected: {:?}", result);
        }
    }
}
