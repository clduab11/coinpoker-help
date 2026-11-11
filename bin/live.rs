use std::collections::hash_map::RandomState;
use std::hash::BuildHasher;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process::Command;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use core_engine::opponent::observer::{Capture, Evidence, Id, Observer, Snapshot, MAX_EVENT_VIEW};
use core_engine::opponent::observing::{
    Frame as ObservingFrame, Reading, Tracker as ObservingTracker,
};
use ingest::capture::{CaptureError, Frame, PlatformCapture, WindowCapturer};
use ingest::discovery::DiscoveryConfig;
use ingest::laya::LayaBackend;
use ingest::partial::{PartialObservationView, SCENE_VERIFIED_FIELDS, STACK_FIELDS, WAGER_FIELDS};
use ingest::recorder::{RecorderSnapshot, RecordingCapturer};
use ingest::runtime::{
    Analysis, Clock, InferenceFailure, LiveEvent, LiveRuntime, MonotonicClock, RuntimeConfig,
    ThreadWorker, Ticket, CAPTURE_HEALTH_INTERVAL_MS, DECISION_DEADLINE_CODE,
    PUBLICATION_RESERVE_MS,
};
use ingest::screen::parse_screen_output;
#[cfg(test)]
use ingest::vlm::VlmBackend;
use serde_json::json;

use crate::config::Options;
use crate::{Pipeline, RunError};

pub fn emit(value: &serde_json::Value) -> Result<(), RunError> {
    let mut out = io::stdout().lock();
    serde_json::to_writer(&mut out, value).map_err(|e| RunError::Message(e.to_string()))?;
    writeln!(out)?;
    out.flush()?;
    Ok(())
}

pub fn list_windows() -> Result<(), RunError> {
    let snapshot = WindowCapturer::discover().map_err(|error| {
        let state = if error == CaptureError::PermissionDenied {
            "permission_required"
        } else {
            "capture_unavailable"
        };
        let _ = emit(
            &json!({"schema_version":2,"event":"status","state":state,"reason":error.to_string()}),
        );
        RunError::Message(error.to_string())
    })?;
    for application in snapshot.applications {
        emit(&json!({"schema_version":2,"event":"application","application":application}))?;
    }
    for window in snapshot.windows {
        emit(&json!({"schema_version":2,"event":"window","window":window}))?;
    }
    Ok(())
}

#[cfg(test)]
fn analyze_frame(
    backend: &impl VlmBackend,
    pipeline: &Pipeline,
    frame: &Frame,
    deadline: Instant,
) -> Result<Analysis<crate::ui::widgets::DecisionView>, InferenceFailure> {
    let output = backend
        .analyze_with_deadline(frame, &ingest::prompt::build_analysis_prompt(), deadline)
        .map_err(|error| InferenceFailure { code: error.code() })?;
    finish_analysis(output, Some(pipeline), deadline)
}

fn analyze_laya_frame(
    backend: &LayaBackend,
    pipeline: &Pipeline,
    frame: &Frame,
    deadline: Instant,
) -> Result<Analysis<crate::ui::widgets::DecisionView>, InferenceFailure> {
    let output = backend
        .analyze_observation_with_deadline(frame, deadline)
        .map_err(|error| InferenceFailure { code: error.code() })?;
    finish_laya_analysis(output, Some(pipeline), deadline)
}

pub(crate) fn finish_laya_analysis(
    mut output: ingest::laya::LayaAnalysis,
    pipeline: Option<&Pipeline>,
    deadline: Instant,
) -> Result<Analysis<crate::ui::widgets::DecisionView>, InferenceFailure> {
    let completed = if Instant::now() >= deadline {
        Err(InferenceFailure {
            code: DECISION_DEADLINE_CODE,
        })
    } else {
        finish_analysis(output.output, pipeline, deadline)
    };
    let mut result = match completed {
        Ok(result) => result,
        Err(failure) if failure.code == DECISION_DEADLINE_CODE => {
            output.diagnostics.source_current = false;
            output.diagnostics.admission =
                ingest::partial::DiagnosticAdmission::DecisionBudgetExpired;
            for field in &mut output.diagnostics.fields {
                field.admission_status = ingest::partial::EvidenceStatus::Rejected;
                field.admission_reason = ingest::partial::DiagnosticReason::DecisionDeadline;
            }
            // Preserve private traces, but never return late table classification,
            // fields, a recommendation, or a consensus seed.
            return Ok(Analysis {
                observation: ingest::screen::ScreenObservation {
                    screen_kind: ingest::screen::ScreenKind::Unknown,
                    evidence: ingest::screen::ScreenEvidence {
                        table_layout: false,
                        hero_cards: false,
                        board_area: false,
                        pot: false,
                        action_controls: false,
                        readable: false,
                    },
                    state: None,
                },
                partial: None,
                diagnostics: Some(output.diagnostics),
                recommendation: None,
            });
        }
        Err(failure) => return Err(failure),
    };
    result.partial = output.partial;
    result.diagnostics = Some(output.diagnostics);
    Ok(result)
}

