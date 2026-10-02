//! Screenshot classification and fail-closed admission to the poker pipeline.
//!
//! Model-reported evidence is not an independent measurement. Metadata supplies
//! vetoes, and deterministic frame inspection only rejects unusable captures; it
//! cannot recognize a poker table. Two matching, independently captured model
//! observations are required, not two alleged evidence sources from one image.

use serde::{de::IgnoredAny, Deserialize, Deserializer, Serialize};

use crate::capture::Frame;
use crate::discovery::TableIdentity;
use crate::parser::{validate_game_state, Card, GamePhase, GameState, ParseError, PlayerState};
use crate::state_machine::validate_transition;
use crate::vlm::VlmOutput;

/// Classification of the whole window, separate from a hand's poker phase.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScreenKind {
    Lobby,
    PokerTable,
    OtherCoinPokerWindow,
    Unknown,
}

/// Required, model-reported visibility claims, never confidence scores.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ScreenEvidence {
    pub table_layout: bool,
    /// Both hero cards are visible and readable (false when visibly absent).
    pub hero_cards: bool,
    /// The board region is visible, including an explicitly empty preflop board.
    pub board_area: bool,
    /// The pot display is readable, including a visibly zero pot.
    pub pot: bool,
    /// Current hero action controls are visible and readable.
    pub action_controls: bool,
    /// Relevant content is readable; missing/unreadable cards are not empty cards.
    pub readable: bool,
}

/// A screen envelope. Non-table payloads are discarded without parsing poker
/// fields. Table payloads have no implicit field defaults, unlike legacy stdin
/// deserialization. Use [`parse_screen_output`] for semantic validation as well.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(from = "ScreenEnvelope")]
pub struct ScreenObservation {
    pub screen_kind: ScreenKind,
    pub evidence: ScreenEvidence,
    pub state: Option<GameState>,
}

#[derive(Deserialize)]
#[serde(tag = "screen_kind", rename_all = "snake_case", deny_unknown_fields)]
enum ScreenEnvelope {
    Lobby {
        evidence: ScreenEvidence,
        #[serde(rename = "state")]
        _state: Option<IgnoredAny>,
    },
    PokerTable {
        evidence: ScreenEvidence,
        #[serde(deserialize_with = "required_nullable")]
        state: Option<TableState>,
    },
    OtherCoinPokerWindow {
        evidence: ScreenEvidence,
        #[serde(rename = "state")]
        _state: Option<IgnoredAny>,
    },
    Unknown {
        evidence: ScreenEvidence,
        #[serde(rename = "state")]
        _state: Option<IgnoredAny>,
    },
}

impl From<ScreenEnvelope> for ScreenObservation {
    fn from(envelope: ScreenEnvelope) -> Self {
        let (screen_kind, evidence, state) = match envelope {
            ScreenEnvelope::Lobby { evidence, .. } => (ScreenKind::Lobby, evidence, None),
            ScreenEnvelope::PokerTable { evidence, state } => {
                (ScreenKind::PokerTable, evidence, state.map(|state| state.0))
            }
            ScreenEnvelope::OtherCoinPokerWindow { evidence, .. } => {
                (ScreenKind::OtherCoinPokerWindow, evidence, None)
            }
            ScreenEnvelope::Unknown { evidence, .. } => (ScreenKind::Unknown, evidence, None),
        };
        Self {
            screen_kind,
            evidence,
            state,
        }
    }
}

// Remote derives enforce the screen schema without changing GameState's stdin
// contract. In particular, missing action flags, bets, or cards cannot silently
// become false/zero/empty and masquerade as an inter-hand marker.
#[derive(Deserialize)]
#[serde(remote = "GameState", deny_unknown_fields)]
struct CompleteGameState {
    game_phase: GamePhase,
    hero_cards: Vec<Card>,
    board: Vec<Card>,
    pot_size: u32,
    to_call: u32,
    hero_chips: u32,
    #[serde(deserialize_with = "required_nullable")]
    min_raise_to: Option<u32>,
    #[serde(deserialize_with = "required_nullable")]
    max_raise_to: Option<u32>,
    #[serde(deserialize_with = "complete_players")]
    players: Vec<PlayerState>,
    action_required: bool,
    available_actions: Vec<String>,
}

#[derive(Deserialize)]
#[serde(remote = "PlayerState", deny_unknown_fields)]
struct CompletePlayerState {
    name: String,
    chips: u32,
    #[serde(deserialize_with = "required_nullable")]
    last_action: Option<String>,
    bet_amount: u32,
}

