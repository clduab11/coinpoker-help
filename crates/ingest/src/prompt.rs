//! System and analysis prompts for the vision model.
//!
//! Instructs the VLM to return strict JSON describing the visible table
//! state (cards, pot, stacks, actions, phase). The prompt is paired with a
//! low sampling temperature (see `VlmConfig`) for deterministic, parseable
//! output.

/// System prompt establishing the analysis task and the strict JSON contract.
pub const SYSTEM_PROMPT: &str = "\
You are a poker table state analyzer. You receive a screenshot of an online \
poker table and must describe the visible state as a single JSON object. \
Return ONLY the JSON object, with no markdown fences, no commentary, and no \
trailing text.

Rules:
- Cards use short rank names: A, K, Q, J, T, 9..2.
- Suits are one of: spades, hearts, diamonds, clubs.
- game_phase is one of: lobby, preflop, flop, turn, river, showdown.
- All numeric amounts are integers in chips (no commas, no decimals).
- Always emit every field shown in the JSON schema, even when its value is unknown.
- If a value is not visible, use 0 for numbers, null for unknown raise bounds, \
and empty arrays for cards/actions that cannot be read.
- Never guess or fabricate cards, chip amounts, players, actions, or raise bounds.
- action_required is true only when it is the hero's turn to act and every \
critical decision value is readable: both hero cards, the full board for the \
phase, pot_size, to_call, hero_chips, Hero's current bet, at least one active \
opponent, and the offered actions (including both raise bounds when raise is offered).
- If any critical value or card is unreadable, set action_required to false and \
available_actions to an empty array rather than fabricating a decision.
- available_actions lists only the actions currently offered to the hero \
(fold, check, call, raise, allin).
- min_raise_to and max_raise_to are integer raise-to totals when raise is offered; \
otherwise use null.

JSON schema:
{
  \"game_phase\": \"flop\",
  \"hero_cards\": [{\"rank\": \"A\", \"suit\": \"spades\"}, {\"rank\": \"K\", \"suit\": \"hearts\"}],
  \"board\": [{\"rank\": \"Q\", \"suit\": \"diamonds\"}, {\"rank\": \"7\", \"suit\": \"clubs\"}, {\"rank\": \"2\", \"suit\": \"spades\"}],
  \"pot_size\": 1250,
  \"to_call\": 500,
  \"hero_chips\": 2500,
  \"min_raise_to\": 1500,
  \"max_raise_to\": 3000,
  \"players\": [
    {\"name\": \"Hero\", \"chips\": 2500, \"last_action\": \"raise\", \"bet_amount\": 500},
    {\"name\": \"Villain\", \"chips\": 3200, \"last_action\": \"call\", \"bet_amount\": 1000}
  ],
  \"action_required\": true,
  \"available_actions\": [\"fold\", \"call\", \"raise\"]
}";

/// Build the user prompt that accompanies a screenshot.
///
/// The image is attached separately by the VLM backend; this is the text
/// portion of the multimodal request.
pub fn build_analysis_prompt() -> String {
    "Analyze this poker table screenshot and return the JSON state object \
     exactly as specified in the system prompt."
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn system_prompt_specifies_strict_json_contract() {
        assert!(SYSTEM_PROMPT.contains("Return ONLY the JSON object"));
        assert!(SYSTEM_PROMPT.contains("\"game_phase\""));
        assert!(SYSTEM_PROMPT.contains("\"action_required\""));
        assert!(SYSTEM_PROMPT.contains("\"available_actions\""));
        assert!(SYSTEM_PROMPT.contains("\"min_raise_to\""));
        assert!(SYSTEM_PROMPT.contains("\"max_raise_to\""));
        assert!(SYSTEM_PROMPT.contains("Always emit every field"));
        assert!(SYSTEM_PROMPT.contains("set action_required to false"));
        assert!(SYSTEM_PROMPT.contains("\"game_phase\": \"flop\""));
        assert!(SYSTEM_PROMPT.contains("\"board\": [{\"rank\": \"Q\""));
        assert!(SYSTEM_PROMPT.contains("\"name\": \"Hero\""));
        assert!(SYSTEM_PROMPT.contains("\"name\": \"Villain\""));
    }

    #[test]
    fn analysis_prompt_is_nonempty_and_directive() {
        let prompt = build_analysis_prompt();
        assert!(prompt.contains("screenshot"));
        assert!(prompt.contains("JSON"));
    }
}