fn finish_analysis(
    output: ingest::vlm::VlmOutput,
    pipeline: Option<&Pipeline>,
    deadline: Instant,
) -> Result<Analysis<crate::ui::widgets::DecisionView>, InferenceFailure> {
    // Error codes are typed constants, never model payloads or parser messages.
    let observation =
        parse_screen_output(&output).map_err(|error| InferenceFailure { code: error.code() })?;
    if Instant::now() >= deadline {
        return Err(InferenceFailure {
            code: DECISION_DEADLINE_CODE,
        });
    }
    // Session reads (PLAN Phase 1): fold this state in before deciding so the
    // exploit layer sees the freshest per-opponent picture.
    if let (Some(pipeline), Some(state)) = (pipeline, observation.state.as_ref()) {
        pipeline.feed().observe_state(state);
    }
    let recommendation = observation
        .state
        .as_ref()
        .filter(|s| s.action_required)
        .and_then(|state| pipeline.and_then(|pipeline| pipeline.decide(state).ok()));
    if Instant::now() >= deadline {
        return Err(InferenceFailure {
            code: DECISION_DEADLINE_CODE,
        });
    }
    Ok(Analysis {
        observation,
        recommendation,
        partial: None,
        diagnostics: None,
    })
}

/// The calibrated lobby size, when both dimensions are configured (R18).
pub fn lobby_size(discovery: &DiscoveryConfig) -> Option<(u32, u32)> {
    match (discovery.lobby_width, discovery.lobby_height) {
        (Some(width), Some(height)) if width > 0 && height > 0 => Some((width, height)),
        _ => None,
    }
}

fn configuration_event(options: &Options) -> serde_json::Value {
    json!({"schema_version":2,"event":"configuration","runtime":options.runtime,
        "identity_configured":options.discovery.has_identity(),"model":options.vlm.model,
        "vlm_timeout_secs":options.vlm.timeout_secs,"visual_calibration":"not_validated",
        "perception":"laya-vision","question_set_version":ingest::laya::question_set_version(),
        "laya_threshold":options.vlm.threshold,"laya_calibrated":ingest::laya::calibrated(),
        "quality_approved":ingest::laya::calibrated(),"capture_health_interval_ms":CAPTURE_HEALTH_INTERVAL_MS,
        "decision_publication_reserve_ms":PUBLICATION_RESERVE_MS,
        "recording_enabled":options.recording.is_some(),
        "wager_registry_configured":options.wager_registry.is_some(),
        "scene_registry_configured":options.scene_registry.is_some()})
}

fn unix_ms() -> Result<u64, RunError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis().min(u128::from(u64::MAX)) as u64)
        .map_err(|_| RunError::Message("system clock predates the Unix epoch".into()))
}

/// A result must still fit both source-bound limits at publication, not get a new lease.
fn leased_record(
    mut record: serde_json::Value,
    event: &str,
    ticket: Ticket,
    valid_for_ms: u64,
    now_ms: u64,
    emitted_at_unix_ms: u64,
    config: &RuntimeConfig,
) -> Option<serde_json::Value> {
    let age = now_ms.checked_sub(ticket.captured_at_ms)?;
    let mut valid_for_ms = valid_for_ms.min(
        config
            .max_frame_age_ms
            .min(config.decision_budget_ms)
            .saturating_sub(age),
    );
    let captured_at_unix_ms = ticket
        .captured_at_unix_ms
        .unwrap_or_else(|| emitted_at_unix_ms.saturating_sub(age));
    if ticket.captured_at_unix_ms.is_some() {
        let wall_age = emitted_at_unix_ms.checked_sub(captured_at_unix_ms)?;
        valid_for_ms = valid_for_ms.min(
            config
                .max_frame_age_ms
                .min(config.decision_budget_ms)
                .saturating_sub(wall_age),
        );
    }
    if valid_for_ms == 0 {
        return None;
    }
    let fields = record
        .as_object_mut()
        .expect("sanitized event DTO is an object");
    fields.insert("schema_version".into(), json!(2));
    fields.insert("event".into(), json!(event));
    fields.insert("observation".into(), json!(ticket));
    fields.insert("captured_at_unix_ms".into(), json!(captured_at_unix_ms));
    fields.insert("valid_for_ms".into(), json!(valid_for_ms));
    fields.insert("emitted_at_unix_ms".into(), json!(emitted_at_unix_ms));
    fields.insert(
        "expires_at_unix_ms".into(),
        json!(emitted_at_unix_ms.saturating_add(valid_for_ms)),
    );
    Some(record)
}