#[derive(Deserialize)]
struct TableState(#[serde(with = "CompleteGameState")] GameState);

#[derive(Deserialize)]
struct TablePlayer(#[serde(with = "CompletePlayerState")] PlayerState);

fn required_nullable<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::deserialize(deserializer)
}

fn complete_players<'de, D>(deserializer: D) -> Result<Vec<PlayerState>, D::Error>
where
    D: Deserializer<'de>,
{
    Vec::<TablePlayer>::deserialize(deserializer)
        .map(|players| players.into_iter().map(|player| player.0).collect())
}

/// Parse the entire trimmed response, optionally enclosed in one JSON/plain
/// markdown fence. Prose, multiple objects, partial envelopes, and guessed
/// defaults are rejected. A non-table screen never requires a poker state.
/// An unreadable table may explicitly carry `state: null`, but cannot be admitted.
pub fn parse_screen_output(output: &VlmOutput) -> Result<ScreenObservation, ParseError> {
    let text = output.text.trim();
    let json = if let Some(fenced) = text.strip_prefix("```") {
        let (language, body) = fenced.split_once('\n').ok_or(ParseError::Malformed)?;
        if !matches!(language.trim(), "" | "json") {
            return Err(ParseError::Malformed);
        }
        body.strip_suffix("```")
            .ok_or(ParseError::Malformed)?
            .trim()
    } else {
        text
    };
    if json.is_empty() {
        return Err(ParseError::NoJson);
    }
    let observation: ScreenObservation = serde_json::from_str(json).map_err(ParseError::from)?;
    validate_observation(&observation)?;
    Ok(observation)
}

fn has_table_evidence(evidence: &ScreenEvidence) -> bool {
    evidence.readable && evidence.table_layout && evidence.board_area && evidence.pot
}

fn validate_observation(observation: &ScreenObservation) -> Result<(), ParseError> {
    if observation.screen_kind != ScreenKind::PokerTable {
        return Ok(());
    }
    let Some(state) = observation.state.as_ref() else {
        return if observation.evidence.readable {
            Err(ParseError::InvalidState)
        } else {
            Ok(())
        };
    };
    validate_game_state(state)?;
    if state.game_phase == GamePhase::Lobby {
        return Err(ParseError::InvalidState);
    }
    if observation.evidence.hero_cards != (state.hero_cards.len() == 2) {
        return Err(ParseError::HeroCards);
    }
    if state.action_required
        && !(has_table_evidence(&observation.evidence)
            && observation.evidence.hero_cards
            && observation.evidence.action_controls)
    {
        return Err(ParseError::ActionRequired);
    }
    if !state
        .available_actions
        .iter()
        .any(|action| action == "raise")
        && (state.min_raise_to.is_some() || state.max_raise_to.is_some())
    {
        return Err(ParseError::InvalidState);
    }
    Ok(())
}

/// Hints supplied by discovery, not inferred again from model output.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MetadataEvidence {
    /// A CoinPoker candidate with no explicit title hint; not proof of a table.
    Candidate,
    /// An explicit table title is still only a hint and never bypasses consensus.
    TableTitle,
    /// An explicit lobby title vetoes even a consistent model-reported table.
    LobbyTitle,
    /// Metadata identifies a non-table window, not an eligible table candidate.
    Other,
}

/// A deterministic rejection check, not a table classifier or confidence score.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VisualEvidence {
    /// Passed basic buffer/size/nonblank checks. NOT proof of a table or readability.
    Plausible,
    Unreadable,
}

/// Reject malformed, sub-160x120, fully transparent, or uniform-color captures.
/// This coarse resolution floor is not calibrated to CoinPoker. Any nonuniform
/// visible RGB content above it is merely plausible; no colors, layouts, logos,
/// or synthetic poker-template heuristics are treated as positive evidence.
pub fn inspect_frame(frame: &Frame) -> VisualEvidence {
    if frame.validate().is_err() || frame.width < 160 || frame.height < 120 {
        return VisualEvidence::Unreadable;
    }
    let mut colors = frame
        .rgba
        .chunks_exact(4)
        .filter(|pixel| pixel[3] != 0)
        .map(|pixel| &pixel[..3]);
    match colors.next() {
        Some(first) if colors.any(|color| color != first) => VisualEvidence::Plausible,
        _ => VisualEvidence::Unreadable,
    }
}

/// Only an accepted, readable table carries a state. Rejections never return the
/// last accepted state as a fallback recommendation, even though it is retained
/// internally for checking continuity.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GateOutcome {
    pub kind: ScreenKind,
    pub accepted_state: Option<GameState>,
    /// Community cards agreed across two reads. This is not advice.
    pub visible_cards: Option<GameState>,
    pub reason: &'static str,
}

/// Consensus and temporal admission for a single window identity.
///
/// Each `observe` call MUST represent a fresh capture and VLM analysis from a
/// different generation; the caller owns that guarantee. Replaying one analysis
/// twice does not constitute independent evidence and cannot be detected by this
/// API. All GameState fields and all evidence flags must agree across at least two
/// consecutive eligible observations. Agreement is a safety filter, not ground truth.
#[derive(Default)]
pub struct TableGate {
    identity: Option<TableIdentity>,
    pending: Option<ScreenObservation>,
    accepted: Option<GameState>,
}

impl TableGate {
    pub fn new() -> Self {
        Self::default()
    }

    /// Forget both consensus and the accepted timeline (e.g. a deliberate reset).
    /// Unknown/unreadable observations instead break consensus without erasing
    /// continuity; they must not turn a late-hand -> preflop error into a new hand.
    pub fn reset(&mut self) {
        *self = Self::new();
    }

    /// Invalidate pending consensus without forgetting the accepted hand timeline.
    pub fn break_consensus(&mut self) {
        self.pending = None;
    }

