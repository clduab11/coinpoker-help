# Graph Report - coinpoker-help  (2026-10-13)

## Corpus Check
- 115 files · ~272,657 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 4, .toml 2, .css 1)

## Summary
- 3810 nodes · 9230 edges · 158 communities (130 shown, 28 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 257 edges (avg confidence: 0.86)
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
- laya_dashboard.py
- VlmError
- super
- VerifiedField
- windows.rs
- observing.rs
- live.rs
- WindowInfo
- assembly.rs
- CaptureTests
- change_detect.rs
- laya.rs
- ManualFeedTests
- AttachTests
- decision.rs
- discovery.rs
- .tick
- coinpoker-help — Readiness Assessment and Validation Plan
- test_laya_server.py
- InferenceFailure
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
- doctor.py
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
- ForcedAction
- partial_observation.rs
- RunError
- Badge
- re
- Practice-Sandbox Dashboard, Observed History, and Seated Data
- ExperimentalCandidateTests
- betting.rs
- manual_inference.rs
- ScreenObservation
- betting_entropy.rs
- Product facts the integration depends on (see the integration plan for details)
- FieldName
- WindowsCapturer
- status
- body
- profile.rs
- temporal.rs
- vlm.rs
- InferenceConsentTests
- TableContentWitness
- headless.rs
- inference_loop
- geometry.rs
- DoctorTests
- Rank
- Position6max
- WagerPassRegistry
- acceptSnapshot
- ExperimentalTests
- manual_capture.rs
- laya/partial.rs
- 2. Steps and gates
- main.rs
- SourcePolicy
- .now_ms
- Execution Steps
- ManualSessionFeed
- extend_partial
- .setUp
- 7. Phase gates
- CaptureError
- WindowKind
- scene.rs
- DecisionView
- app.js
- IntegrationTests
- AutomaticStartupTests
- Next Conversation: Deliver Verified Live Table Data
- laya_prep.py
- DecisionApp
- .new
- saved_capture_schedule.rs
- DiscoveryState
- AcceptanceTests
- Value
- Laya Vision Prototype — Phase A Design (Question Set + Calibration Corpus)
- LiveEvent
- Engine
- HttpTests
- BatchTests
- HttpTests
- WagerTests
- widgets.rs
- pipeline_smoke.rs
- random_pass
- PlayerState
- coinpoker-help
- Suit
- EquityError
- DecisionComplexity
- GamePhase
- text
- renderObservation
- Windows installation and calibration
- FakeEngine
- TemporalConfigError
- Local visual evaluation, manifest format 2
- coinpoker
- renderSource
- PartialObservationView
- fake_server
- Windows VLM compatibility record
- Windows acceptance report, format 1
- lobby-observation.ps1
- Contributing
- Windows validation evidence
- manifest.json
- FakePrep
- PolicyTests
- Security policy
- Time
- Model and runtime provenance
- emit_with_history
- prompt.rs
- Position
- EngineBatchTests
- ScreenBitmap
- ActionBasis

## God Nodes (most connected - your core abstractions)
1. `CompanionUiTests` - 96 edges
2. `CaptureError` - 72 edges
3. `VerifiedField` - 71 edges
4. `VlmError` - 70 edges
5. `PartialTests` - 64 edges
6. `Time` - 54 edges
7. `Value` - 53 edges
8. `ManualFeedTests` - 52 edges
9. `Id` - 49 edges
10. `AttachTests` - 45 edges

## Surprising Connections (you probably didn't know these)
- `Continuation: Actual Phase Timeline` --references--> `status()`  [INFERRED]
  .kilo/plans/1791496776779-repo-readiness-and-next-steps.md → scripts/dashboard/app.js
- `2. Decisions (confirmed with the user 2026-10-09T21:00Z)` --references--> `status()`  [INFERRED]
  .kilo/plans/1791578389113-laya-gate-f-live-run-docs.md → scripts/dashboard/app.js
- `T3. Pins, server, latency bench` --references--> `status()`  [INFERRED]
  .kilo/plans/1791578389113-laya-gate-f-live-run-docs.md → scripts/dashboard/app.js
- `T5. Gate F decision` --references--> `status()`  [INFERRED]
  .kilo/plans/1791578389113-laya-gate-f-live-run-docs.md → scripts/dashboard/app.js
- `T8. Step 9 — docs and records` --references--> `utc()`  [INFERRED]
  .kilo/plans/1791578389113-laya-gate-f-live-run-docs.md → scripts/laya_capture.py

## Import Cycles
- 2-file cycle: `crates/ingest/src/capture.rs -> crates/ingest/src/discovery.rs -> crates/ingest/src/capture.rs`

## Communities (158 total, 28 thin omitted)

### Community 1 - "recorder.rs"
Cohesion: 0.06
Nodes (52): budget_reason(), recording_end_reason(), BoundedHashWriter, BoundedHashWriter<W>, CaptureStamp, create_file(), directory_guard(), encode() (+44 more)

### Community 2 - "live_runtime.rs"
Cohesion: 0.11
Nodes (73): activate(), activate_observation(), admitted_unseated_observation_has_a_source_lease_and_no_placeholder_controls(), ambiguous_windows_and_permission_loss_invalidate_without_duplicate_clears(), automatic_field_invalidation_targets_old_publication_not_new_current_completion(), automatic_independent_stability_dispatches_unchanged_pot_despite_staggered_stack_motion(), automatic_observation_never_promotes_even_a_valid_full_state_or_recommendation(), captures_continue_and_latest_queue_is_bounded_while_inference_is_slow() (+65 more)

### Community 3 - "PartialTests"
Cohesion: 0.07
Nodes (4): Clock, capability(), PartialTests, StaticUiTests

### Community 4 - "laya_dashboard.py"
Cohesion: 0.06
Nodes (26): Companion diagnostic extension (2026-10-11), Explicit Automatic Observation Policy, Manual Inference Transport (2026-10-12), Offline draft labels are not events (2026-10-10), Per-field observing contract (stage2 implemented), PracticeAttachment, amount_text(), AutoAttachFeed (+18 more)

### Community 5 - "VlmError"
Cohesion: 0.19
Nodes (13): LayaClient, PassAnswers, probability(), schema(), Pass, read_bounded(), remaining_budget(), VlmError (+5 more)

### Community 6 - "super"
Cohesion: 0.06
Nodes (32): exact_next_card(), exact_turn_and_river(), MEMORIZED_DRAWS, MemorizedDraw, printed_percentages_track_the_exact_values(), Archetype, Lag, LoosePassive (+24 more)

### Community 7 - "VerifiedField"
Cohesion: 0.03
Nodes (65): VerifiedField, Acting1, Acting2, Acting3, Acting4, Acting5, Acting6, Badge1 (+57 more)

### Community 8 - "windows.rs"
Cohesion: 0.06
Nodes (19): capture_visible_frame(), check_os(), discover(), enum_window(), FRAME_POOL_BUFFERS, FRAME_WAIT_TIMEOUT, newer_fresh_timestamp(), OwnedHandle (+11 more)

### Community 9 - "observing.rs"
Cohesion: 0.20
Nodes (33): Id, advance(), badges_persist_flicker_and_renew_with_existing_ledger_provenance(), call_cost_uses_live_credit_not_visible_wager_ante_or_total_commitment(), current_pot_odds_requires_matching_eligible_sidepot_and_convention(), default_missing_fields_are_not_zero_and_unvalidated_capture_is_separate(), expired_identity_interval_and_duplicate_id_reject_statistics_transfer(), FIELD_LEASES (+25 more)

### Community 10 - "live.rs"
Cohesion: 0.13
Nodes (23): assert_worker_category(), configuration_event(), configuration_event_reports_laya_perception(), current_laya_unseated_admission_propagates_without_hero_placeholders(), current_observation_records_are_allowlisted_leased_and_name_private(), decision_publication_uses_the_same_total_deadline(), delayed_health_publication_cannot_claim_a_fresh_capture(), event_record() (+15 more)

### Community 11 - "WindowInfo"
Cohesion: 0.11
Nodes (11): capture_loop(), emit_status(), FakeSource, same_source(), SourceState, CaptureSource, WindowInfo, DiscoverySnapshot (+3 more)

### Community 12 - "assembly.rs"
Cohesion: 0.09
Nodes (43): acceptance_floor_board_one_checks_every_card_and_no_card_slot(), acceptance_floor_keeps_noul_fallbacks_and_truncation_at_exact_boundaries(), acceptance_floor_p0_boundary_and_low_overrides_enforce_both_polarities(), assemble(), assemble_script(), assert_table_null(), board(), choice() (+35 more)

### Community 13 - "CaptureTests"
Cohesion: 0.05
Nodes (10): Sustained Observation Receipt Variant, CaptureTests, progress(), publish(), sleep(), start(), read(), save() (+2 more)

### Community 14 - "change_detect.rs"
Cohesion: 0.11
Nodes (34): animated_tile_does_not_block_stability(), animated_window_zero_disables_suppression(), animation_cannot_become_stable_until_it_stops(), animation_suppression_bounds_are_validated(), change_outside_a_suppressed_tile_still_triggers(), ChangeDetector, ChangeDetectorConfig, ChangeResult (+26 more)

### Community 15 - "laya.rs"
Cohesion: 0.10
Nodes (41): analyze_runs_crops_through_the_server_and_assembles_an_envelope(), automatic_numeric_pair_refreshes_pot_and_selected_stack_without_a_slow_large_batch(), automatic_partial_passes_do_not_run_fields_after_unqualified_core(), automatic_partial_passes_keep_core_witness_floors_and_independent_unknowns(), automatic_partial_passes_never_reuse_answers_from_previous_source_jobs(), automatic_partial_passes_reject_extensions_before_encoding_or_io(), automatic_partial_passes_reject_invalid_seats_and_elapsed_leases_without_io(), backend() (+33 more)

### Community 17 - "AttachTests"
Cohesion: 0.12
Nodes (6): AttachTests, encode(), listing(), profile(), records(), window()

### Community 18 - "decision.rs"
Cohesion: 0.09
Nodes (39): Action, Call, Check, Fold, Raise, calls_when_equity_beats_break_even(), checks_when_no_bet_and_weak_equity(), decide() (+31 more)

### Community 19 - "discovery.rs"
Cohesion: 0.10
Nodes (34): lobby_size(), ambiguity_invalidates_previously_selected_filter(), app(), ApplicationInfo, calibrated_table_outranks_unknowns_and_lobbies_in_any_order(), CaptureManager, CaptureManager<S>, config() (+26 more)

### Community 20 - ".tick"
Cohesion: 0.19
Nodes (3): Clock, LiveRuntime<S, W, T>, MonotonicClock

### Community 21 - "coinpoker-help — Readiness Assessment and Validation Plan"
Cohesion: 0.04
Nodes (46): 10. Out of scope, 1. Executive summary, 2. Phase 0 — COMPLETE (2026-10-08 UTC), 3. Phase 1 readiness — prerequisites verified, flagged items, 4. Phase 1 — Prerequisites & calibration (gates 1-3) [READY TO EXECUTE], 5. Phase 2 — Capture fidelity & lifecycle (gates 4-17) [BLOCKED on Phase 1], 6. Phase 3 — Corpus & candidate validation (gates 18-20) [BLOCKED on Phase 2], 7. Phase 4 — Remediation & closeout (+38 more)

### Community 22 - "test_laya_server.py"
Cohesion: 0.09
Nodes (7): main(), PowerShellSyntaxTests, blocked_record(), main(), powershell_syntax_command(), run_command(), validate_workflow_workflows()

### Community 23 - "InferenceFailure"
Cohesion: 0.14
Nodes (12): Completion, expired_worker_job_never_runs_analysis(), InferenceFailure, InferenceJob, InferencePort, ThreadWorker, ThreadWorker<T>, Ticket (+4 more)

### Community 24 - "observer.rs"
Cohesion: 0.15
Nodes (45): ActionBadge, actions(), Badge, Action, Clear, capture_and_action_sequence_gaps_prevent_invented_ordinals(), conflicting_capture_and_reversed_time_do_not_admit_actions(), contradictory_dealt_in_status_cannot_finalize_other_players_as_false() (+37 more)

### Community 25 - "laya_attach.py"
Cohesion: 0.08
Nodes (23): AttachError, AttachmentRule, AttachResult, _exe(), _integer(), _json(), constant(), pairs() (+15 more)

### Community 26 - "screen.rs"
Cohesion: 0.15
Nodes (42): a_hand_reset_requires_an_accepted_marker_not_a_single_empty_frame(), accepted_showdown_allows_a_direct_dealt_preflop(), agreeing_community_cards_do_not_require_a_matching_pot(), all_non_table_kinds_need_no_poker_payload_and_ignore_irrelevant_state(), assert_safe_category(), calibrated_table_titles_still_require_two_full_matching_observations(), CompletePlayerState, confirm() (+34 more)

### Community 27 - "SupervisorTests"
Cohesion: 0.06
Nodes (11): Goal and Decisions, Rollout and Out of Scope, Sustained Monitor Window Intake, Validation and Acceptance, Verified Diagnosis, CaptureTests, FakeFeed, FakeSelection (+3 more)

### Community 28 - "laya_capture.py"
Cohesion: 0.10
Nodes (25): Implementation Tasks, approve_inference(), AutomaticStart, default_snapshot(), evidence_snapshot(), experimental_session_approved(), fail_session(), inference_service() (+17 more)

### Community 30 - "table_rules.rs"
Cohesion: 0.06
Nodes (29): anchored_seats_hold_at_every_supported_size(), assign_positions(), MAX_SEATS, names(), names_clockwise_from_button(), seat_position(), SeatingError, ButtonNotOccupied (+21 more)

### Community 31 - "parser.rs"
Cohesion: 0.08
Nodes (22): enforces_available_action_consistency(), extract_json_object(), fills_defaults_for_optional_fields(), output(), parse_vlm_output(), ParseError, ActionRequired, BoardCount (+14 more)

### Community 32 - "runtime.rs"
Cohesion: 0.11
Nodes (18): CAPTURE_HEALTH_INTERVAL_MS, ControlView, DECISION_DEADLINE_CODE, DrawView, Freshness, LiveRuntime, MAX_WORKER_FAILURES, observation_is_current() (+10 more)

### Community 33 - "client.rs"
Cohesion: 0.15
Nodes (31): acceptance_floor_and_probabilities_are_retained_without_f32_rounding(), acceptance_floor_requires_a_finite_number_in_the_unit_interval(), batch_404_and_busy_do_not_retry_or_expose_error_bodies(), batch_keeps_per_pass_validation_and_independent_malformed_result_unknown(), batch_rejects_untrained_duplicate_or_expired_work_without_transport(), client(), each_pass_receives_only_the_remaining_total_or_request_budget(), errors_never_contain_request_or_response_payloads() (+23 more)

### Community 34 - "experimental.rs"
Cohesion: 0.14
Nodes (21): all_measured_draft_crops_are_explicit_unvalidated_and_scaled_without_new_regions(), append_diagnostics(), crop_digest(), CropWitness, descriptor_cannot_claim_approval_or_substitute_a_crop(), diagnostic_expiry_never_admits_experimental_fields_or_renews_source_provenance(), DONOR_PASS, empty_segmentation_is_unknown_never_zero_and_no_experiment_has_an_acceptance_floor() (+13 more)

### Community 35 - "doctor.py"
Cohesion: 0.09
Nodes (23): Step 6 — scripts (no new .ps1), _check_files(), check_model_files(), check_runtime(), collect(), outcome(), record(), color_png() (+15 more)

### Community 36 - "cli.rs"
Cohesion: 0.12
Nodes (33): a_valid_state_recovers_after_invalid_input_without_duplicate_clears(), ACTION_STATE, assert_evaluation_category(), assert_private_output(), assert_stdin_category(), evaluates_synthetic_image_contracts_without_a_server(), help_prints_usage_and_succeeds(), invalid_stdin_state_invalidates_an_active_decision() (+25 more)

### Community 37 - "state_machine.rs"
Cohesion: 0.14
Nodes (34): Card, GameState, action_turning_on_emits_action_required_once(), available_action_change_emits_state_changed_while_action_remains_required(), first_observation_emits_state_changed(), first_observation_with_action_emits_action_required(), hero_card_change_emits_state_changed_while_action_remains_required(), initial_showdown_is_emitted_once_and_later_changes_are_reported() (+26 more)

### Community 38 - "laya-server.py"
Cohesion: 0.05
Nodes (40): 5. Laya server (`scripts/laya-server.py`), answer_diagnostics(), BoundedErrorLog, BoundedHTTPServer, cmd_fetch(), cmd_serve(), log_fn(), cmd_verify() (+32 more)

### Community 39 - "DiagnosticReason"
Cohesion: 0.06
Nodes (35): DiagnosticReason, Accepted, AwaitingConsensus, BelowFloor, BoardCountInvalid, BoardNoncontiguous, BoardPresenceUnknown, CropTooSmall (+27 more)

### Community 40 - "ranges.rs"
Cohesion: 0.11
Nodes (24): ALL_RANKS, button_and_small_blind_add_tier_three(), classes(), display_round_trips_notation(), expand_dash_range(), expand_notation(), expands_dash_ranges_inclusively(), expands_offsuit_plus() (+16 more)

### Community 41 - "Observer"
Cohesion: 0.10
Nodes (20): ActionCounts, ActionRecord, Capture, Coverage, default_and_custom_limits_bound_event_view_and_all_retained_keys(), Evidence<T>, has_gap(), LedgerEvent (+12 more)

### Community 42 - "questions.rs"
Cohesion: 0.08
Nodes (23): acceptance_floor_is_required_and_validated_for_every_trained_pass(), calibrated(), question_set_version(), Calibration, Calibrated, Trained, Uncalibrated, UntrainedProvisional (+15 more)

### Community 43 - "GapReason"
Cohesion: 0.06
Nodes (33): ChipMovement, Ambiguous, Payout, PotCollection, Refund, TopUp, GapReason, ActionSequence (+25 more)

### Community 44 - "config.rs"
Cohesion: 0.10
Nodes (24): cli_overrides_environment_and_defaults(), FLAGS, hwnd_accepts_decimal_and_hexadecimal(), laya_defaults_apply_without_configuration(), laya_threshold_is_bounded_and_overridable_by_cli(), lobby_size_is_a_positive_pair(), Mode, Capture (+16 more)

### Community 45 - "seat_scene.rs"
Cohesion: 0.19
Nodes (24): assembled(), backend_default_never_requests_scene_and_explicit_fixture_encodes_distinct_seat_rois(), base_answers(), candidate(), choice(), config(), exact_whole_scene_witness_rejects_only_changed_seat_not_pot_stacks_or_wagers(), fake_response() (+16 more)

### Community 46 - "src/partial.rs"
Cohesion: 0.09
Nodes (31): BOARD_FIELDS, capabilities(), Capability, DiagnosticAdmission, Candidate, DecisionBudgetExpired, ObservationExpired, ObsoleteObservation (+23 more)

### Community 47 - "serde"
Cohesion: 0.08
Nodes (23): HandStart, BeforeActions, Partial, ButtonPolicy, Dead, Moving, map(), missing_button_blinds_policy_roster_and_empty_dead_button_stay_unknown() (+15 more)

### Community 48 - "equity.rs"
Cohesion: 0.16
Nodes (20): aces_dominate_kings_preflop(), board_royal_flush_splits_unknown_multiway_pot(), Card, EquityConfig, EquityEstimator, estimator(), full_deck(), hand() (+12 more)

### Community 49 - "ForcedAction"
Cohesion: 0.33
Nodes (6): ForcedAction, Ante, BigBlind, SmallBlind, Straddle, Voluntary

### Community 50 - "partial_observation.rs"
Cohesion: 0.19
Nodes (24): a_board_transport_failure_still_attempts_amounts_but_deadline_aborts_all(), a_later_wager_deadline_keeps_prior_safe_field_traces_but_admits_nothing_and_stops_requests(), amount(), assemble(), assemble_wagers(), board_source_region_change_clears_only_changed_slot_and_dependent_count_phase(), choice(), confident_unreadable_card_is_occluded_not_an_accepted_identity_or_presence() (+16 more)

### Community 51 - "RunError"
Cohesion: 0.11
Nodes (19): Case, fail(), frame(), kind(), Manifest, metadata(), percentile(), Ratio (+11 more)

### Community 52 - "Badge"
Cohesion: 0.09
Nodes (21): Badge, AllIn, Bet, BigBlind, Call, Check, Fold, None (+13 more)

### Community 54 - "Practice-Sandbox Dashboard, Observed History, and Seated Data"
Cohesion: 0.07
Nodes (27): 10. P6: Validated Seated Branch and Sandbox Guidance, 11. Validation Matrix and Completion Records, 1. Decisions and Scope, 2. Verified Starting Point, 3. Meaning of the Metrics and Timing, 4. P0: Preserve the Baseline and Decruft Active Instructions, 5. P1: Read-Only Browser Dashboard on the Same Port, 6. P2: Hero-Independent Watching History (+19 more)

### Community 55 - "ExperimentalCandidateTests"
Cohesion: 0.15
Nodes (3): candidate_record(), ExperimentalCandidateTests, ExperimentalFeedTests

### Community 56 - "betting.rs"
Cohesion: 0.10
Nodes (24): action(), additional_call_cost(), BettingRound, CallContext, CallCost, cumulative_short_reopens_only_seats_facing_a_full_increment_since_last_action(), folds_allin_calls_illegal_reopens_unknown_actions_and_street_reset(), full_raises_short_and_cumulative_allins_preserve_increment_and_individual_rights() (+16 more)

### Community 57 - "manual_inference.rs"
Cohesion: 0.11
Nodes (23): ACTIVITY_REGIONS, approval_json(), automatic_activity_requires_persistent_qualified_pixels_not_role_or_model_jitter(), automatic_idle_lobby_transient_ambiguous_jitter_and_resize_keep_finite_run_budgets(), automatic_partial_lanes_recover_after_core_only_admission_and_interruption(), AutomaticSchedule, cosmetic_and_one_stack_churn_do_not_block_independent_current_amounts(), exercise() (+15 more)

### Community 58 - "ScreenObservation"
Cohesion: 0.08
Nodes (29): TableIdentity, GateOutcome, has_table_evidence(), MetadataEvidence, Candidate, LobbyTitle, Other, TableTitle (+21 more)

### Community 59 - "betting_entropy.rs"
Cohesion: 0.16
Nodes (17): BettingEntropy, BettingEntropyConfig, BettingEntropyConfigError, InvalidJitter, InvalidProbability, bounded_humanization_rejects_inverted_bounds(), bounded_humanization_respects_legal_amounts(), deterministic_for_a_seed() (+9 more)

### Community 60 - "Product facts the integration depends on (see the integration plan for details)"
Cohesion: 0.08
Nodes (24): AUTHORIZATIONS (edit before pasting), Captures, Decisions already made by the user, Envelope, Environment (already installed and pinned; see `scripts/laya-pins.json`), Frames and geometry, Goal, Live evidence tool (+16 more)

### Community 61 - "FieldName"
Cohesion: 0.08
Nodes (24): FieldName, Acting, Badge, BigBlind, BoardCount, BoardSlot, Dealer, DisplayedStack (+16 more)

### Community 62 - "WindowsCapturer"
Cohesion: 0.12
Nodes (10): Apartment, backend(), copy_bgra_rows(), idle_frame_pool_requests_a_new_session_without_blocking(), needs_fresh_session(), OwnedCaptureFrame, qpc_now(), remaining_frame_wait() (+2 more)

### Community 63 - "status"
Cohesion: 0.10
Nodes (23): Checkpoint B Additions, JSON-lines contracts, live schema version 2, Live records, Monitor and Reference, browser snapshot version 1, Replay, listing, doctor and evaluation, States and reasons, 0. Rules (unchanged, verbatim from the handoff), 2. Decisions (confirmed with the user 2026-10-09T21:00Z) (+15 more)

### Community 64 - "body"
Cohesion: 0.22
Nodes (5): b64(), body(), HandleTests, png(), ValidateTests

### Community 65 - "profile.rs"
Cohesion: 0.16
Nodes (11): default_profile_has_human_plausible_parameters(), GhostProfile, json_round_trip_preserves_parameters(), ProfileError, Io, Parse, Validation, ProfileValidationError (+3 more)

### Community 66 - "temporal.rs"
Cohesion: 0.20
Nodes (9): invalid_manual_config_does_not_panic(), median_of(), medians_increase_with_complexity(), rejects_invalid_temporal_config(), rng(), samples_stay_within_clamp_bounds(), sampling_is_deterministic_for_a_seed(), TemporalConfig (+1 more)

### Community 67 - "vlm.rs"
Cohesion: 0.09
Nodes (16): ScriptedBackend, base64_png(), defaults_target_the_loopback_laya_server(), encode_png(), error_codes_are_closed_categories(), http_agent(), png_encoding_round_trips(), validate_endpoint() (+8 more)

### Community 68 - "InferenceConsentTests"
Cohesion: 0.10
Nodes (3): 1. Facts verified against the repo that change the handoff text, InferenceConsentTests, source()

### Community 69 - "TableContentWitness"
Cohesion: 0.14
Nodes (12): PartialObservation, region_digest(), region_matches(), region_witness(), RegionWitness, SourceRegionWitnesses, SourceWitnessError, AlreadyBound (+4 more)

### Community 70 - "headless.rs"
Cohesion: 0.18
Nodes (11): Capture, Emit, emits_clear_event(), emits_one_json_line_per_decision(), HeadlessEmitter, HeadlessEmitter<E>, std::sync::Arc<Capture>, stdout() (+3 more)

### Community 71 - "inference_loop"
Cohesion: 0.19
Nodes (8): Approval, inference_loop(), ManualSource, ManualSource<'a, S, C>, ManualWorker, run(), validate_experimental_opt_in(), CaptureTiming

### Community 72 - "geometry.rs"
Cohesion: 0.19
Nodes (11): box_px(), content_rect(), crop(), crops_have_the_box_size_and_tiny_crops_are_refused(), Geometry, readout_tracking_crops_preserve_every_original_byte_and_ignore_only_other_regions(), readout_tracking_frames(), region_px() (+3 more)

### Community 74 - "Rank"
Cohesion: 0.12
Nodes (17): Rank, Ace, Eight, Five, Four, Jack, King, Nine (+9 more)

### Community 75 - "Position6max"
Cohesion: 0.12
Nodes (14): is_openable(), open_range(), Position6max, .ALL, Bb, Btn, Co, Hj (+6 more)

### Community 76 - "WagerPassRegistry"
Cohesion: 0.20
Nodes (8): registry(), registry_descriptors_are_versioned_distinct_closed_and_scaled_without_old_regions(), valid_digest(), WAGER_PROVENANCE, WAGER_REGISTRY_VERSION, WagerPassConfig, WagerPassRegistry, WagerRegion

### Community 77 - "acceptSnapshot"
Cohesion: 0.24
Nodes (18): acceptSnapshot(), admitExperimental(), admitObservation(), announce(), clearExperimental(), clearObservation(), clearRetained(), closeObservation() (+10 more)

### Community 78 - "ExperimentalTests"
Cohesion: 0.25
Nodes (3): __init__(), ExperimentalTests, invalid()

### Community 79 - "manual_capture.rs"
Cohesion: 0.18
Nodes (13): automatic_approval_requires_its_own_policy_and_never_a_seated_assertion(), experimental_approval_is_bounded_automatic_only_and_capture_flag_is_explicit(), fail(), manual_capture_approval_is_fresh_strict_and_bounded(), manual_capture_fake_source_count_resize_and_stop_are_one_shot(), manual_capture_identity_allows_only_resize_not_replacement(), manual_inference_requires_separate_assertion_mode_and_service_instance(), MAX_FRAMES (+5 more)

### Community 80 - "laya/partial.rs"
Cohesion: 0.22
Nodes (10): parse_amount(), amount(), assemble_partial(), assemble_partial_with_wagers(), RANKS, Reading, record(), run_reading() (+2 more)

### Community 81 - "2. Steps and gates"
Cohesion: 0.07
Nodes (26): 0. Decisions (user, 2026-10-09T15:4xZ), 1. Facts this plan relies on (verified in planning), 2. Steps and gates, 3.1 Confidence, 3.2 R5 (amended) — amounts, 3.3 New and clarified rules (0.3.0), 3.4 Strictness, 3.5 Pass order (+18 more)

### Community 82 - "main.rs"
Cohesion: 0.15
Nodes (8): product_cli_rejects_retired_alternate_ports_and_wrong_routes_before_io(), validate_vlm_endpoint(), convert_cards(), local_laya_endpoints_are_allowed(), main(), remote_laya_endpoints_are_always_rejected(), report_warning(), run_stdin_pipeline()

### Community 83 - "SourcePolicy"
Cohesion: 0.19
Nodes (8): SourcePolicy, AutomaticBounded, AutomaticSustained, Manual, valid_approval(), ActivityGate, automatic_gate_rejects_duplicate_expired_and_geometry_only_activity_evidence(), poll_delay()

### Community 84 - ".now_ms"
Cohesion: 0.24
Nodes (6): ManualSource<'_, S, C>, Source, sustained_approval(), sustained_capture_passes_600_seconds_and_1200_acquisitions_with_frozen_evidence(), sustained_ended_evidence_still_rejects_source_capture_and_clock_failures(), sustained_unexpected_recorder_io_is_terminal_not_an_evidence_end()

### Community 85 - "Execution Steps"
Cohesion: 0.13
Nodes (14): 1. Revalidate ownership and record the starting state, 2. Shut down the legacy automatic runtime, 3. Build and check the non-capturing entry point, 4. Start the updated dashboard-only service, 5. Verify the idle state end to end, 6. Prepare source identification, without capture, 7. Deliver the bounded next-session handoff and stop, Approval Plan: Controlled Dashboard-Only Runtime Refresh (+6 more)

### Community 86 - "ManualSessionFeed"
Cohesion: 0.09
Nodes (19): Actual transport, Authorized Second Attempt, Bounded Diagnostics and Sustained Observation, Capability matrix, Confirm and start, Current Work Authorization, Explicit Automatic Startup (Observer or Seated), First Runtime Finding and Correction (+11 more)

### Community 87 - "extend_partial"
Cohesion: 0.27
Nodes (3): extend_partial(), ScenePassConfig, ScenePassRegistry

### Community 88 - ".setUp"
Cohesion: 0.08
Nodes (4): build(), __getitem__(), EnginePrefixTests, prefix()

### Community 89 - "7. Phase gates"
Cohesion: 0.14
Nodes (14): 7. Phase gates, Active follow-on: dashboard/history first, baseline still FAIL, Approved stage2 implementation, not live acceptance (2026-10-10), Authorized Automatic Observer Trials (2026-10-12), Checkpoint B implementation and current blocker (2026-10-10), Current: iteration-1 Gate F FAIL (2026-10-09), Desktop companion / bounded manual diagnostic (2026-10-11), Historical A-D proposals and B-lite results (+6 more)

### Community 90 - "CaptureError"
Cohesion: 0.10
Nodes (18): CaptureError, AmbiguousWindows, Backend, ConfigurationRequired, NoWindowSelected, PermissionDenied, StaleWindow, UnsupportedPlatform (+10 more)

### Community 91 - "WindowKind"
Cohesion: 0.50
Nodes (4): WindowKind, Lobby, Table, Unknown

### Community 92 - "scene.rs"
Cohesion: 0.22
Nodes (10): clear_field(), field_known(), reject(), reject_contradictions(), retain_agreement(), SCENE_FIELDS, SCENE_NOTE, SCENE_PROVENANCE (+2 more)

### Community 93 - "DecisionView"
Cohesion: 0.20
Nodes (10): analyze_frame(), analyze_laya_frame(), finish_analysis(), finish_laya_analysis(), Pipeline, ManualWorker<W>, synthetic_analysis(), Analysis (+2 more)

### Community 94 - "app.js"
Cohesion: 0.31
Nodes (12): fieldStatuses(), httpsUrl(), normalizeCard(), normalizeExperimental(), normalizeHistory(), normalizeObservation(), normalizePartialObservation(), normalizeRecording() (+4 more)

### Community 95 - "IntegrationTests"
Cohesion: 0.18
Nodes (3): IntegrationTests, service(), worker()

### Community 98 - "Next Conversation: Deliver Verified Live Table Data"
Cohesion: 0.17
Nodes (11): Changes Already Implemented, Controlled Live Loop, Definition Of Done, Evidence And Entry Points, Historical Incoming Baseline, Integrity Boundaries, Latest Operator Instructions And Verified State, Next Conversation: Deliver Verified Live Table Data (+3 more)

### Community 99 - "laya_prep.py"
Cohesion: 0.23
Nodes (6): box_px(), _components(), content_rect(), segment_glyphs(), _text_mask(), _text_score()

### Community 100 - "DecisionApp"
Cohesion: 0.25
Nodes (3): app_starts_empty_and_accepts_decisions(), DecisionApp, run()

### Community 101 - ".new"
Cohesion: 0.23
Nodes (9): assert_sustained_board_pair_at_latency(), exercise_sustained_schedule(), experimental_diagnostics_cannot_create_actions_admission_or_historical_ledger_entries(), sustained_board_pair_admits_at_1500ms_with_unknown_role(), sustained_board_pair_admits_at_2000ms_with_unknown_role(), sustained_board_pair_rejects_stale_seed_expired_job_and_failed_core(), sustained_board_schedule_and_runtime_admit_above_floor_distinct_unsaved_reads(), sustained_pairs_revisit_all_seats_within_ten_seconds_at_one_second_job_latency() (+1 more)

### Community 102 - "saved_capture_schedule.rs"
Cohesion: 0.23
Nodes (4): runtime_submissions(), SavedFrame, stopped_saved_capture_stability_replay(), stopped_saved_readout_scope_replay()

### Community 103 - "DiscoveryState"
Cohesion: 0.18
Nodes (11): DiscoveryState, AmbiguousMultipleTables, CandidateTable, CapturingTable, ConfigurationRequired, LobbyDetected, PermissionRequired, Recovering (+3 more)

### Community 105 - "Value"
Cohesion: 0.20
Nodes (12): asserted(), Frame, keep_original_lease(), Reading, SeatFrame, SeatView, Tracker, valid_capture() (+4 more)

### Community 106 - "Laya Vision Prototype — Phase A Design (Question Set + Calibration Corpus)"
Cohesion: 0.20
Nodes (10): 1. Historical motivation, 2. Initial model facts (2026-10-09, licensing corrected), 3. Historical Phase A architecture, 4. Historical first baseline findings (recorded 2026-10-09), 5. Historical Phase A corpus and annotation protocol, 6.1 Range and odds provenance (screenshots, not the PDF), 6. The reference sheet drives the Laya logic (poker-info-sheet.pdf), 8. Current risks and open assumptions (+2 more)

### Community 107 - "LiveEvent"
Cohesion: 0.13
Nodes (14): LiveEvent, CaptureHealth, Clear, Discarded, Observation, ObservationInvalidated, PartialObservation, PartialObservationInvalidated (+6 more)

### Community 108 - "Engine"
Cohesion: 0.20
Nodes (3): initialize(), Engine, initialize()

### Community 112 - "WagerTests"
Cohesion: 0.20
Nodes (3): RegistryPinTests, SceneTests, WagerTests

### Community 113 - "widgets.rs"
Cohesion: 0.36
Nodes (6): equity_and_ev_formatting(), no_pot_odds_when_facing_no_bet(), pot_odds_ratio_label_formats_as_ratio(), summary_annotates_raise_amounts(), summary_includes_action_and_metrics(), view()

### Community 114 - "pipeline_smoke.rs"
Cohesion: 0.25
Nodes (4): convert_cards(), cross_crate_pipeline_produces_a_decision_view(), FLOP_STATE, state_machine_and_parser_agree_on_phases()

### Community 115 - "random_pass"
Cohesion: 0.56
Nodes (3): random_pass(), seeded_random_answer_maps_always_produce_parseable_envelopes(), XorShift

### Community 116 - "PlayerState"
Cohesion: 0.22
Nodes (5): PlayerState, complete_players(), CompleteGameState, required_nullable(), TablePlayer

### Community 117 - "coinpoker-help"
Cohesion: 0.22
Nodes (9): Architecture, CLI, coinpoker-help, Current model and browser, Known limits, Privacy and model provenance, Start here, Structured replay (+1 more)

### Community 118 - "Suit"
Cohesion: 0.29
Nodes (6): RsSuit, Suit, Clubs, Diamonds, Hearts, Spades

### Community 119 - "EquityError"
Cohesion: 0.25
Nodes (8): EquityError, BoardTooLarge, DeckExhausted, DuplicateCard, EmptyHands, InvalidHandSize, NoOpponents, ZeroIterations

### Community 120 - "DecisionComplexity"
Cohesion: 0.25
Nodes (8): DecisionComplexity, PostflopCall, PostflopRaise, PostflopSimple, PreflopCall, PreflopFold, PreflopRaise, RiverAllin

### Community 121 - "GamePhase"
Cohesion: 0.29
Nodes (7): GamePhase, Flop, Lobby, Preflop, River, Showdown, Turn

### Community 122 - "text"
Cohesion: 0.36
Nodes (8): activityQualified(), filterReference(), loadReference(), renderAction(), renderHistory(), renderHistoryEvents(), showTab(), text()

### Community 123 - "renderObservation"
Cohesion: 0.43
Nodes (8): make(), reasonFor(), renderCards(), renderControls(), renderDiagnostics(), renderObservation(), retainedCount(), retainedLabel()

### Community 124 - "Windows installation and calibration"
Cohesion: 0.29
Nodes (7): 1. Prerequisites, 2. Reuse and verify the existing Laya checkpoint, 3. Open the read-only local dashboard, 4. Historical passive-profile diagnostics, 5. Evaluate and record acceptance, Historical candidate archive and current omissions, Windows installation and calibration

### Community 126 - "TemporalConfigError"
Cohesion: 0.33
Nodes (6): TemporalConfigError, InvalidMaximum, InvalidMinimum, InvertedBounds, NonFiniteSigma, NonPositiveSigma

### Community 127 - "Local visual evaluation, manifest format 2"
Cohesion: 0.33
Nodes (6): Acceptance thresholds, Fixture schema, Local visual evaluation, manifest format 2, Required held-out local corpus, Retention, Run

### Community 128 - "coinpoker"
Cohesion: 0.33
Nodes (6): coinpoker, core-engine, ghost-layer, ingest, opponent-model, ui

### Community 129 - "renderSource"
Cohesion: 0.60
Nodes (6): captureHealthy(), recordingBudgetOpen(), recordingFresh(), renderSource(), retentionAllowed(), updateRecordingLease()

### Community 130 - "PartialObservationView"
Cohesion: 0.20
Nodes (7): consensus_retains_literal_amounts_and_independent_cards_not_unverified_fields(), PartialObservationView, ObservationRole, Observing, SeatedWaiting, Uncertain, YourTurn

### Community 132 - "Windows VLM compatibility record"
Cohesion: 0.40
Nodes (5): Active Laya-only candidate, Historical Gemma candidate and expected hashes, Historical runtime decision, Historical transport and acceptance checks, Windows VLM compatibility record

### Community 133 - "Windows acceptance report, format 1"
Cohesion: 0.40
Nodes (5): Current Laya and follow-on status, Historical candidate gates, Historical candidate smoke order, Historical environment and provenance, Windows acceptance report, format 1

### Community 135 - "Contributing"
Cohesion: 0.50
Nodes (4): Active development scope, Change rules, Contributing, Toolchain and checks

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

### Community 153 - "emit_with_history"
Cohesion: 0.16
Nodes (21): a_new_run_does_not_inherit_history_or_admission_counters(), admitted_observation_emits_one_opaque_gap_summary_after_successful_write(), AdmittedHistory, current_capture_health_tracks_unvalidated_gaps_without_inference(), emit_with_history(), heartbeat_does_not_erase_original_source_bound_partial_stacks(), history_record(), history_source() (+13 more)

### Community 155 - "prompt.rs"
Cohesion: 0.36
Nodes (6): build_analysis_prompt(), example(), examples_specify_the_full_strict_screen_envelope(), prompts_classify_first_without_assuming_a_table(), SYSTEM_PROMPT, table_example_preserves_strict_poker_requirements()

### Community 156 - "Position"
Cohesion: 0.29
Nodes (7): Position, Bb, Btn, Co, Hj, Sb, Utg

### Community 159 - "ActionBasis"
Cohesion: 0.50
Nodes (4): ActionBasis, Badge, Commitment, Unknown

## Knowledge Gaps
- **699 isolated node(s):** `USAGE`, `Capture`, `Stdin`, `ListWindows`, `Doctor` (+694 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1237 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **28 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `status()` connect `status` to `text`, `coinpoker-help — Readiness Assessment and Validation Plan`, `app.js`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `CompanionUiTests` (e.g. with `ExperimentalCandidateTests` and `ManualFeedTests`) actually correct?**
  _`CompanionUiTests` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `USAGE`, `Capture`, `Stdin` to the rest of the system?**
  _699 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `CompanionUiTests` be split into smaller, more focused modules?**
  _Cohesion score 0.06281920326864147 - nodes in this community are weakly interconnected._
- **Why does `T8. Step 9 — docs and records` connect `status` to `laya_capture.py`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Should `recorder.rs` be split into smaller, more focused modules?**
  _Cohesion score 0.06264609630668537 - nodes in this community are weakly interconnected._
- **Why does `ManualSessionFeed` connect `ManualSessionFeed` to `laya_dashboard.py`, `laya_capture.py`, `laya-server.py`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._