pub(crate) fn event_record(
    event: LiveEvent<crate::ui::widgets::DecisionView>,
    now_ms: u64,
    emitted_at_unix_ms: u64,
    config: &RuntimeConfig,
    recording: RecorderSnapshot,
) -> Result<Option<serde_json::Value>, RunError> {
    let mut record = match event {
        LiveEvent::Status {
            state,
            reason,
            identity,
        } => {
            json!({"schema_version":2,"event":"status","state":state,"reason":reason,"identity":identity})
        }
        LiveEvent::Clear { reason, generation } => {
            json!({"schema_version":2,"event":"clear","reason":reason,"generation":generation})
        }
        LiveEvent::Recommendation {
            ticket,
            value,
            valid_for_ms,
        } => {
            let mut record =
                serde_json::to_value(value).map_err(|e| RunError::Message(e.to_string()))?;
            if let Some(map) = record.as_object_mut() {
                map.insert(
                    "finished_in_ms".into(),
                    json!(now_ms.saturating_sub(ticket.captured_at_ms)),
                );
            }
            return Ok(leased_record(
                record,
                "decision",
                ticket,
                valid_for_ms,
                now_ms,
                emitted_at_unix_ms,
                config,
            ));
        }
        LiveEvent::Observation {
            ticket,
            value,
            valid_for_ms,
        } => {
            // This live worker uses Laya only. In 0.4.0 a full admitted state has
            // already passed confident unseated R15/R17, parser and runtime gates.
            // Never extend this provenance to weak Table events or a future model.
            let value = if ingest::laya::question_set_version() == "0.4.0" {
                value.with_confirmed_unseated_admission()
            } else {
                value
            };
            let record =
                serde_json::to_value(value).map_err(|e| RunError::Message(e.to_string()))?;
            return Ok(leased_record(
                record,
                "observation",
                ticket,
                valid_for_ms,
                now_ms,
                emitted_at_unix_ms,
                config,
            ));
        }
        LiveEvent::PartialObservation {
            ticket,
            value,
            valid_for_ms,
        } => {
            let record =
                serde_json::to_value(value).map_err(|e| RunError::Message(e.to_string()))?;
            return Ok(leased_record(
                record,
                "partial_observation",
                ticket,
                valid_for_ms,
                now_ms,
                emitted_at_unix_ms,
                config,
            ));
        }
        LiveEvent::PerceptionDiagnostics {
            ticket,
            value,
            valid_for_ms,
        } => {
            let mut record =
                serde_json::to_value(value).map_err(|e| RunError::Message(e.to_string()))?;
            // Private telemetry survives late/obsolete admission. It is never an
            // observation and never extends a lease. Explicit experimental candidates
            // may have a separate sanitized, source-leased diagnostic projection.
            let age = now_ms.checked_sub(ticket.captured_at_ms);
            let limit = config.max_frame_age_ms.min(config.decision_budget_ms);
            let captured = ticket
                .captured_at_unix_ms
                .or_else(|| age.map(|age| emitted_at_unix_ms.saturating_sub(age)));
            let wall_remaining = captured
                .and_then(|source| emitted_at_unix_ms.checked_sub(source))
                .map_or(0, |age| limit.saturating_sub(age));
            let fields = record
                .as_object_mut()
                .expect("typed private diagnostics object");
            fields.insert("schema_version".into(), json!(2));
            fields.insert("event".into(), json!("perception_diagnostics"));
            fields.insert("observation".into(), json!(ticket));
            fields.insert("emitted_at_unix_ms".into(), json!(emitted_at_unix_ms));
            fields.insert("captured_at_unix_ms".into(), json!(captured));
            fields.insert("source_age_ms".into(), json!(age));
            fields.insert(
                "expires_at_unix_ms".into(),
                json!(captured.map(|t| t.saturating_add(limit))),
            );
            fields.insert(
                "valid_for_ms".into(),
                json!(valid_for_ms
                    .min(age.map_or(0, |age| limit.saturating_sub(age)))
                    .min(wall_remaining)),
            );
            if age.is_none_or(|age| age >= limit) || wall_remaining == 0 {
                fields.insert("source_current".into(), json!(false));
            }
            return Ok(Some(record));
        }
        LiveEvent::PartialObservationInvalidated {
            ticket,
            reason,
            fields,
        } => {
            let mut record = json!({"schema_version":2,"event":"partial_observation_invalidated","reason":reason,
                "generation":ticket.generation,"epoch":ticket.epoch,"identity":ticket.identity,
                "captured_at_unix_ms":ticket.captured_at_unix_ms,"observation":ticket});
            if let Some(fields) = fields {
                record["fields"] = json!(fields);
            }
            record
        }
        LiveEvent::ObservationInvalidated {
            reason,
            generation,
            epoch,
            identity,
        } => {
            json!({"schema_version":2,"event":"observation_invalidated","reason":reason,
                "generation":generation,"epoch":epoch,"identity":identity})
        }
        LiveEvent::CaptureHealth {
            frame_count,
            frame_width,
            frame_height,
            captured_at_ms,
            generation,
            epoch,
            fresh_capture,
            identity,
        } => {
            let capture_age = captured_at_ms.and_then(|captured| now_ms.checked_sub(captured));
            let fresh_capture =
                fresh_capture && capture_age.is_some_and(|age| age < CAPTURE_HEALTH_INTERVAL_MS);
            let captured_at_unix_ms = capture_age.map(|age| emitted_at_unix_ms.saturating_sub(age));
            json!({"schema_version":2,"event":"capture_health","frame_count":frame_count,
                "frame_width":frame_width,"frame_height":frame_height,"captured_at_ms":captured_at_ms,
                "captured_at_unix_ms":captured_at_unix_ms,
                "generation":generation,"epoch":epoch,"fresh_capture":fresh_capture,"identity":identity,
                "recording_enabled":recording.recording_enabled,"recorded_frames":recording.recorded_frames,
                "recorded_bytes":recording.recorded_bytes,"recording_status":recording.recording_status,
                "recording_complete":recording.recording_complete})
        }
        LiveEvent::Table {
            game_phase,
            hero_cards,
            board,
            action_required,
        } => {
            json!({"schema_version":2,"event":"table","game_phase":game_phase,"hero_cards":hero_cards,"board":board,"action_required":action_required})
        }
        LiveEvent::Discarded { generation, reason } => {
            json!({"schema_version":2,"event":"discarded","generation":generation,"reason":reason})
        }
    };
    record
        .as_object_mut()
        .unwrap()
        .insert("emitted_at_unix_ms".into(), json!(emitted_at_unix_ms));
    Ok(Some(record))
}