    pub fn observe(
        &mut self,
        identity: &TableIdentity,
        observation: &ScreenObservation,
        metadata: MetadataEvidence,
        visual: VisualEvidence,
    ) -> GateOutcome {
        if self.identity.as_ref() != Some(identity) {
            self.reset();
            self.identity = Some(identity.clone());
        }
        match metadata {
            MetadataEvidence::LobbyTitle => {
                self.accepted = None;
                return self.reject(ScreenKind::Lobby, "lobby title; no table recommendations");
            }
            MetadataEvidence::Other => {
                self.accepted = None;
                return self.reject(
                    ScreenKind::OtherCoinPokerWindow,
                    "non-table metadata; no table recommendations",
                );
            }
            MetadataEvidence::Candidate | MetadataEvidence::TableTitle => {}
        }
        if visual == VisualEvidence::Unreadable {
            return self.reject(ScreenKind::Unknown, "capture is unreadable");
        }
        if !observation.evidence.readable {
            return self.reject(ScreenKind::Unknown, "screen content is unreadable");
        }
        match observation.screen_kind {
            ScreenKind::Unknown => {
                return self.reject(
                    ScreenKind::Unknown,
                    "unknown screen; no table recommendations",
                );
            }
            ScreenKind::Lobby | ScreenKind::OtherCoinPokerWindow => {
                if observation.evidence.table_layout {
                    return self.reject(
                        ScreenKind::Unknown,
                        "non-table classification conflicts with table evidence",
                    );
                }
                self.accepted = None;
                return self.reject(
                    observation.screen_kind,
                    "non-table screen; no table recommendations",
                );
            }
            ScreenKind::PokerTable => {}
        }
        // No real-image positive layout detector has been calibrated yet. A model
        // cannot promote an unidentified application window into a playable table,
        // even by repeating the same internally consistent hallucination.
        if metadata != MetadataEvidence::TableTitle {
            return self.reject(ScreenKind::PokerTable, "table-title-calibration-required");
        }
        // Revalidate even manually constructed observations, not just parsed JSON.
        if validate_observation(observation).is_err() {
            return self.reject(
                ScreenKind::Unknown,
                "table state or evidence is inconsistent",
            );
        }
        if !has_table_evidence(&observation.evidence) {
            return self.reject(ScreenKind::Unknown, "table evidence is incomplete");
        }
        let Some(state) = observation.state.as_ref() else {
            return self.reject(ScreenKind::Unknown, "table state is unavailable");
        };
        if let Some(previous) = &self.accepted {
            if let Err(reason) = validate_transition(previous, state) {
                return self.reject(ScreenKind::PokerTable, reason);
            }
        }
        let cards_agree = self
            .pending
            .as_ref()
            .is_some_and(|pending| same_visible_cards(pending, observation));
        let agrees = self.pending.as_ref() == Some(observation);
        self.pending = Some(observation.clone());
        if agrees {
            self.accepted = Some(state.clone());
            return GateOutcome {
                kind: ScreenKind::PokerTable,
                accepted_state: Some(state.clone()),
                visible_cards: Some(state.clone()),
                reason: "matching fresh table observations",
            };
        }
        if cards_agree {
            return GateOutcome {
                kind: ScreenKind::PokerTable,
                accepted_state: None,
                visible_cards: Some(state.clone()),
                reason: "community cards agree; no advice",
            };
        }
        GateOutcome {
            kind: ScreenKind::PokerTable,
            accepted_state: None,
            visible_cards: None,
            reason: "waiting for a second matching observation",
        }
    }

    fn reject(&mut self, kind: ScreenKind, reason: &'static str) -> GateOutcome {
        self.pending = None;
        GateOutcome {
            kind,
            accepted_state: None,
            visible_cards: None,
            reason,
        }
    }
}

