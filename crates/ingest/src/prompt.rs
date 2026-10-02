//! Classification-first screenshot prompts and a strict screen envelope.
//!
//! A window is not assumed to be a poker table. Poker extraction happens only
//! after classification, and missing data never becomes a fabricated decision
//! or an empty-card marker for a new hand.

/// System prompt establishing classification, visibility, and poker contracts.
pub const SYSTEM_PROMPT: &str = r#"Classify the screenshot first. It may show a lobby, a poker table, another application window, or unreadable content. Do not assume that the screenshot is a table.
Return ONLY the JSON object, with no markdown fences, no commentary, and no trailing text.

Classification rules:
- screen_kind must be one of: lobby, poker_table, other_coin_poker_window, unknown.
- lobby means a visible CoinPoker lobby or game/tournament listing, not a live table view.
- poker_table means a visible live poker table with seats and a board/pot region. A table listing, card icon, thumbnail, title, or logo alone is not enough.
- An empty hero seat is still a poker_table. A game label at the top left of the felt, such as NLH followed by a table id, marks that live table. The same text in a listing row is still a lobby. Do not copy the table id into the JSON.
- other_coin_poker_window means an identifiable CoinPoker window that is neither a lobby nor a table, such as settings, cashier, or a dialog.
- unknown means the screen cannot be reliably classified or is not identifiable as a CoinPoker screen.
- For lobby, other_coin_poker_window, and unknown, return state as null. Do not invent a GameState for a non-table screen. No table recommendations are permitted for non-table screens.
- Do not provide poker advice or recommendations; this task only describes what is visible.

Envelope and evidence rules:
- Always emit every envelope field: screen_kind, evidence, state. Every evidence field is a required boolean, not a score or probability.
- table_layout: a live table layout with seats is visible, not just a lobby/list/preview.
- hero_cards: both hero cards are visible and readable. False can mean visibly absent or unreadable; distinguish these with readable and state.
- board_area: the board region is visible, including an explicitly empty preflop board.
- pot: the pot display is visible and its amount readable, including a visibly zero pot.
- action_controls: current hero action controls are visible and readable, not merely a menu or disabled controls.
- readable: relevant classification/table content can be read without guessing. For a table, all data needed for the supplied state must be readable.
- These booleans report your observations; they are not independent proof of a table.
- If table content or any critical card/value is unreadable, set readable to false and state to null. Never use missing data to manufacture an empty non-action preflop state.
- An unambiguously empty preflop table may have hero_cards false and action_controls false while readable is true. Only explicitly visible absence permits empty card arrays. Blinds may already be posted.

Poker state rules (only for poker_table with a non-null state):
- Always emit every state and player field shown in the table example, including null values. Never guess or fabricate cards, chip amounts, players, actions, or raise bounds.
- game_phase is one of: preflop, flop, turn, river, showdown. Lobby is a screen_kind, not a table game_phase.
- Cards use short rank names: A, K, Q, J, T, 9..2. Suits are one of: spades, hearts, diamonds, clubs. No card can appear twice across hero_cards and board.
- hero_cards must contain exactly two readable cards, or an empty array only when visibly absent and action_required is false.
- When Hero is not seated, leave hero_cards empty, set action_required false, and still report every visible community card.
- Board counts are exact: preflop 0, flop 3, turn 4, river 5, showdown 5. Preserve the left-to-right board order and hero-card order.
- All numeric amounts are integers in chips (no commas, no decimals). Zero means visibly zero, not unknown. If an amount cannot be read exactly, use readable false and state null instead of filling in a default.
- Pseudo-anonymize players: use Hero for the clearly identifiable hero and Seat1, Seat2, etc. for other seats. Assign seat numbers by fixed clockwise screen position starting at the topmost seat; do not renumber after folds or empty seats. Never transcribe nicknames, account identifiers, or other personal data. Emit Hero first, then the other players in seat order.
- Player chips are remaining stacks; Hero's chips must equal hero_chips. bet_amount is that player's contribution on the current street, not their stack or total hand contribution. last_action is a visible action or null when not shown.
- action_required is true only when it is the hero's turn to act and every critical decision value is readable: both hero cards, the full board for the phase, pot_size, to_call, hero_chips, Hero's current bet, at least one active opponent, and the offered actions (including both raise bounds when raise is offered).
- An actionable state requires a positive pot and hero stack, one Hero player, at least one non-Hero player who has not folded, unique player names, and nonempty offered actions.
- When it is not Hero's turn, set action_required to false and available_actions to an empty array. Showdown never requires action.
- available_actions lists only the actions currently offered to the hero: fold, check, call, raise, allin. Do not repeat actions.
- to_call must equal the highest non-folded opponent street contribution minus Hero's current bet, floored at zero. With to_call zero, offer check and never fold/call. With positive to_call, offer fold plus call (or allin for a short all-in call), and never check. Do not fabricate an action to satisfy these rules; unreadable or inconsistent controls require readable false and state null.
- min_raise_to and max_raise_to are integer raise-to totals when raise is offered; otherwise use null. Both bounds must be readable when raise is offered. min_raise_to must exceed Hero's current bet plus to_call and cannot exceed max_raise_to. max_raise_to cannot exceed Hero's current bet plus remaining stack.

Non-table envelope example (illustrative, not a classification of the attached image):
{
  "screen_kind": "unknown",
  "evidence": {
    "table_layout": false,
    "hero_cards": false,
    "board_area": false,
    "pot": false,
    "action_controls": false,
    "readable": false
  },
  "state": null
}