/// Emissions between complete `history` views. A delta keeps each record small
/// without truncating the observer ledger or dropping its events.
const HISTORY_SNAPSHOT_INTERVAL: u32 = 64;

/// Source-current snapshots do not grant unvalidated action or seat evidence trust.
pub(crate) struct AdmittedHistory {
    observer: Observer,
    partial: ObservingTracker,
    ids: RandomState,
    session_id: Id,
    sequence: u64,
    last_generation: u64,
    last_captured_at_ms: Option<u64>,
    minimum_epoch: u64,
    partial_sequence: u64,
    last_partial: Option<Ticket>,
    /// Highest ledger `event_sequence` already delivered to the consumer.
    history_since: u64,
    /// Delta emissions since the last complete view.
    history_emissions: u32,
    /// `(session, table, hand)` the consumer's events belong to.
    history_key: Option<(Option<Id>, Option<Id>, Option<Id>)>,
}

impl AdmittedHistory {
    pub(crate) fn new() -> Result<Self, RunError> {
        let ids = RandomState::new();
        let session_id = Id(ids.hash_one((std::process::id(), unix_ms()?)).max(1));
        Ok(Self {
            observer: Observer::default(),
            partial: ObservingTracker::default(),
            ids,
            session_id,
            sequence: 0,
            last_generation: 0,
            last_captured_at_ms: None,
            minimum_epoch: 0,
            partial_sequence: 0,
            last_partial: None,
            history_since: 0,
            history_emissions: 0,
            history_key: None,
        })
    }

    fn record_admission(&mut self, ticket: &Ticket, now_ms: u64, config: &RuntimeConfig) -> bool {
        self.record_source(ticket, now_ms, config, false)
    }

    fn record_source(
        &mut self,
        ticket: &Ticket,
        now_ms: u64,
        config: &RuntimeConfig,
        capture_only: bool,
    ) -> bool {
        // A blocked stdout write must not turn an expired observation into a capture.
        let Some(age) = now_ms.checked_sub(ticket.captured_at_ms) else {
            return false;
        };
        let limit = config.max_frame_age_ms.min(config.decision_budget_ms);
        let limit = if capture_only {
            limit.min(CAPTURE_HEALTH_INTERVAL_MS)
        } else {
            limit
        };
        if age >= limit
            || ticket.generation < self.last_generation
            || !capture_only && ticket.generation == self.last_generation
            || ticket.epoch < self.minimum_epoch
            || self.last_captured_at_ms.is_some_and(|last| {
                ticket.captured_at_ms < last || capture_only && ticket.captured_at_ms == last
            })
        {
            return false;
        }
        let Some(sequence) = self.sequence.checked_add(1) else {
            return false;
        };
        self.sequence = sequence;
        self.last_generation = ticket.generation;
        self.last_captured_at_ms = Some(ticket.captured_at_ms);
        self.minimum_epoch = ticket.epoch;
        // Hash only run/process/window provenance, never names or model fields.
        let table_id = Id(self
            .ids
            .hash_one((
                self.session_id.0,
                ticket.identity.process_id,
                ticket.identity.hwnd,
            ))
            .max(1));
        let _ = self.observer.observe(&Snapshot {
            capture: Capture {
                session_id: self.session_id,
                table_id,
                sequence,
                captured_at_ms: ticket.captured_at_ms,
                // A content generation can cover many fresh identical captures.
                // This opaque reference advances only after source lease checks.
                ticket: Id(sequence),
            },
            // Recognition and physical seat/badge evidence remain unapproved.
            // Never map a player-vector index or a role change into a trusted seat.
            quality_approved: false,
            ..Snapshot::default()
        });
        true
    }

