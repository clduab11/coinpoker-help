# Graph Report - coinpoker-help  (2026-10-14)

## Corpus Check
- 142 files · ~343,512 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 4, .toml 2, .css 1)

## Summary
- 4687 nodes · 11731 edges · 201 communities (141 shown, 60 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 406 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2f80e2fa`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- CompanionUiTests
- recorder.rs
- live_runtime.rs
- PartialTests
- PracticeAttachment
- VlmError
- test_laya_numeric.py
- VerifiedField
- windows.rs
- observing.rs
- live.rs
- ContextTests
- assembly.rs
- CaptureTests
- change_detect.rs
- laya.rs
- ManualFeedTests
- AttachTests
- decision.rs
- discovery.rs
- LiveEvent
- coinpoker-help — Readiness Assessment and Validation Plan
- json
- DecisionView
- observer.rs
- laya_attach.py
- screen.rs
- SupervisorTests
- laya_capture.py
- StateTests
- table_rules.rs
- parser.rs
- runtime.rs
- client.rs
- experimental.rs
- test_laya_server.py
- cli.rs
- state_machine.rs
- laya-server.py
- DiagnosticReason
- ranges.rs
- Observer
- questions.rs
- GapReason
- config.rs
- seat_scene.rs
- src/partial.rs
- serde
- equity.rs
- ActionRecord
- partial_observation.rs
- evaluation.rs
- Badge
- PokerReferenceTests
- Practice-Sandbox Dashboard, Observed History, and Seated Data
- ExperimentalCandidateTests
- betting.rs
- manual_inference.rs
- ScreenObservation
- betting_entropy.rs
- Product facts the integration depends on (see the integration plan for details)
- FieldName
- CaptureError
- app.js
- FakeEngine
- profile.rs
- temporal.rs
- vlm.rs
- InferenceConsentTests
- TableContentWitness
- headless.rs
- inference_loop
- Archetype
- DoctorTests
- Rank
- Position6max
- laya/partial.rs
- ManualSessionFeed
- state
- manual_capture.rs
- laya_context.py
- coinpoker-help — Laya Vision as the sole live perception backend
- FeatureCacheTests
- SourcePolicy
- .now_ms
- Execution Steps
- Bounded Diagnostics and Sustained Observation
- extend_partial
- .setUp
- 7. Phase gates
- WindowInfo
- laya_actions.py
- scene.rs
- .new
- IntegrationTests
- AutomaticStartupTests
- Next Conversation: Deliver Verified Live Table Data
- laya_showdown.py
- super
- EventEvidence
- saved_capture_schedule.rs
- DiscoveryState
- AcceptanceTests
- VisualTests
- Laya Vision Prototype — Phase A Design (Question Set + Calibration Corpus)
- VisualWorker
- Engine
- HttpTests
- BatchTests
- HttpTests
- WagerTests
- RevealedCardTests
- laya_numeric.py
- BoardTemplateTests
- PlayerState
- coinpoker-help
- Suit
- FeedFailureTests
- DecisionComplexity
- native_decision
- NumericWorker
- BoardTemplateRecognizer
- Windows installation and calibration
- time
- TemporalConfigError
- Local visual evaluation, manifest format 2
- coinpoker
- StaticUiTests
- AutoAttachFeed
- fake_server
- Windows VLM compatibility record
- Windows acceptance report, format 1
- lobby-observation.ps1
- Contributing
- laya_dashboard.py
- Windows validation evidence
- manifest.json
- FakePrep
- PolicyTests
- Security policy
- Time
- Model and runtime provenance
- Part 1: Recognition, Evidence, And Table-First UI
- CaptureControlTests
- prompt.rs
- EngineBatchTests
- ScreenBitmap
- result
- Project Instructions
- handle_predict
- MonitorControlUiTests
- .ingest
- field_statuses
- 2. Steps and gates
- geometry.rs
- ContextWorkerTests
- VisualUiTests
- random_pass
- .test_sustained_supervisor_runs_45_minutes_and_only_caps_evidence_and_logs
- Service
- make_handler
- 3. Assembly (Rust `laya/assembly.rs`)
- ExperimentalTests
- cmd_serve
- ReadoutLogTests
- main.rs
- OriginalCaptureProjectionTests
- .batch
- outs.rs
- LiteralTests
- PercentTests
- PartialObservationView
- NumericUiTests
- CaptureSource
- partial_view
- Ticket
- Position
- AttachResult
- listing
- _PipeReader
- RangeError
- read

## God Nodes (most connected - your core abstractions)
1. `CompanionUiTests` - 131 edges
2. `CaptureError` - 78 edges
3. `VerifiedField` - 71 edges
4. `VlmError` - 70 edges
5. `PartialTests` - 67 edges
6. `Time` - 54 edges
7. `Value` - 53 edges
8. `ManualFeedTests` - 52 edges
9. `Id` - 49 edges
10. `AttachTests` - 46 edges

## Surprising Connections (you probably didn't know these)
- `Continuation: Actual Phase Timeline` --references--> `status()`  [INFERRED]
  .kilo/plans/1791496776779-repo-readiness-and-next-steps.md → scripts/dashboard/app.js
- `JSON-lines contracts, live schema version 2` --references--> `event()`  [INFERRED]
  docs/EVENTS_V2.md → scripts/laya_context.py
- `2. Decisions (confirmed with the user 2026-10-09T21:00Z)` --references--> `status()`  [INFERRED]
  .kilo/plans/1791578389113-laya-gate-f-live-run-docs.md → scripts/dashboard/app.js
- `T3. Pins, server, latency bench` --references--> `status()`  [INFERRED]
  .kilo/plans/1791578389113-laya-gate-f-live-run-docs.md → scripts/dashboard/app.js
- `T5. Gate F decision` --references--> `status()`  [INFERRED]
  .kilo/plans/1791578389113-laya-gate-f-live-run-docs.md → scripts/dashboard/app.js

## Import Cycles
- 2-file cycle: `crates/ingest/src/capture.rs -> crates/ingest/src/discovery.rs -> crates/ingest/src/capture.rs`

## Communities (201 total, 60 thin omitted)

### Community 1 - "recorder.rs"
Cohesion: 0.07
Nodes (58): budget_reason(), recording_end_reason(), BoundedHashWriter, BoundedHashWriter<W>, CaptureStamp, changed_visibility_same_stamp_does_not_reuse_old_archival_mask(), create_file(), directory_guard() (+50 more)

### Community 2 - "live_runtime.rs"
Cohesion: 0.09
Nodes (77): convert_cards(), cross_crate_pipeline_produces_a_decision_view(), FLOP_STATE, state_machine_and_parser_agree_on_phases(), activate(), activate_observation(), admitted_unseated_observation_has_a_source_lease_and_no_placeholder_controls(), ambiguous_windows_and_permission_loss_invalidate_without_duplicate_clears() (+69 more)

### Community 4 - "PracticeAttachment"
Cohesion: 0.18
Nodes (6): 4. Produce Occupancy, Identity Continuity, And Role, PracticeAttachment, capture_argv(), LiveFeed, local_path(), PrivateLedger

### Community 5 - "VlmError"
Cohesion: 0.17
Nodes (14): ScriptedBackend, LayaClient, PassAnswers, probability(), schema(), Pass, read_bounded(), remaining_budget() (+6 more)

### Community 6 - "test_laya_numeric.py"
Cohesion: 0.11
Nodes (6): Template, canonical(), LiteralTests, PixelLogicTests, PrivateOriginalTests, receipt()

### Community 7 - "VerifiedField"
Cohesion: 0.03
Nodes (65): VerifiedField, Acting1, Acting2, Acting3, Acting4, Acting5, Acting6, Badge1 (+57 more)

### Community 8 - "windows.rs"
Cohesion: 0.06
Nodes (27): check_os(), classify(), classify_visible_surface(), creation_time_and_capture_topology_are_fresh_witnesses_not_reusable_pid_proof(), desktop(), foreign_shared_executable_process_and_wrong_table_root_do_not_grant_exception(), FRAME_POOL_BUFFERS, FRAME_WAIT_TIMEOUT (+19 more)

### Community 9 - "observing.rs"
Cohesion: 0.13
Nodes (44): noul(), Id, advance(), asserted(), badges_persist_flicker_and_renew_with_existing_ledger_provenance(), call_cost_uses_live_credit_not_visible_wager_ante_or_total_commitment(), current_pot_odds_requires_matching_eligible_sidepot_and_convention(), default_missing_fields_are_not_zero_and_unvalidated_capture_is_separate() (+36 more)

### Community 10 - "live.rs"
Cohesion: 0.09
Nodes (47): a_new_run_does_not_inherit_history_or_admission_counters(), admitted_observation_emits_one_opaque_gap_summary_after_successful_write(), assert_worker_category(), configuration_event(), configuration_event_reports_laya_perception(), current_capture_health_tracks_unvalidated_gaps_without_inference(), current_laya_unseated_admission_propagates_without_hero_placeholders(), current_observation_records_are_allowlisted_leased_and_name_private() (+39 more)

### Community 11 - "ContextTests"
Cohesion: 0.07
Nodes (12): ContextTimeline, event(), ContextTests, FakeOcr, GenuineProfileReplay, OcrCoordinateTests, OriginalOcrReplay, profile_words() (+4 more)

### Community 12 - "assembly.rs"
Cohesion: 0.09
Nodes (44): acceptance_floor_board_one_checks_every_card_and_no_card_slot(), acceptance_floor_keeps_noul_fallbacks_and_truncation_at_exact_boundaries(), acceptance_floor_p0_boundary_and_low_overrides_enforce_both_polarities(), assemble(), assemble_script(), assert_table_null(), board(), choice() (+36 more)

### Community 14 - "change_detect.rs"
Cohesion: 0.11
Nodes (34): animated_tile_does_not_block_stability(), animated_window_zero_disables_suppression(), animation_cannot_become_stable_until_it_stops(), animation_suppression_bounds_are_validated(), change_outside_a_suppressed_tile_still_triggers(), ChangeDetector, ChangeDetectorConfig, ChangeResult (+26 more)

### Community 15 - "laya.rs"
Cohesion: 0.10
Nodes (41): analyze_runs_crops_through_the_server_and_assembles_an_envelope(), automatic_numeric_pair_refreshes_pot_and_selected_stack_without_a_slow_large_batch(), automatic_partial_passes_do_not_run_fields_after_unqualified_core(), automatic_partial_passes_keep_core_witness_floors_and_independent_unknowns(), automatic_partial_passes_never_reuse_answers_from_previous_source_jobs(), automatic_partial_passes_reject_extensions_before_encoding_or_io(), automatic_partial_passes_reject_invalid_seats_and_elapsed_leases_without_io(), backend() (+33 more)

### Community 17 - "AttachTests"
Cohesion: 0.11
Nodes (6): AttachTests, encode(), listing(), profile(), records(), window()

### Community 18 - "decision.rs"
Cohesion: 0.09
Nodes (39): Action, Call, Check, Fold, Raise, calls_when_equity_beats_break_even(), checks_when_no_bet_and_weak_equity(), decide() (+31 more)

### Community 19 - "discovery.rs"
Cohesion: 0.08
Nodes (40): lobby_size(), ambiguity_invalidates_previously_selected_filter(), app(), ApplicationInfo, calibrated_table_outranks_unknowns_and_lobbies_in_any_order(), CaptureManager, CaptureManager<S>, config() (+32 more)

### Community 20 - "LiveEvent"
Cohesion: 0.09
Nodes (18): Clock, LiveEvent, CaptureHealth, Clear, Discarded, Observation, ObservationInvalidated, PartialObservation (+10 more)

### Community 21 - "coinpoker-help — Readiness Assessment and Validation Plan"
Cohesion: 0.04
Nodes (47): 10. Out of scope, 1. Executive summary, 2. Phase 0 — COMPLETE (2026-10-08 UTC), 3. Phase 1 readiness — prerequisites verified, flagged items, 4. Phase 1 — Prerequisites & calibration (gates 1-3) [READY TO EXECUTE], 5. Phase 2 — Capture fidelity & lifecycle (gates 4-17) [BLOCKED on Phase 1], 6. Phase 3 — Corpus & candidate validation (gates 18-20) [BLOCKED on Phase 2], 7. Phase 4 — Remediation & closeout (+39 more)

### Community 22 - "json"
Cohesion: 0.08
Nodes (5): main(), assemble_board(), slot_features(), library(), PowerShellSyntaxTests

### Community 23 - "DecisionView"
Cohesion: 0.12
Nodes (21): analyze_frame(), analyze_laya_frame(), finish_analysis(), finish_laya_analysis(), Pipeline, FailedResultPort, ManualWorker<W>, synthetic_analysis() (+13 more)

### Community 24 - "observer.rs"
Cohesion: 0.18
Nodes (39): actions(), capture_and_action_sequence_gaps_prevent_invented_ordinals(), conflicting_capture_and_reversed_time_do_not_admit_actions(), contradictory_dealt_in_status_cannot_finalize_other_players_as_false(), contradictory_wager_and_unexplained_wager_clearing_interrupt_continuity(), corroborated_preflop_end_allows_known_outcomes_without_using_board_clearing(), default_evidence_and_nullable_amounts_do_not_mean_zero_or_false(), duplicate_persistent_flickering_and_renewed_badges_are_distinct() (+31 more)

### Community 25 - "laya_attach.py"
Cohesion: 0.10
Nodes (19): AttachError, AttachmentRule, _exe(), _integer(), _json(), constant(), pairs(), list_windows() (+11 more)

### Community 26 - "screen.rs"
Cohesion: 0.15
Nodes (43): a_hand_reset_requires_an_accepted_marker_not_a_single_empty_frame(), accepted_showdown_allows_a_direct_dealt_preflop(), agreeing_community_cards_do_not_require_a_matching_pot(), all_non_table_kinds_need_no_poker_payload_and_ignore_irrelevant_state(), assert_safe_category(), calibrated_table_titles_still_require_two_full_matching_observations(), CompletePlayerState, confirm() (+35 more)

### Community 27 - "SupervisorTests"
Cohesion: 0.06
Nodes (11): Goal and Decisions, Rollout and Out of Scope, Sustained Monitor Window Intake, Validation and Acceptance, Verified Diagnosis, CaptureTests, FakeFeed, FakeSelection (+3 more)

### Community 28 - "laya_capture.py"
Cohesion: 0.13
Nodes (25): Implementation Tasks, approve_inference(), AutomaticStart, confirm_source(), default_snapshot(), evidence_snapshot(), experimental_session_approved(), fail_session() (+17 more)

### Community 30 - "table_rules.rs"
Cohesion: 0.06
Nodes (29): anchored_seats_hold_at_every_supported_size(), assign_positions(), MAX_SEATS, names(), names_clockwise_from_button(), seat_position(), SeatingError, ButtonNotOccupied (+21 more)

### Community 31 - "parser.rs"
Cohesion: 0.06
Nodes (29): enforces_available_action_consistency(), extract_json_object(), fills_defaults_for_optional_fields(), GamePhase, Flop, Lobby, Preflop, River (+21 more)

### Community 32 - "runtime.rs"
Cohesion: 0.12
Nodes (19): CAPTURE_HEALTH_INTERVAL_MS, ControlView, DECISION_DEADLINE_CODE, DrawView, expired_worker_job_never_runs_analysis(), Freshness, MAX_WORKER_FAILURES, observation_is_current() (+11 more)

### Community 33 - "client.rs"
Cohesion: 0.15
Nodes (31): acceptance_floor_and_probabilities_are_retained_without_f32_rounding(), acceptance_floor_requires_a_finite_number_in_the_unit_interval(), batch_404_and_busy_do_not_retry_or_expose_error_bodies(), batch_keeps_per_pass_validation_and_independent_malformed_result_unknown(), batch_rejects_untrained_duplicate_or_expired_work_without_transport(), client(), each_pass_receives_only_the_remaining_total_or_request_budget(), errors_never_contain_request_or_response_payloads() (+23 more)

### Community 34 - "experimental.rs"
Cohesion: 0.14
Nodes (21): all_measured_draft_crops_are_explicit_unvalidated_and_scaled_without_new_regions(), append_diagnostics(), crop_digest(), CropWitness, descriptor_cannot_claim_approval_or_substitute_a_crop(), diagnostic_expiry_never_admits_experimental_fields_or_renews_source_provenance(), DONOR_PASS, empty_segmentation_is_unknown_never_zero_and_no_experiment_has_an_acceptance_floor() (+13 more)

### Community 35 - "test_laya_server.py"
Cohesion: 0.08
Nodes (23): Step 6 — scripts (no new .ps1), _check_files(), check_model_files(), check_runtime(), collect(), outcome(), record(), color_png() (+15 more)

### Community 36 - "cli.rs"
Cohesion: 0.12
Nodes (33): a_valid_state_recovers_after_invalid_input_without_duplicate_clears(), ACTION_STATE, assert_evaluation_category(), assert_private_output(), assert_stdin_category(), evaluates_synthetic_image_contracts_without_a_server(), help_prints_usage_and_succeeds(), invalid_stdin_state_invalidates_an_active_decision() (+25 more)

### Community 37 - "state_machine.rs"
Cohesion: 0.14
Nodes (34): Card, GameState, action_turning_on_emits_action_required_once(), available_action_change_emits_state_changed_while_action_remains_required(), first_observation_emits_state_changed(), first_observation_with_action_emits_action_required(), hero_card_change_emits_state_changed_while_action_remains_required(), initial_showdown_is_emitted_once_and_later_changes_are_reported() (+26 more)

### Community 38 - "laya-server.py"
Cohesion: 0.09
Nodes (14): BoundedErrorLog, cmd_fetch(), cmd_verify(), load_acceptance_floors(), load_experimental_metadata(), load_pins(), load_scene_registry(), load_seat_registry() (+6 more)

### Community 39 - "DiagnosticReason"
Cohesion: 0.06
Nodes (35): DiagnosticReason, Accepted, AwaitingConsensus, BelowFloor, BoardCountInvalid, BoardNoncontiguous, BoardPresenceUnknown, CropTooSmall (+27 more)

### Community 40 - "ranges.rs"
Cohesion: 0.13
Nodes (22): button_and_small_blind_add_tier_three(), classes(), display_round_trips_notation(), expand_dash_range(), expand_notation(), expands_dash_ranges_inclusively(), expands_offsuit_plus(), expands_pair_plus_through_aces() (+14 more)

### Community 41 - "Observer"
Cohesion: 0.12
Nodes (17): ActionCounts, Capture, Coverage, default_and_custom_limits_bound_event_view_and_all_retained_keys(), has_gap(), LedgerEvent, Limits, Observer (+9 more)

### Community 42 - "questions.rs"
Cohesion: 0.08
Nodes (23): acceptance_floor_is_required_and_validated_for_every_trained_pass(), calibrated(), question_set_version(), Calibration, Calibrated, Trained, Uncalibrated, UntrainedProvisional (+15 more)

### Community 43 - "GapReason"
Cohesion: 0.06
Nodes (33): ChipMovement, Ambiguous, Payout, PotCollection, Refund, TopUp, GapReason, ActionSequence (+25 more)

### Community 44 - "config.rs"
Cohesion: 0.09
Nodes (28): cli_overrides_environment_and_defaults(), FLAGS, hwnd_accepts_decimal_and_hexadecimal(), laya_defaults_apply_without_configuration(), laya_threshold_is_bounded_and_overridable_by_cli(), lobby_size_is_a_positive_pair(), Mode, Capture (+20 more)

### Community 45 - "seat_scene.rs"
Cohesion: 0.19
Nodes (24): assembled(), backend_default_never_requests_scene_and_explicit_fixture_encodes_distinct_seat_rois(), base_answers(), candidate(), choice(), config(), exact_whole_scene_witness_rejects_only_changed_seat_not_pot_stacks_or_wagers(), fake_response() (+16 more)

### Community 46 - "src/partial.rs"
Cohesion: 0.09
Nodes (31): BOARD_FIELDS, capabilities(), Capability, DiagnosticAdmission, Candidate, DecisionBudgetExpired, ObservationExpired, ObsoleteObservation (+23 more)

### Community 47 - "serde"
Cohesion: 0.08
Nodes (24): HandStart, BeforeActions, Partial, ButtonPolicy, Dead, Moving, map(), missing_button_blinds_policy_roster_and_empty_dead_button_stay_unknown() (+16 more)

### Community 48 - "equity.rs"
Cohesion: 0.11
Nodes (28): aces_dominate_kings_preflop(), board_royal_flush_splits_unknown_multiway_pot(), Card, EquityConfig, EquityError, BoardTooLarge, DeckExhausted, DuplicateCard (+20 more)

### Community 49 - "ActionRecord"
Cohesion: 0.08
Nodes (25): ActionBadge, ActionBasis, Badge, Commitment, Unknown, ActionKind, Bet, Call (+17 more)

### Community 50 - "partial_observation.rs"
Cohesion: 0.18
Nodes (27): a_board_transport_failure_still_attempts_amounts_but_deadline_aborts_all(), a_later_wager_deadline_keeps_prior_safe_field_traces_but_admits_nothing_and_stops_requests(), amount(), assemble(), assemble_wagers(), board_source_region_change_clears_only_changed_slot_and_dependent_count_phase(), choice(), confident_unreadable_card_is_occluded_not_an_accepted_identity_or_presence() (+19 more)

### Community 51 - "evaluation.rs"
Cohesion: 0.13
Nodes (18): Case, fail(), frame(), kind(), Manifest, metadata(), percentile(), Ratio (+10 more)

### Community 52 - "Badge"
Cohesion: 0.09
Nodes (21): Badge, AllIn, Bet, BigBlind, Call, Check, Fold, None (+13 more)

### Community 54 - "Practice-Sandbox Dashboard, Observed History, and Seated Data"
Cohesion: 0.07
Nodes (28): 10. P6: Validated Seated Branch and Sandbox Guidance, 11. Validation Matrix and Completion Records, 1. Decisions and Scope, 2. Verified Starting Point, 3. Meaning of the Metrics and Timing, 4. P0: Preserve the Baseline and Decruft Active Instructions, 5. P1: Browser Dashboard on the Same Port, 6. P2: Hero-Independent Watching History (+20 more)

### Community 55 - "ExperimentalCandidateTests"
Cohesion: 0.15
Nodes (3): candidate_record(), ExperimentalCandidateTests, ExperimentalFeedTests

### Community 56 - "betting.rs"
Cohesion: 0.13
Nodes (19): action(), additional_call_cost(), BettingRound, CallContext, CallCost, cumulative_short_reopens_only_seats_facing_a_full_increment_since_last_action(), folds_allin_calls_illegal_reopens_unknown_actions_and_street_reset(), full_raises_short_and_cumulative_allins_preserve_increment_and_individual_rights() (+11 more)

### Community 57 - "manual_inference.rs"
Cohesion: 0.09
Nodes (38): ACTIVITY_REGIONS, approval_json(), assert_sustained_board_pair_at_latency(), automatic_activity_requires_persistent_qualified_pixels_not_role_or_model_jitter(), automatic_idle_lobby_transient_ambiguous_jitter_and_resize_keep_finite_run_budgets(), automatic_partial_lanes_recover_after_core_only_admission_and_interruption(), cosmetic_and_one_stack_churn_do_not_block_independent_current_amounts(), cpu_board_readiness_cannot_change_manual_bounded_or_experimental_schedules() (+30 more)

### Community 58 - "ScreenObservation"
Cohesion: 0.11
Nodes (22): GateOutcome, has_table_evidence(), parse_screen_output(), same_visible_cards(), ScreenEnvelope, Lobby, OtherCoinPokerWindow, PokerTable (+14 more)

### Community 59 - "betting_entropy.rs"
Cohesion: 0.16
Nodes (17): BettingEntropy, BettingEntropyConfig, BettingEntropyConfigError, InvalidJitter, InvalidProbability, bounded_humanization_rejects_inverted_bounds(), bounded_humanization_respects_legal_amounts(), deterministic_for_a_seed() (+9 more)

### Community 60 - "Product facts the integration depends on (see the integration plan for details)"
Cohesion: 0.08
Nodes (24): AUTHORIZATIONS (edit before pasting), Captures, Decisions already made by the user, Envelope, Environment (already installed and pinned; see `scripts/laya-pins.json`), Frames and geometry, Goal, Live evidence tool (+16 more)

### Community 61 - "FieldName"
Cohesion: 0.08
Nodes (24): FieldName, Acting, Badge, BigBlind, BoardCount, BoardSlot, Dealer, DisplayedStack (+16 more)

### Community 62 - "CaptureError"
Cohesion: 0.08
Nodes (21): CaptureError, AmbiguousWindows, Backend, ConfigurationRequired, NoWindowSelected, PermissionDenied, StaleWindow, UnsupportedPlatform (+13 more)

### Community 63 - "app.js"
Cohesion: 0.05
Nodes (116): Checkpoint B Additions, Explicit Capture Stop, Historical Checkpoint A/B Startup, JSON-lines contracts, live schema version 2, Live records, Monitor and Reference, browser snapshot version 1, Replay, listing, doctor and evaluation, States and reasons (+108 more)

### Community 64 - "FakeEngine"
Cohesion: 0.22
Nodes (4): FakeEngine, HandleTests, png(), ValidateTests

### Community 65 - "profile.rs"
Cohesion: 0.16
Nodes (11): default_profile_has_human_plausible_parameters(), GhostProfile, json_round_trip_preserves_parameters(), ProfileError, Io, Parse, Validation, ProfileValidationError (+3 more)

### Community 66 - "temporal.rs"
Cohesion: 0.20
Nodes (9): invalid_manual_config_does_not_panic(), median_of(), medians_increase_with_complexity(), rejects_invalid_temporal_config(), rng(), samples_stay_within_clamp_bounds(), sampling_is_deterministic_for_a_seed(), TemporalConfig (+1 more)

### Community 67 - "vlm.rs"
Cohesion: 0.09
Nodes (14): base64_png(), defaults_target_the_loopback_laya_server(), encode_png(), error_codes_are_closed_categories(), http_agent(), png_encoding_round_trips(), validate_endpoint(), VlmBackend (+6 more)

### Community 69 - "TableContentWitness"
Cohesion: 0.14
Nodes (12): PartialObservation, region_digest(), region_matches(), region_witness(), RegionWitness, SourceRegionWitnesses, SourceWitnessError, AlreadyBound (+4 more)

### Community 70 - "headless.rs"
Cohesion: 0.18
Nodes (11): Capture, Emit, emits_clear_event(), emits_one_json_line_per_decision(), HeadlessEmitter, HeadlessEmitter<E>, std::sync::Arc<Capture>, stdout() (+3 more)

### Community 71 - "inference_loop"
Cohesion: 0.17
Nodes (9): Approval, ActivityGate, automatic_gate_rejects_duplicate_expired_and_geometry_only_activity_evidence(), inference_loop(), ManualSource, ManualSource<'a, S, C>, ManualWorker, run() (+1 more)

### Community 72 - "Archetype"
Cohesion: 0.09
Nodes (27): Archetype, Lag, LoosePassive, Tag, TightPassive, Unknown, Classification, Classifier (+19 more)

### Community 74 - "Rank"
Cohesion: 0.12
Nodes (18): Rank, Ace, Eight, Five, Four, Jack, King, Nine (+10 more)

### Community 75 - "Position6max"
Cohesion: 0.14
Nodes (10): Position6max, .ALL, Bb, Btn, Co, Hj, Sb, Utg (+2 more)

### Community 76 - "laya/partial.rs"
Cohesion: 0.12
Nodes (17): amount(), assemble_partial(), assemble_partial_with_wagers(), RANKS, Reading, record(), run_reading(), SUITS (+9 more)

### Community 78 - "state"
Cohesion: 0.13
Nodes (7): capture(), FiniteCollectorTests, MeasurementTests, profile(), run(), sample(), state()

### Community 79 - "manual_capture.rs"
Cohesion: 0.12
Nodes (18): automatic_approval_requires_its_own_policy_and_never_a_seated_assertion(), capture_loop(), emit_status(), experimental_approval_is_bounded_automatic_only_and_capture_flag_is_explicit(), fail(), FakeSource, manual_capture_approval_is_fresh_strict_and_bounded(), manual_capture_fake_source_count_resize_and_stop_are_one_shot() (+10 more)

### Community 80 - "laya_context.py"
Cohesion: 0.15
Nodes (16): _bounds(), ContextReader, words_in(), _hull(), _inside(), _lines(), _name(), _name_pixels() (+8 more)

### Community 81 - "coinpoker-help — Laya Vision as the sole live perception backend"
Cohesion: 0.18
Nodes (10): 0. Decisions (user, 2026-10-09T15:4xZ), 1. Facts this plan relies on (verified in planning), 4. Geometry (`laya/geometry.rs`, `regions.json`), 6. Config and CLI (`bin/config.rs`, `bin/live.rs`), 7. Tests (focused; replace the removed Gemma tests), 8. Stop conditions, 9. Known gaps (record in addendum 9 / final report), coinpoker-help — Laya Vision as the sole live perception backend (+2 more)

### Community 82 - "FeatureCacheTests"
Cohesion: 0.13
Nodes (8): CapturedGPUProofTests, run(), encode(), encoded(), CapturedPixelReplayTests, FeatureCacheTests, RGB, uncached_predict_many()

### Community 83 - "SourcePolicy"
Cohesion: 0.19
Nodes (8): SourcePolicy, AutomaticBounded, AutomaticSustained, Manual, valid_approval(), AutomaticSchedule, next_automatic_pass(), poll_delay()

### Community 84 - ".now_ms"
Cohesion: 0.25
Nodes (6): Source, sustained_approval(), sustained_capture_passes_600_seconds_and_1200_acquisitions_with_frozen_evidence(), sustained_ended_evidence_still_rejects_source_capture_and_clock_failures(), sustained_unexpected_recorder_io_is_terminal_not_an_evidence_end(), Time

### Community 85 - "Execution Steps"
Cohesion: 0.13
Nodes (14): 1. Revalidate ownership and record the starting state, 2. Shut down the legacy automatic runtime, 3. Build and check the non-capturing entry point, 4. Start the updated dashboard-only service, 5. Verify the idle state end to end, 6. Prepare source identification, without capture, 7. Deliver the bounded next-session handoff and stop, Approval Plan: Controlled Dashboard-Only Runtime Refresh (+6 more)

### Community 86 - "Bounded Diagnostics and Sustained Observation"
Cohesion: 0.11
Nodes (18): Actual transport, Authorized Second Attempt, Bounded Diagnostics and Sustained Observation, Capability matrix, Confirm and start, Current Work Authorization, Explicit Automatic Startup (Observer or Seated), First Runtime Finding and Correction (+10 more)

### Community 87 - "extend_partial"
Cohesion: 0.27
Nodes (3): extend_partial(), ScenePassConfig, ScenePassRegistry

### Community 88 - ".setUp"
Cohesion: 0.08
Nodes (4): build(), __getitem__(), EnginePrefixTests, prefix()

### Community 89 - "7. Phase gates"
Cohesion: 0.14
Nodes (14): 7. Phase gates, Approved stage2 implementation, not live acceptance (2026-10-10), Authorized Automatic Observer Trials (2026-10-12), Checkpoint B implementation and current blocker (2026-10-10), Current: iteration-1 Gate F FAIL (2026-10-09), Desktop companion / bounded manual diagnostic (2026-10-11), Historical A-D proposals and B-lite results, Historical dashboard/history plan (2026-10-10), baseline still FAIL (+6 more)

### Community 90 - "WindowInfo"
Cohesion: 0.07
Nodes (28): CapturedPopup, Frame, frame_requires_exact_packed_rgba_length(), FrameError, DimensionsOverflow, InvalidBufferLength, InvalidVisibility, FrameReadability (+20 more)

### Community 91 - "laya_actions.py"
Cohesion: 0.09
Nodes (14): ActionReader, ActionTimeline, _badge_masks(), _capture_key(), CropTemplates, _digit_mask(), _fingerprint(), _normal_mask() (+6 more)

### Community 92 - "scene.rs"
Cohesion: 0.22
Nodes (10): clear_field(), field_known(), reject(), reject_contradictions(), retain_agreement(), SCENE_FIELDS, SCENE_NOTE, SCENE_PROVENANCE (+2 more)

### Community 94 - ".new"
Cohesion: 0.14
Nodes (19): Apartment, capture_visible_frame(), copy_desktop_rect(), discover(), enum_window(), OwnedHandle, process_created_at_100ns(), process_exe_name() (+11 more)

### Community 95 - "IntegrationTests"
Cohesion: 0.15
Nodes (3): IntegrationTests, service(), worker()

### Community 98 - "Next Conversation: Deliver Verified Live Table Data"
Cohesion: 0.17
Nodes (12): Changes Already Implemented, Controlled Live Loop, Definition Of Done, Evidence And Entry Points, Historical Incoming Baseline, Integrity Boundaries, Latest Operator Instructions And Verified State, Local Integration Update (2026-10-13) (+4 more)

### Community 99 - "laya_showdown.py"
Cohesion: 0.10
Nodes (20): box_px(), _components(), content_rect(), segment_glyphs(), _text_mask(), _text_score(), _bounds(), _current_evidence() (+12 more)

### Community 100 - "super"
Cohesion: 0.12
Nodes (10): app_starts_empty_and_accepts_decisions(), DecisionApp, run(), equity_and_ev_formatting(), no_pot_odds_when_facing_no_bet(), pot_odds_ratio_label_formats_as_ratio(), render_panel(), summary_annotates_raise_amounts() (+2 more)

### Community 102 - "saved_capture_schedule.rs"
Cohesion: 0.21
Nodes (4): runtime_submissions(), SavedFrame, stopped_saved_capture_stability_replay(), stopped_saved_readout_scope_replay()

### Community 103 - "DiscoveryState"
Cohesion: 0.18
Nodes (11): DiscoveryState, AmbiguousMultipleTables, CandidateTable, CapturingTable, ConfigurationRequired, LobbyDetected, PermissionRequired, Recovering (+3 more)

### Community 106 - "Laya Vision Prototype — Phase A Design (Question Set + Calibration Corpus)"
Cohesion: 0.20
Nodes (10): 1. Historical motivation, 2. Initial model facts (2026-10-09, licensing corrected), 3. Historical Phase A architecture, 4. Historical first baseline findings (recorded 2026-10-09), 5. Historical Phase A corpus and annotation protocol, 6.1 Range and odds provenance (screenshots, not the PDF), 6. The reference sheet drives the Laya logic (poker-info-sheet.pdf), 8. Current risks and open assumptions (+2 more)

### Community 107 - "VisualWorker"
Cohesion: 0.18
Nodes (5): _capture(), ContextWorker, _current_region(), _region_checks(), VisualWorker

### Community 108 - "Engine"
Cohesion: 0.16
Nodes (3): initialize(), Engine, initialize()

### Community 112 - "WagerTests"
Cohesion: 0.20
Nodes (3): RegistryPinTests, SceneTests, WagerTests

### Community 113 - "RevealedCardTests"
Cohesion: 0.18
Nodes (7): capture(), current_roster(), face(), frame(), library(), pair(), RevealedCardTests

### Community 114 - "laya_numeric.py"
Cohesion: 0.15
Nodes (13): _annotated_glyphs(), _glyph(), _hash(), _lines(), _mask(), _numeric_score(), NumericReader, _original() (+5 more)

### Community 115 - "BoardTemplateTests"
Cohesion: 0.09
Nodes (3): BoardTemplateTests, source_suit_updates(), synthetic_card()

### Community 116 - "PlayerState"
Cohesion: 0.22
Nodes (5): PlayerState, complete_players(), CompleteGameState, required_nullable(), TablePlayer

### Community 117 - "coinpoker-help"
Cohesion: 0.22
Nodes (9): Architecture, CLI, coinpoker-help, Current model and browser, Known limits, Privacy and model provenance, Start here, Structured replay (+1 more)

### Community 118 - "Suit"
Cohesion: 0.29
Nodes (6): RsSuit, Suit, Clubs, Diamonds, Hearts, Spades

### Community 120 - "DecisionComplexity"
Cohesion: 0.25
Nodes (8): DecisionComplexity, PostflopCall, PostflopRaise, PostflopSimple, PreflopCall, PreflopFold, PreflopRaise, RiverAllin

### Community 121 - "native_decision"
Cohesion: 0.25
Nodes (3): native_decision(), native_observation(), NativeProjectionTests

### Community 122 - "NumericWorker"
Cohesion: 0.17
Nodes (4): NumericWorker, NumericWorkerTests, finish(), read()

### Community 123 - "BoardTemplateRecognizer"
Cohesion: 0.18
Nodes (4): BoardTemplateRecognizer, _json(), main(), _shape_fields()

### Community 124 - "Windows installation and calibration"
Cohesion: 0.29
Nodes (7): 1. Prerequisites, 2. Reuse and verify the existing Laya checkpoint, 3. Open the local dashboard, 4. Historical passive-profile diagnostics, 5. Evaluate and record acceptance, Historical candidate archive and current omissions, Windows installation and calibration

### Community 125 - "time"
Cohesion: 0.27
Nodes (5): blocked_record(), main(), powershell_syntax_command(), run_command(), validate_workflow_workflows()

### Community 126 - "TemporalConfigError"
Cohesion: 0.33
Nodes (6): TemporalConfigError, InvalidMaximum, InvalidMinimum, InvertedBounds, NonFiniteSigma, NonPositiveSigma

### Community 127 - "Local visual evaluation, manifest format 2"
Cohesion: 0.29
Nodes (7): Acceptance thresholds, Fixture schema, Local visual evaluation, manifest format 2, Required held-out local corpus, Retention, Run, pot()

### Community 128 - "coinpoker"
Cohesion: 0.33
Nodes (6): coinpoker, core-engine, ghost-layer, ingest, opponent-model, ui

### Community 132 - "Windows VLM compatibility record"
Cohesion: 0.40
Nodes (5): Active Laya-only candidate, Historical Gemma candidate and expected hashes, Historical runtime decision, Historical transport and acceptance checks, Windows VLM compatibility record

### Community 133 - "Windows acceptance report, format 1"
Cohesion: 0.40
Nodes (5): Current Laya and follow-on status, Historical candidate gates, Historical candidate smoke order, Historical environment and provenance, Windows acceptance report, format 1

### Community 135 - "Contributing"
Cohesion: 0.50
Nodes (4): Active development scope, Change rules, Contributing, Toolchain and checks

### Community 136 - "laya_dashboard.py"
Cohesion: 0.21
Nodes (10): diagnostic_vocabulary(), drain_feed(), experimental_view(), finite(), observation_metrics(), private_perception(), references(), _reject_constant() (+2 more)

### Community 137 - "Windows validation evidence"
Cohesion: 0.50
Nodes (4): Current baseline and pending follow-on validation, Historical automated run (2026-09-23), Historical implementation boundaries (2026-09-23), Windows validation evidence

### Community 138 - "manifest.json"
Cohesion: 0.50
Nodes (3): cases, format, source

### Community 141 - "Security policy"
Cohesion: 0.50
Nodes (4): Reporting, Screenshot and output boundaries, Security policy, Supported versions

### Community 143 - "Model and runtime provenance"
Cohesion: 0.67
Nodes (3): Active Laya Vision provenance, Historical Gemma and llama.cpp provenance, Model and runtime provenance

### Community 153 - "Part 1: Recognition, Evidence, And Table-First UI"
Cohesion: 0.14
Nodes (13): 1. Extend The Collector Before The Window, 1. Revalidate Runtime And Collect Genuine Inputs, 2. Define Independent, Source-Bound Contracts, 2. Run One Continuous Observer Segment, 3. Make Client Popups A Regional Occlusion Case, 3. Required Report, 4. Finish And Handoff, 5. Import Atomic Client-Displayed Profile Stats (+5 more)

### Community 155 - "prompt.rs"
Cohesion: 0.36
Nodes (6): build_analysis_prompt(), example(), examples_specify_the_full_strict_screen_envelope(), prompts_classify_first_without_assuming_a_table(), SYSTEM_PROMPT, table_example_preserves_strict_poker_requirements()

### Community 157 - "EngineBatchTests"
Cohesion: 0.16
Nodes (3): __init__(), EngineBatchTests, invalid()

### Community 160 - "Project Instructions"
Cohesion: 0.50
Nodes (3): Engineering Scope, Policy Research Requires Explicit Approval, Project Instructions

### Community 161 - "handle_predict"
Cohesion: 0.13
Nodes (12): answer_diagnostics(), experimental_descriptor(), handle_predict(), handle_predict_batch(), png_size(), readout_core_template(), RequestError, authorized() (+4 more)

### Community 164 - ".ingest"
Cohesion: 0.22
Nodes (4): DashboardState, integer(), native_analysis_inputs(), unavailable_reason()

### Community 166 - "field_statuses"
Cohesion: 0.25
Nodes (7): Companion diagnostic extension (2026-10-11), Explicit Automatic Observation Policy, Manual Inference Transport (2026-10-12), Offline draft labels are not events (2026-10-10), Per-field observing contract (stage2 implemented), Sustained Observation Receipt Variant, field_statuses()

### Community 167 - "2. Steps and gates"
Cohesion: 0.20
Nodes (10): 2. Steps and gates, Step 0 — verify, commit and push addendum 8 (D4), Step 1 — runtime environment, pins, licence, Step 2 — question set 0.3.0 and regions (data only, no Rust), Step 3 — Phase B-lite (in-process laya, before any Rust wiring), Step 4 — `scripts/laya-server.py` (section 5) and Python tests, Step 5 — Rust: LayaBackend and Gemma removal (sections 3, 4, 6), Step 7 — validation (+2 more)

### Community 168 - "geometry.rs"
Cohesion: 0.15
Nodes (11): box_px(), content_rect(), crop(), crops_have_the_box_size_and_tiny_crops_are_refused(), Geometry, readout_tracking_crops_preserve_every_original_byte_and_ignore_only_other_regions(), readout_tracking_frames(), region_px() (+3 more)

### Community 171 - "random_pass"
Cohesion: 0.56
Nodes (3): random_pass(), seeded_random_answer_maps_always_produce_parseable_envelopes(), XorShift

### Community 172 - ".test_sustained_supervisor_runs_45_minutes_and_only_caps_evidence_and_logs"
Cohesion: 0.12
Nodes (5): progress(), publish(), sleep(), start(), save()

### Community 176 - "make_handler"
Cohesion: 0.71
Nodes (7): make_handler(), _discard_body(), do_GET(), do_POST(), _local_request(), _send(), _send_bytes()

### Community 177 - "3. Assembly (Rust `laya/assembly.rs`)"
Cohesion: 0.33
Nodes (6): 3.1 Confidence, 3.2 R5 (amended) — amounts, 3.3 New and clarified rules (0.3.0), 3.4 Strictness, 3.5 Pass order, 3. Assembly (Rust `laya/assembly.rs`)

### Community 179 - "cmd_serve"
Cohesion: 0.18
Nodes (6): 5. Laya server (`scripts/laya-server.py`), BoundedHTTPServer, cmd_serve(), log_fn(), serve(), log_message()

### Community 181 - "main.rs"
Cohesion: 0.17
Nodes (5): convert_cards(), main(), report_warning(), run_stdin_pipeline(), Io

### Community 183 - ".batch"
Cohesion: 0.33
Nodes (3): b64(), body(), ReadoutBatchTests

### Community 184 - "outs.rs"
Cohesion: 0.19
Nodes (5): exact_next_card(), exact_turn_and_river(), MEMORIZED_DRAWS, MemorizedDraw, printed_percentages_track_the_exact_values()

### Community 189 - "PartialObservationView"
Cohesion: 0.20
Nodes (7): consensus_retains_literal_amounts_and_independent_cards_not_unverified_fields(), PartialObservationView, ObservationRole, Observing, SeatedWaiting, Uncertain, YourTurn

### Community 191 - "CaptureSource"
Cohesion: 0.20
Nodes (3): ManualSource<'_, S, C>, CaptureSource, CaptureTiming

### Community 192 - "partial_view"
Cohesion: 0.20
Nodes (7): Implementation Map, Planning Findings, Purpose And Session Boundary, Quiet Table Monitor And Observer Break Test, amount_text(), cards(), partial_view()

### Community 193 - "Ticket"
Cohesion: 0.42
Nodes (4): AdmittedHistory, leased_record(), RuntimeConfig, Ticket

### Community 194 - "Position"
Cohesion: 0.29
Nodes (7): Position, Bb, Btn, Co, Hj, Sb, Utg

### Community 198 - "RangeError"
Cohesion: 0.40
Nodes (5): RangeError, HighCardNotHigher, InvalidPair, InvalidRank, InvalidToken

## Knowledge Gaps
- **726 isolated node(s):** `USAGE`, `Capture`, `Stdin`, `ListWindows`, `Doctor` (+721 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1402 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **60 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CompanionUiTests` connect `CompanionUiTests` to `.context_session`, `.full_analysis`, `.experimental_session`, `.first_live_claim`, `ManualFeedTests`, `json`, `ExperimentalCandidateTests`, `.sustained_session`, `.run_ui`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `CompanionUiTests` (e.g. with `ExperimentalCandidateTests` and `ManualFeedTests`) actually correct?**
  _`CompanionUiTests` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `USAGE`, `Capture`, `Stdin` to the rest of the system?**
  _726 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `CompanionUiTests` be split into smaller, more focused modules?**
  _Cohesion score 0.10793650793650794 - nodes in this community are weakly interconnected._
- **Why does `status()` connect `app.js` to `coinpoker-help — Readiness Assessment and Validation Plan`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Should `recorder.rs` be split into smaller, more focused modules?**
  _Cohesion score 0.06732673267326733 - nodes in this community are weakly interconnected._
- **Why does `utc()` connect `laya_capture.py` to `app.js`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._