Table envelope example (illustrative only; do not copy these cards or values):
{
  "screen_kind": "poker_table",
  "evidence": {
    "table_layout": true,
    "hero_cards": true,
    "board_area": true,
    "pot": true,
    "action_controls": true,
    "readable": true
  },
  "state": {
    "game_phase": "flop",
    "hero_cards": [{"rank": "A", "suit": "spades"}, {"rank": "K", "suit": "hearts"}],
    "board": [{"rank": "Q", "suit": "diamonds"}, {"rank": "7", "suit": "clubs"}, {"rank": "2", "suit": "spades"}],
    "pot_size": 2000,
    "to_call": 500,
    "hero_chips": 2500,
    "min_raise_to": 1500,
    "max_raise_to": 3000,
    "players": [
      {"name": "Hero", "chips": 2500, "last_action": "call", "bet_amount": 500},
      {"name": "Seat1", "chips": 3200, "last_action": "raise", "bet_amount": 1000}
    ],
    "action_required": true,
    "available_actions": ["fold", "call", "raise"]
  }
}"#;

/// The image is attached separately by the VLM backend. This text deliberately
/// does not pre-classify it as a table or request poker data for non-table screens.
pub fn build_analysis_prompt() -> String {
    "Classify this screenshot first, then return the JSON screen envelope exactly as specified in the system prompt. Use state null for non-table screens or unreadable table data; do not assume a poker table."
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::{validate_game_state, GamePhase, GameState};
    use serde_json::Value;

    fn example(label: &str) -> Value {
        let (_, text) = SYSTEM_PROMPT.split_once(label).expect("example heading");
        serde_json::Deserializer::from_str(text.trim_start())
            .into_iter::<Value>()
            .next()
            .expect("example JSON")
            .expect("valid example JSON")
    }

    #[test]
    fn prompts_classify_first_without_assuming_a_table() {
        assert!(SYSTEM_PROMPT.starts_with("Classify the screenshot first."));
        assert!(SYSTEM_PROMPT.contains("Do not assume that the screenshot is a table"));
        assert!(SYSTEM_PROMPT.contains("lobby, poker_table, other_coin_poker_window, unknown"));
        assert!(
            SYSTEM_PROMPT.contains("No table recommendations are permitted for non-table screens")
        );
        let prompt = build_analysis_prompt();
        assert!(prompt.starts_with("Classify this screenshot first"));
        assert!(prompt.contains("JSON screen envelope"));
        assert!(prompt.contains("state null for non-table screens"));
        assert!(!prompt.contains("this poker table screenshot"));
    }

    #[test]
    fn examples_specify_the_full_strict_screen_envelope() {
        assert!(SYSTEM_PROMPT.contains("Return ONLY the JSON object"));
        assert!(SYSTEM_PROMPT.contains("Always emit every envelope field"));
        assert!(SYSTEM_PROMPT.contains("Always emit every state and player field"));
        for label in [
            "Non-table envelope example (illustrative, not a classification of the attached image):",
            "Table envelope example (illustrative only; do not copy these cards or values):",
        ] {
            let envelope = example(label);
            assert_eq!(envelope.as_object().unwrap().len(), 3);
            assert!(envelope["screen_kind"].is_string());
            assert!(envelope.get("state").is_some());
            assert_eq!(envelope["evidence"].as_object().unwrap().len(), 6);
            for field in ["table_layout", "hero_cards", "board_area", "pot", "action_controls", "readable"] {
                assert!(envelope["evidence"][field].is_boolean(), "evidence {field}");
            }
        }
        let non_table = example("Non-table envelope example (illustrative, not a classification of the attached image):");
        assert_eq!(non_table["screen_kind"], "unknown");
        assert!(non_table["state"].is_null());
    }

    #[test]
    fn table_example_preserves_strict_poker_requirements() {
        let envelope = example(
            "Table envelope example (illustrative only; do not copy these cards or values):",
        );
        assert_eq!(envelope["screen_kind"], "poker_table");
        let poker = &envelope["state"];
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
        ] {
            assert!(poker.get(field).is_some(), "state field {field}");
        }
        let state: GameState =
            serde_json::from_value(poker.clone()).expect("complete poker example");
        validate_game_state(&state).expect("example must satisfy the unchanged poker validator");
        assert_eq!(state.game_phase, GamePhase::Flop);
        assert_eq!(state.hero_cards.len(), 2);
        assert_eq!(state.board.len(), 3);
        assert!(state.action_required);
        assert!(state.min_raise_to.is_some());
        assert!(state.max_raise_to.is_some());
        assert_eq!(
            state
                .players
                .iter()
                .map(|player| player.name.as_str())
                .collect::<Vec<_>>(),
            vec!["Hero", "Seat1"]
        );
    }

    #[test]
    fn unreadability_and_player_privacy_rules_are_explicit() {
        assert!(SYSTEM_PROMPT.contains("readable to false and state to null"));
        assert!(SYSTEM_PROMPT
            .contains("Never use missing data to manufacture an empty non-action preflop state"));
        assert!(SYSTEM_PROMPT
            .contains("set action_required to false and available_actions to an empty array"));
        assert!(SYSTEM_PROMPT.contains("Never guess or fabricate"));
        assert!(SYSTEM_PROMPT.contains("Zero means visibly zero, not unknown"));
        assert!(SYSTEM_PROMPT.contains("Never transcribe nicknames, account identifiers"));
        assert!(SYSTEM_PROMPT.contains("do not renumber after folds or empty seats"));
        assert!(SYSTEM_PROMPT.contains("preflop 0, flop 3, turn 4, river 5, showdown 5"));
        assert!(SYSTEM_PROMPT.contains("An empty hero seat is still a poker_table"));
        assert!(SYSTEM_PROMPT.contains("still report every visible community card"));
        assert!(SYSTEM_PROMPT.contains("Do not copy the table id into the JSON"));
    }
}