    fn invalidate(&mut self, generation: u64, epoch: u64) {
        // Every admitted capture already broke continuity with UnvalidatedSource.
        // Reject replay without manufacturing another capture or resetting the ledger.
        self.last_generation = self.last_generation.max(generation);
        self.minimum_epoch = self.minimum_epoch.max(epoch);
        self.partial.invalidate();
    }

    fn record_partial(
        &mut self,
        ticket: &Ticket,
        value: &PartialObservationView,
        now_ms: u64,
        config: &RuntimeConfig,
    ) -> bool {
        let limit = config.max_frame_age_ms.min(config.decision_budget_ms);
        if ticket.generation < self.last_generation
            || ticket.epoch < self.minimum_epoch
            || now_ms
                .checked_sub(ticket.captured_at_ms)
                .is_none_or(|age| age >= limit)
            || self.last_partial.as_ref().is_some_and(|last| {
                ticket == last
                    || ticket.generation < last.generation
                    || ticket.epoch < last.epoch
                    || ticket.captured_at_ms < last.captured_at_ms
            })
        {
            return false;
        }
        let Some(sequence) = self.partial_sequence.checked_add(1) else {
            return false;
        };
        let Some(epoch) = ticket.epoch.checked_add(1) else {
            return false;
        };
        let table_id = Id(self
            .ids
            .hash_one((
                self.session_id.0,
                ticket.identity.process_id,
                ticket.identity.hwnd,
            ))
            .max(1));
        let mut frame = ObservingFrame {
            capture: Capture {
                session_id: self.session_id,
                table_id,
                sequence,
                captured_at_ms: ticket.captured_at_ms,
                ticket: Id(sequence),
            },
            source_epoch: Id(epoch),
            current_capture_validated: true,
            expires_at_ms: ticket.captured_at_ms.saturating_add(limit),
            ..ObservingFrame::default()
        };
        // Unknown hand/occupancy/wager/badge stays unknown. Fitted stack evidence
        // enters only the partial display store, never an actionable GameState.
        for (index, (seat, field)) in value.seats.iter().zip(STACK_FIELDS).enumerate() {
            if seat.seat != index as u8 + 1 {
                return false;
            }
            if value.verified_fields.contains(&field) {
                if let Some(amount) = seat.displayed_stack {
                    frame.seats[index].displayed_stack = Some(Reading::current(
                        &frame,
                        Evidence::trusted(u64::from(amount)),
                    ));
                }
            }
        }
        for (index, (seat, field)) in value.seats.iter().zip(WAGER_FIELDS).enumerate() {
            if value.verified_fields.contains(&field) {
                if let Some(amount) = seat.visible_wager {
                    frame.seats[index].visible_wager = Some(Reading::current(
                        &frame,
                        Evidence::trusted(u64::from(amount)),
                    ));
                }
            }
        }
        let mut actors = Vec::new();
        for (index, seat) in value.seats.iter().enumerate() {
            let fields = SCENE_VERIFIED_FIELDS[index];
            if value.verified_fields.contains(&fields[0]) && seat.occupied == Some(false) {
                frame.seats[index].occupant_id = Evidence {
                    value: None,
                    trusted: true,
                    confidence: None,
                };
            }
            if value.verified_fields.contains(&fields[1]) {
                match seat.status {
                    Some(ingest::partial::SeatStatus::Folded) => {
                        frame.seats[index].folded = Evidence::trusted(true)
                    }
                    Some(
                        ingest::partial::SeatStatus::Active | ingest::partial::SeatStatus::AllIn,
                    ) => frame.seats[index].folded = Evidence::trusted(false),
                    _ => {}
                }
            }
            if value.verified_fields.contains(&fields[6]) && seat.acting == Some(true) {
                actors.push(index as u8);
            }
        }
        if actors.len() == 1 {
            frame.acting_seat = Some(Reading::current(&frame, Evidence::trusted(actors[0])));
        }
        // Visible badges have no proven occurrence/order, and occupancy is not
        // occupant continuity or an original dealt-in roster. Do not fabricate them.
        let _ = self.partial.observe(&frame, now_ms);
        self.partial_sequence = sequence;
        self.last_partial = Some(ticket.clone());
        self.last_generation = self.last_generation.max(ticket.generation);
        self.minimum_epoch = self.minimum_epoch.max(ticket.epoch);
        true
    }
}