fn same_visible_cards(pending: &ScreenObservation, observation: &ScreenObservation) -> bool {
    match (&pending.state, &observation.state) {
        (Some(pending), Some(observation)) => {
            pending.game_phase == observation.game_phase
                && pending.hero_cards == observation.hero_cards
                && pending.board == observation.board
                && pending.action_required == observation.action_required
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};

    fn identity() -> TableIdentity {
        TableIdentity {
            exe_name: "test.coinpoker".to_string(),
            process_id: 42,
            hwnd: 7,
        }
    }

    fn state(phase: GamePhase) -> GameState {
        let card = |rank: &str, suit: &str| Card {
            rank: rank.to_string(),
            suit: suit.to_string(),
        };
        let action = !matches!(phase, GamePhase::Lobby | GamePhase::Showdown);
        let state = GameState {
            game_phase: phase,
            hero_cards: vec![card("A", "spades"), card("K", "hearts")],
            board: [
                ("Q", "diamonds"),
                ("7", "clubs"),
                ("2", "spades"),
                ("9", "hearts"),
                ("J", "clubs"),
            ]
            .into_iter()
            .take(phase.expected_board_cards())
            .map(|(rank, suit)| card(rank, suit))
            .collect(),
            pot_size: 1250,
            to_call: 500,
            hero_chips: 2500,
            min_raise_to: action.then_some(1500),
            max_raise_to: action.then_some(3000),
            players: vec![
                PlayerState {
                    name: "Hero".to_string(),
                    chips: 2500,
                    last_action: Some("raise".to_string()),
                    bet_amount: 500,
                },
                PlayerState {
                    name: "Seat1".to_string(),
                    chips: 3200,
                    last_action: Some("call".to_string()),
                    bet_amount: 1000,
                },
            ],
            action_required: action,
            available_actions: if action {
                vec!["fold".to_string(), "call".to_string(), "raise".to_string()]
            } else {
                vec![]
            },
        };
        validate_game_state(&state).expect("valid fixture");
        state
    }

    fn table(state: GameState) -> ScreenObservation {
        ScreenObservation {
            screen_kind: ScreenKind::PokerTable,
            evidence: ScreenEvidence {
                table_layout: true,
                hero_cards: state.hero_cards.len() == 2,
                board_area: true,
                pot: true,
                action_controls: state.action_required,
                readable: true,
            },
            state: Some(state),
        }
    }

    fn non_table(kind: ScreenKind) -> ScreenObservation {
        ScreenObservation {
            screen_kind: kind,
            evidence: ScreenEvidence {
                table_layout: false,
                hero_cards: false,
                board_area: false,
                pot: false,
                action_controls: false,
                readable: true,
            },
            state: None,
        }
    }

    fn marker() -> ScreenObservation {
        let mut marker = state(GamePhase::Preflop);
        marker.hero_cards.clear();
        marker.action_required = false;
        marker.available_actions.clear();
        marker.min_raise_to = None;
        marker.max_raise_to = None;
        marker.to_call = 0;
        table(marker)
    }

    fn output(text: &str) -> VlmOutput {
        VlmOutput {
            text: text.to_string(),
        }
    }

    fn parse(value: &Value) -> Result<ScreenObservation, ParseError> {
        parse_screen_output(&output(&value.to_string()))
    }

    const REJECTED_SENTINEL: &str = "SYNTHETIC_REJECTED_FIELD_SENTINEL";

    fn assert_safe_category(value: &Value, category: &str) {
        let diagnostic = parse(value).expect_err("invalid observation").to_string();
        assert_eq!(diagnostic, category);
        let record = json!({"reason": diagnostic}).to_string();
        assert!(!record.contains(REJECTED_SENTINEL));
        assert!(!record.contains("invalid game state"));
        assert!(!record.contains("invalid card"));
        assert!(!record.contains("unknown available action"));
    }

    #[test]
    fn safe_category_board_count() {
        let mut value = serde_json::to_value(table(state(GamePhase::Flop))).unwrap();
        value["state"]["board"] = json!([{"rank": REJECTED_SENTINEL, "suit": "clubs"}]);
        assert_safe_category(&value, "board-count");
    }

    #[test]
    fn safe_category_hero_cards() {
        let mut value = serde_json::to_value(table(state(GamePhase::Flop))).unwrap();
        value["state"]["hero_cards"][0]["rank"] = json!(REJECTED_SENTINEL);
        assert_safe_category(&value, "hero-cards");
        value["state"]["hero_cards"] = json!([{"rank": REJECTED_SENTINEL, "suit": "clubs"}]);
        assert_safe_category(&value, "hero-cards");
    }

    #[test]
    fn safe_category_action_required() {
        let mut value = serde_json::to_value(table(state(GamePhase::Flop))).unwrap();
        value["state"]["available_actions"] = json!([REJECTED_SENTINEL]);
        assert_safe_category(&value, "action-required");
        let mut value = serde_json::to_value(table(state(GamePhase::Flop))).unwrap();
        value["state"]["players"][1]["name"] = json!(REJECTED_SENTINEL);
        value["evidence"]["action_controls"] = json!(false);
        assert_safe_category(&value, "action-required");
    }

    #[test]
    fn safe_category_envelope_failures_do_not_mistake_trailing_prose_for_truncation() {
        let mut value = serde_json::to_value(table(state(GamePhase::Flop))).unwrap();
        value["state"]["players"][1]["name"] = json!(REJECTED_SENTINEL);
        let json = value.to_string();
        let mut incomplete = json.clone();
        incomplete.pop();
        let mut unknown_kind = value;
        unknown_kind["screen_kind"] = json!(REJECTED_SENTINEL);
        for (text, category) in [
            (
                format!("```json\n{json}\n``` {REJECTED_SENTINEL}"),
                "malformed",
            ),
            (format!("```{REJECTED_SENTINEL}"), "malformed"),
            (format!("```json\n{json}"), "malformed"),
            (REJECTED_SENTINEL.to_string(), "malformed"),
            (unknown_kind.to_string(), "schema"),
            (incomplete, "truncated"),
            (" \n\t".to_string(), "no-json"),
        ] {
            let diagnostic = parse_screen_output(&output(&text)).unwrap_err().to_string();
            assert_eq!(diagnostic, category);
            let record = json!({"reason": diagnostic}).to_string();
            assert!(!record.contains(REJECTED_SENTINEL));
            assert!(!record.contains("screen envelope fence"));
            assert!(!record.contains("unknown variant"));
            assert!(!record.contains("EOF while parsing"));
        }
    }

    fn observe(gate: &mut TableGate, observation: &ScreenObservation) -> GateOutcome {
        gate.observe(
            &identity(),
            observation,
            MetadataEvidence::TableTitle,
            VisualEvidence::Plausible,
        )
    }

    // Calls model distinct fresh generations supplied by the capture integration;
    // these synthetic tests verify gate logic, not real-screen recognition.
    fn confirm(gate: &mut TableGate, observation: &ScreenObservation) -> GateOutcome {
        assert!(observe(gate, observation).accepted_state.is_none());
        observe(gate, observation)
    }

    #[test]
    fn agreeing_community_cards_do_not_require_a_matching_pot() {
        let mut gate = TableGate::new();
        let mut reading = state(GamePhase::Flop);
        reading.hero_cards.clear();
        reading.action_required = false;
        reading.available_actions.clear();
        reading.min_raise_to = None;
        reading.max_raise_to = None;
        reading.to_call = 0;
        let mut changed_pot = reading.clone();
        changed_pot.pot_size += 50;
        let waiting = observe(&mut gate, &table(reading));
        assert!(waiting.visible_cards.is_none());
        let agreed = observe(&mut gate, &table(changed_pot));
        assert!(agreed.accepted_state.is_none());
        let cards = agreed.visible_cards.expect("community cards");
        assert_eq!(cards.board.len(), 3);
        assert!(cards.hero_cards.is_empty());
        assert!(!cards.action_required);
        assert_eq!(agreed.reason, "community cards agree; no advice");
    }

    #[test]
    fn screen_kinds_and_observations_round_trip_without_default_classification() {
        for (kind, name) in [
            (ScreenKind::Lobby, "lobby"),
            (ScreenKind::PokerTable, "poker_table"),
            (ScreenKind::OtherCoinPokerWindow, "other_coin_poker_window"),
            (ScreenKind::Unknown, "unknown"),
        ] {
            assert_eq!(serde_json::to_value(kind).unwrap(), json!(name));
            assert_eq!(
                serde_json::from_value::<ScreenKind>(json!(name)).unwrap(),
                kind
            );
        }
        let observed = table(state(GamePhase::Flop));
        assert_eq!(
            parse(&serde_json::to_value(&observed).unwrap()).unwrap(),
            observed.clone()
        );
        assert!(serde_json::from_value::<ScreenKind>(json!("table")).is_err());
        assert!(parse(&serde_json::to_value(state(GamePhase::Flop)).unwrap()).is_err());
    }

    #[test]
    fn all_non_table_kinds_need_no_poker_payload_and_ignore_irrelevant_state() {
        for kind in [
            ScreenKind::Lobby,
            ScreenKind::OtherCoinPokerWindow,
            ScreenKind::Unknown,
        ] {
            let expected = non_table(kind);
            let mut value = serde_json::to_value(&expected).unwrap();
            assert_eq!(parse(&value).unwrap(), expected);
            value.as_object_mut().unwrap().remove("state");
            assert_eq!(parse(&value).unwrap(), expected);
            for irrelevant in [
                json!({"pot_size": -1, "board": ["not a card"]}),
                json!("not poker"),
                json!(42),
            ] {
                value["state"] = irrelevant;
                assert_eq!(parse(&value).unwrap(), expected);
            }
        }
    }

    #[test]
    fn envelope_and_evidence_fields_are_required_and_typed() {
        let complete = serde_json::to_value(table(state(GamePhase::Flop))).unwrap();
        for field in ["screen_kind", "evidence", "state"] {
            let mut value = complete.clone();
            value.as_object_mut().unwrap().remove(field);
            assert!(parse(&value).is_err(), "missing {field}");
        }
        for field in [
            "table_layout",
            "hero_cards",
            "board_area",
            "pot",
            "action_controls",
            "readable",
        ] {
            let mut value = complete.clone();
            value["evidence"].as_object_mut().unwrap().remove(field);
            assert!(parse(&value).is_err(), "missing evidence {field}");
            value["evidence"][field] = json!("true");
            assert!(parse(&value).is_err(), "mistyped evidence {field}");
        }
        let mut value = complete;
        value["confidence"] = json!(0.99);
        assert!(parse(&value).is_err());
    }

    #[test]
    fn table_payload_cannot_inherit_legacy_poker_field_defaults() {
        let complete = serde_json::to_value(table(state(GamePhase::Flop))).unwrap();
        for field in complete["state"].as_object().unwrap().keys() {
            let mut value = complete.clone();
            value["state"].as_object_mut().unwrap().remove(field);
            assert!(parse(&value).is_err(), "missing table field {field}");
        }
        for field in ["name", "chips", "last_action", "bet_amount"] {
            let mut value = complete.clone();
            value["state"]["players"][0]
                .as_object_mut()
                .unwrap()
                .remove(field);
            assert!(parse(&value).is_err(), "missing player field {field}");
        }
    }

    #[test]
    fn whole_response_parsing_accepts_only_one_complete_envelope() {
        let observed = table(state(GamePhase::Flop));
        let json = serde_json::to_string(&observed).unwrap();
        for text in [
            format!(" \n{json}\t"),
            format!("```json\n{json}\n```"),
            format!("```\r\n{json}\r\n```\n"),
        ] {
            assert_eq!(parse_screen_output(&output(&text)).unwrap(), observed);
        }
        for text in [
            format!("Here is the result: {json}"),
            format!("{json} trailing text"),
            format!("{json}\n{json}"),
            format!("```json\n{json}"),
            format!("```json\n{json}\n``` trailing text"),
            format!("```rust\n{json}\n```"),
            json[..json.len() - 1].to_string(),
            "null".to_string(),
            "[]".to_string(),
            json.replace(
                "\"screen_kind\":\"poker_table\"",
                "\"screen_kind\":\"poker_table\",\"screen_kind\":\"unknown\"",
            ),
            json.replace("\"pot_size\":1250", "\"pot_size\":1250,\"pot_size\":1300"),
        ] {
            assert!(
                parse_screen_output(&output(&text)).is_err(),
                "accepted {text}"
            );
        }
        assert_eq!(
            parse_screen_output(&output(" \n\t")),
            Err(ParseError::NoJson)
        );
    }

    #[test]
    fn table_parsing_preserves_poker_validation_and_evidence_consistency() {
        let complete = serde_json::to_value(table(state(GamePhase::Flop))).unwrap();
        let mut invalid_states = Vec::new();
        let mut value = complete.clone();
        value["state"]["pot_size"] = json!(0);
        invalid_states.push(value);
        let mut value = complete.clone();
        value["state"]["to_call"] = json!(499);
        invalid_states.push(value);
        let mut value = complete.clone();
        value["state"]["board"] = json!([]);
        invalid_states.push(value);
        let mut value = complete.clone();
        value["state"]["players"][0]["chips"] = json!(2499);
        invalid_states.push(value);
        let mut value = complete.clone();
        value["state"]["min_raise_to"] = Value::Null;
        invalid_states.push(value);
        let mut value = complete.clone();
        value["state"]["hero_cards"][0] = value["state"]["board"][0].clone();
        invalid_states.push(value);
        for field in [
            "table_layout",
            "hero_cards",
            "board_area",
            "pot",
            "action_controls",
            "readable",
        ] {
            let mut value = complete.clone();
            value["evidence"][field] = json!(false);
            invalid_states.push(value);
        }
        invalid_states.push(serde_json::to_value(table(state(GamePhase::Lobby))).unwrap());
        for value in invalid_states {
            assert!(parse(&value).is_err());
        }
        let mut value = complete;
        value["state"] = Value::Null;
        assert!(parse(&value).is_err());
        value["evidence"]["readable"] = json!(false);
        let unreadable = parse(&value).unwrap();
        assert!(unreadable.state.is_none());
        assert!(observe(&mut TableGate::new(), &unreadable)
            .accepted_state
            .is_none());
    }

    #[test]
    fn calibrated_table_titles_still_require_two_full_matching_observations() {
        let observed = table(state(GamePhase::Flop));
        let mut gate = TableGate::new();
        let first = observe(&mut gate, &observed);
        assert_eq!(first.kind, ScreenKind::PokerTable);
        assert!(first.accepted_state.is_none());
        assert_eq!(observe(&mut gate, &observed).accepted_state, observed.state);
    }

    #[test]
    fn repeated_hallucination_cannot_promote_an_unclassified_application_window() {
        let observed = table(state(GamePhase::Flop));
        let mut gate = TableGate::new();
        for _ in 0..5 {
            let result = gate.observe(
                &identity(),
                &observed,
                MetadataEvidence::Candidate,
                VisualEvidence::Plausible,
            );
            assert!(result.accepted_state.is_none());
            assert_eq!(result.reason, "table-title-calibration-required");
        }
    }

    #[test]
    fn lobby_metadata_vetoes_a_consistent_actionable_table() {
        let observed = table(state(GamePhase::Flop));
        let mut gate = TableGate::new();
        assert!(confirm(&mut gate, &observed).accepted_state.is_some());
        for _ in 0..3 {
            let result = gate.observe(
                &identity(),
                &observed,
                MetadataEvidence::LobbyTitle,
                VisualEvidence::Plausible,
            );
            assert_eq!(result.kind, ScreenKind::Lobby);
            assert!(result.accepted_state.is_none());
        }
        assert!(gate.accepted.is_none());
        assert!(gate.pending.is_none());
    }

    #[test]
    fn other_metadata_vetoes_a_consistent_actionable_table() {
        let observed = table(state(GamePhase::Flop));
        let mut gate = TableGate::new();
        for _ in 0..3 {
            let result = gate.observe(
                &identity(),
                &observed,
                MetadataEvidence::Other,
                VisualEvidence::Plausible,
            );
            assert_eq!(result.kind, ScreenKind::OtherCoinPokerWindow);
            assert!(result.accepted_state.is_none());
        }
    }

    #[test]
    fn lobby_classification_never_produces_table_recommendations() {
        let observed = non_table(ScreenKind::Lobby);
        let result = confirm(&mut TableGate::new(), &observed);
        assert_eq!(result.kind, ScreenKind::Lobby);
        assert!(result.accepted_state.is_none());
    }

    #[test]
    fn other_coinpoker_window_never_produces_table_recommendations() {
        let observed = non_table(ScreenKind::OtherCoinPokerWindow);
        let result = confirm(&mut TableGate::new(), &observed);
        assert_eq!(result.kind, ScreenKind::OtherCoinPokerWindow);
        assert!(result.accepted_state.is_none());
    }

    #[test]
    fn unknown_classification_never_produces_table_recommendations() {
        let observed = non_table(ScreenKind::Unknown);
        let result = confirm(&mut TableGate::new(), &observed);
        assert_eq!(result.kind, ScreenKind::Unknown);
        assert!(result.accepted_state.is_none());
    }

    #[test]
    fn false_actionable_evidence_and_unreadable_frames_break_consensus() {
        let observed = table(state(GamePhase::Flop));
        for flag in 0..6 {
            let mut gate = TableGate::new();
            assert!(observe(&mut gate, &observed).accepted_state.is_none());
            let mut bad = observed.clone();
            let evidence = &mut bad.evidence;
            let flags = [
                &mut evidence.table_layout,
                &mut evidence.hero_cards,
                &mut evidence.board_area,
                &mut evidence.pot,
                &mut evidence.action_controls,
                &mut evidence.readable,
            ];
            *flags.into_iter().nth(flag).unwrap() = false;
            assert!(confirm(&mut gate, &bad).accepted_state.is_none());
            assert!(confirm(&mut gate, &observed).accepted_state.is_some());
        }
        let mut gate = TableGate::new();
        observe(&mut gate, &observed);
        assert!(gate
            .observe(
                &identity(),
                &observed,
                MetadataEvidence::TableTitle,
                VisualEvidence::Unreadable
            )
            .accepted_state
            .is_none());
        assert!(confirm(&mut gate, &observed).accepted_state.is_some());
    }

    #[test]
    fn every_decision_field_participates_in_consensus() {
        let initial = state(GamePhase::Flop);
        let mut changed_states = Vec::new();
        let mut changed = initial.clone();
        changed.pot_size += 1;
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.to_call += 1;
        changed.players[1].bet_amount += 1;
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.hero_chips += 1;
        changed.players[0].chips += 1;
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.min_raise_to = Some(1600);
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.max_raise_to = Some(2900);
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.players[1].chips += 1;
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.players[1].last_action = Some("raise".to_string());
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.players[1].name = "Seat2".to_string();
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.players.swap(0, 1);
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.hero_cards[0].rank = "T".to_string();
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.board[0].rank = "8".to_string();
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.available_actions.push("allin".to_string());
        changed_states.push(changed);
        let mut changed = initial.clone();
        changed.action_required = false;
        changed.available_actions.clear();
        changed.min_raise_to = None;
        changed.max_raise_to = None;
        changed_states.push(changed);
        changed_states.push(state(GamePhase::Turn));
        for changed in changed_states {
            validate_game_state(&changed).expect("valid changed state");
            let mut gate = TableGate::new();
            observe(&mut gate, &table(initial.clone()));
            let different = table(changed);
            assert!(observe(&mut gate, &different).accepted_state.is_none());
            assert_eq!(
                observe(&mut gate, &different).accepted_state,
                different.state
            );
        }
    }

    #[test]
    fn differing_eligible_evidence_restarts_consensus() {
        let mut first = marker();
        let mut second = first.clone();
        second.evidence.action_controls = true;
        let mut gate = TableGate::new();
        observe(&mut gate, &first);
        assert!(observe(&mut gate, &second).accepted_state.is_none());
        assert!(observe(&mut gate, &second).accepted_state.is_some());
        first.evidence.pot = false;
        assert!(confirm(&mut gate, &first).accepted_state.is_none());
    }

    #[test]
    fn every_identity_component_resets_consensus_and_the_timeline() {
        let original = identity();
        let mut changed_identities = Vec::new();
        let mut changed = original.clone();
        changed.exe_name.push_str(".another");
        changed_identities.push(changed);
        let mut changed = original.clone();
        changed.process_id += 1;
        changed_identities.push(changed);
        let mut changed = original.clone();
        changed.hwnd += 1;
        changed_identities.push(changed);
        let late = table(state(GamePhase::River));
        let early = table(state(GamePhase::Preflop));
        for changed in changed_identities {
            let mut gate = TableGate::new();
            confirm(&mut gate, &late);
            assert!(gate
                .observe(
                    &changed,
                    &early,
                    MetadataEvidence::TableTitle,
                    VisualEvidence::Plausible
                )
                .accepted_state
                .is_none());
            assert_eq!(
                gate.observe(
                    &changed,
                    &early,
                    MetadataEvidence::TableTitle,
                    VisualEvidence::Plausible
                )
                .accepted_state,
                early.state
            );
        }
    }

    #[test]
    fn invalid_observations_do_not_poison_the_accepted_timeline() {
        let accepted = table(state(GamePhase::Flop));
        let mut invalid = accepted.clone();
        invalid.state.as_mut().unwrap().hero_cards[0].rank = "T".to_string();
        let mut skipped = table(state(GamePhase::River));
        let mut gate = TableGate::new();
        assert!(confirm(&mut gate, &accepted).accepted_state.is_some());
        assert!(confirm(&mut gate, &invalid).accepted_state.is_none());
        assert_eq!(gate.accepted, accepted.state);
        assert!(confirm(&mut gate, &skipped).accepted_state.is_none());
        assert_eq!(gate.accepted, accepted.state);
        skipped.state.as_mut().unwrap().pot_size = 0;
        assert!(confirm(&mut gate, &skipped).accepted_state.is_none());
        assert_eq!(gate.accepted, accepted.state);
        assert_eq!(
            confirm(&mut gate, &table(state(GamePhase::Turn))).accepted_state,
            Some(state(GamePhase::Turn))
        );
    }

    #[test]
    fn a_hand_reset_requires_an_accepted_marker_not_a_single_empty_frame() {
        let late = table(state(GamePhase::River));
        let mut dealt = state(GamePhase::Preflop);
        dealt.hero_cards[0].rank = "T".to_string();
        let dealt = table(dealt);
        let mut gate = TableGate::new();
        confirm(&mut gate, &late);
        assert!(confirm(&mut gate, &dealt).accepted_state.is_none());
        assert!(observe(&mut gate, &marker()).accepted_state.is_none());
        assert!(confirm(&mut gate, &dealt).accepted_state.is_none());
        assert_eq!(gate.accepted, late.state);
        let boundary = confirm(&mut gate, &marker());
        assert!(boundary
            .accepted_state
            .is_some_and(|state| !state.action_required));
        assert_eq!(confirm(&mut gate, &dealt).accepted_state, dealt.state);
    }

    #[test]
    fn accepted_showdown_allows_a_direct_dealt_preflop() {
        let mut gate = TableGate::new();
        confirm(&mut gate, &table(state(GamePhase::Showdown)));
        let dealt = table(state(GamePhase::Preflop));
        assert_eq!(confirm(&mut gate, &dealt).accepted_state, dealt.state);
    }

    #[test]
    fn unknown_unreadable_and_conflicting_screens_cannot_erase_continuity() {
        let late = table(state(GamePhase::River));
        let early = table(state(GamePhase::Preflop));
        let mut unreadable = non_table(ScreenKind::Lobby);
        unreadable.evidence.readable = false;
        let mut conflict = non_table(ScreenKind::Lobby);
        conflict.evidence.table_layout = true;
        let mut missing = late.clone();
        missing.state = None;
        for uncertain in [
            non_table(ScreenKind::Unknown),
            unreadable,
            conflict,
            missing,
        ] {
            let mut gate = TableGate::new();
            confirm(&mut gate, &late);
            assert!(confirm(&mut gate, &uncertain).accepted_state.is_none());
            assert_eq!(gate.accepted, late.state);
            assert!(confirm(&mut gate, &early).accepted_state.is_none());
        }
        let mut gate = TableGate::new();
        confirm(&mut gate, &late);
        gate.observe(
            &identity(),
            &late,
            MetadataEvidence::Candidate,
            VisualEvidence::Unreadable,
        );
        assert_eq!(gate.accepted, late.state);
        assert!(confirm(&mut gate, &early).accepted_state.is_none());
    }

    #[test]
    fn genuine_non_table_screens_and_explicit_reset_clear_the_timeline() {
        let late = table(state(GamePhase::River));
        let early = table(state(GamePhase::Preflop));
        for kind in [ScreenKind::Lobby, ScreenKind::OtherCoinPokerWindow] {
            let mut gate = TableGate::new();
            confirm(&mut gate, &late);
            observe(&mut gate, &non_table(kind));
            assert!(gate.accepted.is_none());
            assert_eq!(confirm(&mut gate, &early).accepted_state, early.state);
        }
        let mut gate = TableGate::new();
        confirm(&mut gate, &late);
        gate.reset();
        assert!(gate.identity.is_none());
        assert!(gate.pending.is_none());
        assert!(gate.accepted.is_none());
        assert_eq!(confirm(&mut gate, &early).accepted_state, early.state);
    }

    fn synthetic_frame(width: u32, height: u32) -> Frame {
        let rgba = (0..width * height)
            .flat_map(|pixel| {
                let gray = (pixel % 251) as u8;
                [gray, gray, gray, 255]
            })
            .collect();
        Frame::new(width, height, rgba).unwrap()
    }

    #[test]
    fn frame_inspection_rejects_malformed_tiny_blank_and_transparent_buffers() {
        for frame in [
            Frame {
                width: 320,
                height: 240,
                rgba: vec![0; 15],
            },
            Frame {
                width: u32::MAX,
                height: u32::MAX,
                rgba: vec![],
            },
            synthetic_frame(0, 240),
            synthetic_frame(320, 0),
            synthetic_frame(159, 120),
            synthetic_frame(160, 119),
        ] {
            assert_eq!(inspect_frame(&frame), VisualEvidence::Unreadable);
        }
        for color in [
            [0, 0, 0, 255],
            [255, 255, 255, 255],
            [12, 84, 41, 255],
            [0, 0, 0, 0],
        ] {
            let frame = Frame::new(320, 240, color.repeat(320 * 240)).unwrap();
            assert_eq!(inspect_frame(&frame), VisualEvidence::Unreadable);
        }
        let mut transparent = synthetic_frame(320, 240);
        for pixel in transparent.rgba.chunks_exact_mut(4) {
            pixel[3] = 0;
        }
        assert_eq!(inspect_frame(&transparent), VisualEvidence::Unreadable);
        let mut alpha_only = Frame::new(320, 240, [10, 10, 10, 255].repeat(320 * 240)).unwrap();
        alpha_only.rgba[3] = 1;
        assert_eq!(inspect_frame(&alpha_only), VisualEvidence::Unreadable);
    }

    #[test]
    fn plausible_is_not_proof_of_a_table_or_a_recommendation() {
        let arbitrary_gray_image = synthetic_frame(320, 240);
        let visual = inspect_frame(&arbitrary_gray_image);
        assert_eq!(visual, VisualEvidence::Plausible);
        let mut gate = TableGate::new();
        let unknown = non_table(ScreenKind::Unknown);
        for _ in 0..3 {
            let result = gate.observe(&identity(), &unknown, MetadataEvidence::TableTitle, visual);
            assert_eq!(result.kind, ScreenKind::Unknown);
            assert!(result.accepted_state.is_none());
        }
    }
}