/// One bounded `history` record. The observer ledger is never truncated: a
/// complete view is sent at a bounded cadence or when the target changes, and
/// every other record carries exactly the ledger events appended since the
/// previous record. `history_omitted` reports any events a single record could
/// not carry, so no gap is silent.
fn history_record(history: &mut AdmittedHistory, emitted_at_unix_ms: u64) -> serde_json::Value {
    let since = history.history_since;
    let (mut summary, pending_start, pending) = {
        let observer = &history.observer;
        let summary = observer.summary();
        let start = observer
            .events()
            .partition_point(|event| event.event_sequence <= since);
        (summary, start, observer.events().len() - start)
    };
    let key = (summary.session_id, summary.table_id, summary.hand_id);
    let snapshot = history.history_key != Some(key)
        || history.history_emissions >= HISTORY_SNAPSHOT_INTERVAL
        || pending > MAX_EVENT_VIEW;
    let through = if snapshot {
        summary
            .events
            .last()
            .map_or(since, |event| event.event_sequence)
    } else {
        history
            .observer
            .events()
            .last()
            .map_or(since, |event| event.event_sequence)
    };
    let omitted = if snapshot {
        pending.saturating_sub(summary.events.len()) as u64
    } else {
        0
    };
    if !snapshot {
        // A delta is exactly the contiguous run appended after the cursor.
        summary.events = history.observer.events()[pending_start..].to_vec();
    }
    history.history_since = through;
    history.history_key = Some(key);
    history.history_emissions = if snapshot {
        0
    } else {
        history.history_emissions.saturating_add(1)
    };
    json!({"schema_version":2,"event":"history","summary":summary,
        "history_since":since,"history_through":through,"history_snapshot":snapshot,
        "history_omitted":omitted,"emitted_at_unix_ms":emitted_at_unix_ms})
}

pub(crate) fn emit_with_history(
    record: &serde_json::Value,
    ticket: Option<&Ticket>,
    partial: Option<&PartialObservationView>,
    history: &mut AdmittedHistory,
    clock: &impl Clock,
    config: &RuntimeConfig,
    sink: &mut impl FnMut(&serde_json::Value) -> Result<(), RunError>,
) -> Result<(), RunError> {
    sink(record)?;
    match record["event"].as_str() {
        Some("observation_invalidated" | "partial_observation_invalidated") => {
            if let (Some(generation), Some(epoch)) =
                (record["generation"].as_u64(), record["epoch"].as_u64())
            {
                history.invalidate(generation, epoch);
            }
        }
        Some("observation")
            if ticket
                .is_some_and(|ticket| history.record_admission(ticket, clock.now_ms(), config)) =>
        {
            sink(&history_record(history, unix_ms()?))?;
        }
        Some("partial_observation") => {
            if let (Some(ticket), Some(value)) = (ticket, partial) {
                if history.record_partial(ticket, value, clock.now_ms(), config) {
                    // Independent readings never replace the public history prefix
                    // with a second, shorter ledger.
                    sink(&history_record(history, unix_ms()?))?;
                }
            }
        }
        Some("capture_health")
            if record["fresh_capture"] == true
                && ticket.is_some_and(|ticket| {
                    history.record_source(ticket, clock.now_ms(), config, true)
                }) =>
        {
            sink(&history_record(history, unix_ms()?))?;
        }
        _ => {}
    }
    Ok(())
}

fn load_private_registry<T: serde::de::DeserializeOwned>(
    root: &std::path::Path,
    path: &str,
) -> Result<T, RunError> {
    use std::io::Read;
    let invalid = || RunError::Message("invalid private wager registry".into());
    let relative = std::path::Path::new(path);
    if relative.is_absolute()
        || !relative.starts_with(".local")
        || path.contains(':')
        || relative
            .components()
            .any(|c| !matches!(c, std::path::Component::Normal(_)))
        || relative.extension().is_none_or(|ext| ext != "json")
    {
        return Err(invalid());
    }
    let root = root.canonicalize().map_err(|_| invalid())?;
    let base = root.join(".local").canonicalize().map_err(|_| invalid())?;
    let file = root.join(relative).canonicalize().map_err(|_| invalid())?;
    if !base.starts_with(&root) || !file.starts_with(&base) || !file.is_file() {
        return Err(invalid());
    }
    let mut bytes = Vec::new();
    std::fs::File::open(file)
        .map_err(|_| invalid())?
        .take(64 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| invalid())?;
    if bytes.len() > 64 * 1024 {
        return Err(invalid());
    }
    serde_json::from_slice(&bytes).map_err(|_| invalid())
}

/// Poll the CDP lobby surface: emits a `lobby-snapshot` on every listing
/// change, and a `cdp-status` record on every reachability transition (so a
/// client close/reopen is visible in the stream, not a silent gap).
/// `max_ticks` bounds the loop for tests; `None` runs until process exit.
pub(crate) fn run_cdp_poller(
    port: u16,
    interval: std::time::Duration,
    max_ticks: Option<u32>,
    sink: &mut impl FnMut(&serde_json::Value),
) {
    use ingest::adapter::cdp;
    let mut last_seq: Option<u64> = None;
    let mut last_state: Option<&'static str> = None;
    let mut ticks = 0u32;
    loop {
        let state: &'static str = match cdp::lobby_snapshot(port) {
            Ok(Some(snapshot)) => {
                if last_seq != Some(snapshot.seq) || last_state != Some("snapshot") {
                    last_seq = Some(snapshot.seq);
                    sink(&json!({
                        "kind": "lobby-snapshot",
                        "adapter": "cdp",
                        "extraction": cdp::CDP_EXTRACTION_VERSION,
                        "path": snapshot.path,
                        "user": snapshot.user,
                        "wallet": snapshot.wallet_raw,
                        "wallet_amount": snapshot.wallet_amount,
                        "seq": snapshot.seq,
                        "captured_at_ms": snapshot.captured_at_ms,
                        "tables": snapshot.tables,
                    }));
                }
                "snapshot"
            }
            Ok(None) => {
                if last_state != Some("no-lobby-page") {
                    sink(&json!({"kind": "cdp-status", "state": "no-lobby-page", "port": port}));
                }
                "no-lobby-page"
            }
            Err(error) => {
                // Detail only on the transition, so steady state stays quiet.
                if last_state != Some("unavailable") {
                    sink(&json!({
                        "kind": "cdp-status", "state": "unavailable",
                        "detail": error, "port": port
                    }));
                }
                "unavailable"
            }
        };
        last_state = Some(state);
        ticks += 1;
        if max_ticks == Some(ticks) {
            return;
        }
        std::thread::sleep(interval);
    }
}

pub fn run(options: Options) -> Result<(), RunError> {
    if !cfg!(target_os = "windows") {
        return Err(RunError::Message(
            "live capture requires Windows 10 version 1903 or later; use --stdin on this platform"
                .into(),
        ));
    }
    emit(&configuration_event(&options))?;

    // CDP lobby poller (Phase 1): observes the Electron lobby surface over
    // loopback CDP and emits `lobby-snapshot` records whenever the listing
    // changes. Spawned before the identity gate so it still reports when the
    // capture identity is uncalibrated. Fail-quiet.
    if options.cdp_enabled {
        let port = options.cdp_port;
        std::thread::spawn(move || {
            run_cdp_poller(
                port,
                std::time::Duration::from_millis(2_000),
                None,
                &mut |record| {
                    let _ = emit(record);
                },
            );
        });
    }
    if !options.discovery.has_identity() {
        emit(
            &json!({"schema_version":2,"event":"status","state":"configuration_required",
            "reason":"run --list-windows; configure --exe-name using the actual executable name"}),
        )?;
        return Err(RunError::Message(
            "no calibrated application identity configured".into(),
        ));
    }
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("binary crate is inside the checkout");
    let mut backend = LayaBackend::new(options.vlm, lobby_size(&options.discovery))
        .map_err(|error| RunError::Message(error.to_string()))?;
    if let Some(path) = options.wager_registry {
        backend = backend
            .with_wager_registry(load_private_registry(root, &path)?)
            .map_err(|_| RunError::Message("invalid private wager registry".into()))?;
    }
    if let Some(path) = options.scene_registry {
        backend = backend
            .with_scene_registry(load_private_registry(root, &path)?)
            .map_err(|_| RunError::Message("invalid private scene registry".into()))?;
    }
    let pipeline = Pipeline::with_seed(options.seed);
    // Doorbell: the worker pings on completion so the loop wakes immediately
    // instead of waiting out the capture cadence.
    let doorbell = std::sync::Arc::new((std::sync::Mutex::new(0u64), std::sync::Condvar::new()));
    let worker_doorbell = doorbell.clone();
    let worker = ThreadWorker::new(move |job| {
        let result = analyze_laya_frame(&backend, &pipeline, &job.frame, job.deadline);
        let (lock, cvar) = &*worker_doorbell;
        if let Ok(mut seen) = lock.lock() {
            *seen += 1;
        }
        cvar.notify_all();
        result
    });
    let poll_ms = options.runtime.poll_ms;
    let config = options.runtime.clone();
    // Only the explicit build checkout root may contain native private images.
    // Recorder initialization or I/O failures latch metadata, not capture errors.
    let capture = RecordingCapturer::new(
        PlatformCapture::default(),
        root,
        options.recording,
        SystemTime::now(),
    );
    let recording = capture.recording();
    let mut runtime = LiveRuntime::new(capture, worker, options.discovery, options.runtime)
        .map_err(|e| RunError::Message(e.into()))?;
    // Live runs use the field lanes: per-region change detection keeps partial
    // candidates coherent instead of clearing them on every felt animation tick,
    // and the activity sample feeds the admission schedule. The bounded probe
    // also seeds partial consensus before the first gate observation.
    runtime.enable_activity_probe();
    let clock = MonotonicClock::default();
    let mut history = AdmittedHistory::new()?;
    loop {
        for event in runtime.tick(&clock) {
            let partial = match &event {
                LiveEvent::PartialObservation { value, .. } => Some(value.clone()),
                _ => None,
            };
            let ticket = match &event {
                LiveEvent::Observation { ticket, .. }
                | LiveEvent::PartialObservation { ticket, .. }
                | LiveEvent::PerceptionDiagnostics { ticket, .. }
                | LiveEvent::Recommendation { ticket, .. } => Some(ticket.clone()),
                LiveEvent::CaptureHealth {
                    generation,
                    epoch,
                    captured_at_ms: Some(captured_at_ms),
                    identity: Some(identity),
                    fresh_capture: true,
                    ..
                } => Some(Ticket {
                    identity: identity.clone(),
                    generation: *generation,
                    epoch: *epoch,
                    captured_at_ms: *captured_at_ms,
                    captured_at_unix_ms: None,
                }),
                _ => None,
            };
            let emitted_at = unix_ms()?;
            match event_record(
                event,
                clock.now_ms(),
                emitted_at,
                &config,
                recording.snapshot(),
            )? {
                Some(record) => emit_with_history(
                    &record,
                    ticket.as_ref(),
                    partial.as_deref(),
                    &mut history,
                    &clock,
                    &config,
                    &mut emit,
                )?,
                None => {
                    runtime.publication_dropped();
                    let ticket = ticket.expect("only leased events can expire at publication");
                    emit(
                        &json!({"schema_version":2,"event":"discarded","generation":ticket.generation,
                        "reason":"publication-expired","emitted_at_unix_ms":emitted_at}),
                    )?;
                    emit_with_history(
                        &json!({"schema_version":2,"event":"observation_invalidated","generation":ticket.generation,
                        "epoch":ticket.epoch,"identity":ticket.identity,"reason":"publication-expired",
                        "emitted_at_unix_ms":emitted_at}),
                        None,
                        None,
                        &mut history,
                        &clock,
                        &config,
                        &mut emit,
                    )?;
                }
            }
        }
        // Event-driven wait (Phase 1): wake on the worker doorbell or at the
        // runtime's next due deadline; `poll_ms` survives only as the capture
        // cadence cap for idle stretches.
        let due_ms = runtime.next_wake_in_ms(clock.now_ms());
        let wait = std::time::Duration::from_millis(due_ms.min(poll_ms))
            .max(std::time::Duration::from_millis(2));
        let (lock, cvar) = &*doorbell;
        if let Ok(guard) = lock.lock() {
            let _ = cvar.wait_timeout(guard, wait);
        }
    }
}

pub fn support_script(name: &str) -> Result<PathBuf, RunError> {
    let candidates = [
        std::env::var_os("COINPOKER_SUPPORT_DIR").map(PathBuf::from),
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(PathBuf::from)),
        std::env::current_dir().ok(),
        Some(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")),
    ];
    candidates.into_iter().flatten().map(|dir| dir.join("scripts").join(name))
        .find(|path| path.is_file()).ok_or_else(|| RunError::Message(format!("missing scripts/{name}; run from the repository or unpack the complete release artifact")))
}

pub fn doctor(options: Options) -> Result<(), RunError> {
    let script = support_script("doctor.py")?;
    let interpreter = if cfg!(windows) { "python" } else { "python3" };
    let mut command = Command::new(interpreter);
    command
        .arg(script)
        .arg("--binary")
        .arg(std::env::current_exe()?)
        .env("COINPOKER_VLM_ENDPOINT", options.vlm.endpoint)
        .env("COINPOKER_VLM_MODEL", options.vlm.model);
    for (name, value) in [
        ("COINPOKER_EXE_NAME", options.discovery.exe_name),
        (
            "COINPOKER_PID",
            options.discovery.process_id.map(|p| p.to_string()),
        ),
        (
            "COINPOKER_WINDOW_HWND",
            options
                .discovery
                .window_hwnd
                .map(|hwnd| format!("0x{hwnd:x}")),
        ),
        ("COINPOKER_WINDOW_TITLE", options.discovery.table_title),
        ("COINPOKER_LOBBY_TITLE", options.discovery.lobby_title),
        (
            "COINPOKER_LOBBY_SIZE",
            match (
                options.discovery.lobby_width,
                options.discovery.lobby_height,
            ) {
                (Some(width), Some(height)) if width > 0 && height > 0 => {
                    Some(format!("{width}x{height}"))
                }
                _ => None,
            },
        ),
    ] {
        if let Some(value) = value {
            command.env(name, value);
        } else {
            command.env_remove(name);
        }
    }
    let status = command.status()?;
    if status.success() {
        Ok(())
    } else {
        Err(RunError::Message(
            "doctor found failed or blocked checks; see its report".into(),
        ))
    }
}

#[cfg(test)]
#[path = "live_tests.rs"]
mod tests;
