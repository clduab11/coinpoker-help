"""Offline source-bound diagnostic candidates; no model, source or client operations."""
import copy
import json
import unittest

from scripts.tests import test_laya_dashboard_stage2 as stage2
from scripts.tests import test_manual_inference as manual

dashboard = stage2.dashboard
INSTANCE, SESSION = "b" * 32, "a" * 32


def candidate_record(clock, seat=1, kind="wager", text="12.50", generation=1, epoch=1):
    now = int(clock.wall() * 1000)
    region = {"id": f"seat_{seat}_{kind}", "reference_dimensions": [900, 686],
              "bounds": list(dashboard.EXPERIMENTAL_BOUNDS[kind][seat - 1])}
    bounds = [(value * size + reference // 2) // reference for value, size, reference in
              zip(region["bounds"], (800, 613, 800, 613), (900, 686, 900, 686))]
    dimensions = [bounds[2] - bounds[0], bounds[3] - bounds[1]]
    descriptor = {"version": 1, "pass": f"p{6 if kind == 'wager' else 7}_seat_{seat}_{kind}",
                  "seat": seat, "region": region, **dashboard.EXPERIMENTAL_MARKERS}
    values = {f"g{i}": glyph for i, glyph in enumerate(text, 1)} if kind == "wager" else {
        field: "raise" if field == "badge" else "yes" if field == "acting" else labels[0]
        for field, labels in dashboard.SCENE_LABELS.items()}
    questions = [{"question": field, "answer": {"type": "choice", "value": value}, "score": .99,
                  "effective_floor": None, "status": "unknown", "reason": "unapproved-capability",
                  "truncated": False} for field, value in values.items()]
    fields = ["visible_wager"] if kind == "wager" else list(dashboard.SCENE_LABELS)
    return {"schema_version": 2, "event": "perception_diagnostics", "source_policy": "automatic-bounded",
            "activity_state": "verifying", "experimental_bet_action": True, "service_instance_id": INSTANCE,
            "observation": {"generation": generation, "epoch": epoch, "identity": copy.deepcopy(stage2.IDENTITY),
                            "captured_at_ms": 1000 + generation, "captured_at_unix_ms": now - 500},
            "captured_at_unix_ms": now - 500, "emitted_at_unix_ms": now,
            "expires_at_unix_ms": now + 1000, "valid_for_ms": 1000,
            "frame_width": 800, "frame_height": 613, "source_current": True, "admission": "source_current",
            "experimental": {"descriptor": descriptor, **dashboard.EXPERIMENTAL_MARKERS,
                "donor_pass": "p5_seat_1_stack" if kind == "wager" else None,
                "inherited_cutoff": .8 if kind == "wager" else None,
                "geometry_source": dashboard.EXPERIMENTAL_GEOMETRY, "crop_bounds": bounds,
                "crop_dimensions": dimensions, "core_accepted": True},
            "passes": [{"pass": descriptor["pass"], "crop_bounds": [bounds], "crop_dimensions": [dimensions],
                         "segments": {"n": len(text), "overflow": False} if kind == "wager" else None,
                         "questions": questions, "total_ms": 20}],
            "fields": [{"field": field, "seat": seat, "board_slot": None, "status": "unknown",
                        "reason": "unapproved-capability", "admission_status": "unknown",
                        "admission_reason": "unapproved-capability"} for field in fields], "timing": {}}


class ExperimentalCandidateTests(unittest.TestCase):
    def setUp(self):
        self.clock = stage2.Clock()
        self.state = dashboard.DashboardState("synthetic", monotonic=self.clock.mono, wall=self.clock.wall,
            experimental_bet_action=True, service_instance_id=INSTANCE)
        self.state.begin_stream()
        self.state.set_model("ready")
        self.fixture = stage2.PartialTests()
        self.fixture.state, self.fixture.clock = self.state, self.clock
        self.fixture.health()
        self.receipt = {"session_id": SESSION, "mode": "inference-enabled", "inference_enabled": True,
            "source_policy": "automatic-bounded", "status": "capturing", "activity_state": "verifying",
            "experimental_bet_action": True, "updated_at_unix_ms": int(self.clock.wall() * 1000),
            "remaining_ms": 600000, "recorded_frames": 7, "max_frames": 1200}
        self.bind()

    def bind(self, approved=True):
        self.state.set_experimental_receipt(self.receipt, approved=approved,
            deadline=self.clock.mono() + 600, session_id=self.state.session_id)

    def publish(self, **kwargs):
        self.state.ingest(candidate_record(self.clock, **kwargs), session_id=self.state.session_id)
        return self.state.snapshot()["experimental_candidates"]

    def test_all_twelve_draft_regions_project_only_safe_separate_diagnostics(self):
        for kind in ("wager", "scene"):
            for seat in range(1, 7):
                with self.subTest(kind=kind, seat=seat):
                    value = self.publish(kind=kind, seat=seat, generation=seat + (6 if kind == "scene" else 0))
                    self.assertEqual((value["kind"], value["seat"]), (kind, seat))
                    self.assertTrue(value["diagnostic_only"])
                    self.assertFalse(value["quality_approved"])
                    self.assertEqual(value["training"], "unvalidated")
                    self.assertEqual((value["geometry_status"], value["human_review"]), ("DRAFT", "PENDING"))
                    self.assertIsNone(value["fitted_floor"])
                    if kind == "wager":
                        self.assertEqual(value["numeric_text"], "12.50")
                    else:
                        self.assertEqual(next(v for v in value["scene"] if v["field"] == "badge")["guess"], "raise")
                    public = json.dumps(self.state.snapshot())
                    for private in ("raw_source_ids", "crop_bounds", "reference_dimensions", "geometry_source", "answer", "0x123", "coinpokergameclient"):
                        self.assertNotIn(private, public.lower())
                    snapshot = self.state.snapshot()
                    self.assertIsNone(snapshot["observation"])
                    self.assertIsNone(snapshot["partial_observation"])
                    self.assertIsNone(snapshot["advice"])
                    self.assertEqual(snapshot["history"]["events"], [])
                    self.assertEqual(snapshot["history"]["counts"], {})

    def test_empty_overflow_bad_glyph_below_donor_and_legitimate_zero(self):
        variants = [("", {}, "empty-segmentation"), ("0", {}, "unapproved-capability"),
                    ("12", {"overflow": True}, "segmentation-overflow"), ("99", {"score": .799}, "below-floor"),
                    ("99", {"glyph": "not_a_character"}, "invalid-answer"),
                    ("99999999", {}, "invalid-amount")]
        for generation, (text, extra, reason) in enumerate(variants, 1):
            record = candidate_record(self.clock, text=text, generation=generation)
            selected = record["passes"][0]
            if "overflow" in extra:
                selected["segments"]["overflow"] = extra["overflow"]
            if "score" in extra:
                selected["questions"][0]["score"] = extra["score"]
            if "glyph" in extra:
                selected["questions"][0]["answer"]["value"] = extra["glyph"]
            self.state.ingest(record)
            value = self.state.snapshot()["experimental_candidates"]
            self.assertEqual(value["reason"], reason)
            self.assertEqual(value["numeric_text"], "0" if text == "0" else None)

    def test_unused_missing_glyphs_remain_unknown_without_invalidating_present_candidate(self):
        record = candidate_record(self.clock, text="12")
        record["passes"][0]["questions"] += [{"question": f"g{i}", "answer": None, "score": None,
            "effective_floor": None, "status": "unknown", "reason": "missing-answer", "truncated": False}
            for i in range(3, 9)]
        self.state.ingest(record)
        self.assertEqual(self.state.snapshot()["experimental_candidates"]["numeric_text"], "12")
        record = candidate_record(self.clock, generation=2, text="12")
        record["passes"][0]["questions"][0]["truncated"] = True
        self.state.ingest(record)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"]["numeric_text"])

    def test_forged_descriptor_proofs_bounds_target_floors_and_scores_rejected(self):
        mutations = [lambda r: r["experimental"].update(training="trained_unapproved"),
            lambda r: r["experimental"].update(human_verified=True),
            lambda r: r["experimental"]["descriptor"].update(held_out_approved=True),
            lambda r: r["experimental"]["descriptor"]["region"]["bounds"].__setitem__(0, 316),
            lambda r: r["experimental"]["crop_bounds"].__setitem__(0, 1),
            lambda r: r["experimental"].update(inherited_cutoff=.79),
            lambda r: r["experimental"].update(core_accepted=False),
            lambda r: r["passes"][0]["questions"][0].update(effective_floor=.8),
            lambda r: r["passes"][0]["questions"][0].update(status="accepted"),
            lambda r: r["passes"][0]["questions"][0].update(score=True),
            lambda r: r.update(quality_approved=True)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                record = candidate_record(self.clock, generation=index + 1)
                mutate(record)
                self.state.ingest(record)
                self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        scene = candidate_record(self.clock, kind="scene", generation=20)
        scene["experimental"]["inherited_cutoff"] = .8
        self.state.ingest(scene)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_lease_ages_do_not_renew_and_expired_generation_cannot_replay(self):
        record = candidate_record(self.clock)
        self.state.ingest(record)
        expiry = self.state.snapshot()["experimental_candidates"]["expires_at_unix_ms"]
        self.clock.value += .5
        replay = copy.deepcopy(record)
        replay.update(valid_for_ms=4000, expires_at_unix_ms=expiry + 2000)
        self.state.ingest(replay)
        self.assertEqual(self.state.snapshot()["experimental_candidates"]["expires_at_unix_ms"], expiry)
        self.clock.value += .501
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.state.ingest(replay)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_late_invalid_diagnostic_cannot_clear_newer_but_same_and_newer_invalidate(self):
        old = candidate_record(self.clock)
        self.state.ingest(old)
        newer = candidate_record(self.clock, generation=2, text="42")
        self.state.ingest(newer)
        self.state.ingest({**old, "source_current": False, "admission": "obsolete_observation"})
        self.assertEqual(self.state.snapshot()["experimental_candidates"]["numeric_text"], "42")
        self.state.ingest({**newer, "source_current": False})
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.state.ingest(newer)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_source_roi_epoch_geometry_and_service_fences_fail_closed(self):
        for index, mutate in enumerate((lambda r: r["observation"].update(epoch=2),
                lambda r: r["observation"]["identity"].update(hwnd="0x999"),
                lambda r: r.update(frame_width=900), lambda r: r.update(service_instance_id="c" * 32),
                lambda r: r.update(experimental_bet_action=False))):
            with self.subTest(index=index):
                record = candidate_record(self.clock, generation=index + 1)
                mutate(record)
                self.state.ingest(record)
                self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_flags_approval_owner_heartbeat_stop_and_source_loss_clear(self):
        self.assertIsNotNone(self.publish())
        self.bind(approved=False)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.bind()
        self.assertIsNotNone(self.publish(generation=2))
        self.receipt["experimental_bet_action"] = False
        self.bind()
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.receipt["experimental_bet_action"] = True
        self.bind()
        self.assertIsNotNone(self.publish(generation=3))
        self.clock.value += 2.501
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.fixture.health(generation=4)
        self.receipt["updated_at_unix_ms"] = int(self.clock.wall() * 1000)
        self.bind()
        self.assertIsNotNone(self.publish(generation=4))
        self.state.end_stream()
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_diagnostic_log_cap_does_not_disable_valid_current_projection(self):
        self.state.diagnostics.path = dashboard.ROOT / ".local/unused-cap-test.jsonl"
        self.state.diagnostics.max_events = 0
        self.assertIsNotNone(self.publish())
        self.assertFalse(self.state.diagnostics.complete)
        self.assertEqual(self.state.diagnostics.count, 0)

    def test_private_metadata_preserves_valid_draft_provenance_without_public_leak_or_aliasing(self):
        record = candidate_record(self.clock)
        record["raw_source_ids"] = "PRIVATE"
        saved = dashboard.private_perception(record)
        self.assertEqual(saved["experimental"], record["experimental"])
        self.assertNotIn("raw_source_ids", saved)
        record["experimental"]["crop_bounds"][0] += 1
        self.assertNotEqual(saved["experimental"]["crop_bounds"], record["experimental"]["crop_bounds"])
        forged = candidate_record(self.clock, generation=2)
        forged["experimental"]["human_verified"] = True
        self.assertNotIn("experimental", dashboard.private_perception(forged))

    def test_source_false_and_rejected_core_keep_private_diagnostics_but_never_public_candidates(self):
        record = candidate_record(self.clock, kind="scene")
        record.update(source_current=False, admission="obsolete_observation")
        record["experimental"]["core_accepted"] = False
        saved = dashboard.private_perception(record)
        self.assertFalse(saved["experimental"]["core_accepted"])
        self.assertFalse(saved["source_current"])
        self.state.ingest(record)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.assertEqual(self.state.snapshot()["history"]["events"], [])
        self.assertIsNone(self.state.snapshot()["advice"])

    def test_candidate_source_epoch_loss_and_terminal_receipt_clear_without_changing_numeric_fields(self):
        self.state.ingest(self.fixture.record())
        self.assertIsNotNone(self.publish(generation=2))
        before = self.state.snapshot()["partial_observation"]
        self.receipt["status"] = "stopped"
        self.bind()
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.assertEqual(self.state.snapshot()["partial_observation"], before)
        self.receipt["status"] = "capturing"
        self.bind()
        self.assertIsNotNone(self.publish(generation=3))
        self.fixture.health(generation=4, epoch=2)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.fixture.health(generation=5, epoch=2, identity=None, fresh_capture=False)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_exact_five_second_candidate_deadline_with_continuing_source_is_not_renewed(self):
        record = candidate_record(self.clock)
        record.update(expires_at_unix_ms=record["captured_at_unix_ms"] + 5000, valid_for_ms=4500)
        self.state.ingest(record)
        for step in range(1, 5):
            self.clock.value += 1
            self.fixture.health(generation=step + 1)
            self.receipt["updated_at_unix_ms"] = int(self.clock.wall() * 1000)
            self.bind()
            self.assertEqual(self.state.snapshot()["experimental_candidates"]["expires_at_unix_ms"], record["expires_at_unix_ms"])
        self.clock.value += .501
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_strict_five_second_limit_and_newer_invalidation_do_not_allow_replay(self):
        record = candidate_record(self.clock)
        captured = record["captured_at_unix_ms"]
        record.update(expires_at_unix_ms=captured + 5001, valid_for_ms=4501)
        self.state.ingest(record)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        record = candidate_record(self.clock, generation=2)
        self.state.ingest(record)
        self.assertIsNotNone(self.state.snapshot()["experimental_candidates"])
        self.state.ingest({"schema_version": 2, "event": "observation_invalidated", "generation": 3,
                          "epoch": 1, "reason": "source-region-changed"})
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])
        self.state.ingest(record)
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_numeric_readout_expiry_does_not_end_newer_experimental_source_lease(self):
        self.state.ingest(self.fixture.record())
        record = candidate_record(self.clock, generation=2)
        record.update(expires_at_unix_ms=record["captured_at_unix_ms"] + 4500, valid_for_ms=4000)
        self.state.ingest(record)
        self.clock.value += 1.001
        self.fixture.health(generation=3)
        self.receipt["updated_at_unix_ms"] = int(self.clock.wall() * 1000)
        self.bind()
        snapshot = self.state.snapshot()
        self.assertIsNone(snapshot["partial_observation"])
        self.assertIsNotNone(snapshot["experimental_candidates"])

    def test_service_approval_flag_and_session_binding_never_come_from_record(self):
        self.state.experimental_bet_action = False
        self.assertIsNone(self.publish())
        self.state.experimental_bet_action = True
        self.bind(approved=1)
        self.assertIsNone(self.publish(generation=2))
        self.bind()
        self.assertIsNotNone(self.publish(generation=3))
        self.receipt["session_id"] = "c" * 32
        self.bind()
        self.assertIsNone(self.state.snapshot()["experimental_candidates"])

    def test_candidates_never_rewrite_admitted_fields_or_history(self):
        self.state.ingest(self.fixture.record())
        before = self.state.snapshot()["partial_observation"]
        value = self.publish(kind="scene", generation=2)
        self.assertIsNotNone(value)
        snapshot = self.state.snapshot()
        self.assertEqual(snapshot["partial_observation"], before)
        self.assertTrue(all(seat["visible_wager"] is None for seat in snapshot["partial_observation"]["seats"]))
        self.assertEqual(snapshot["history"]["gaps"], 0)
        self.assertFalse(snapshot["server"]["advice_ready"])

    def test_actual_public_projection_round_trips_through_actual_renderer(self):
        from scripts.tests.test_companion_ui import CompanionUiTests
        ui = CompanionUiTests()
        ui.setUp()
        ui.experimental_session()
        ui.snapshot["experimental_candidates"] = self.publish()
        ui.run_ui("experimental-live")


class ExperimentalFeedTests(unittest.TestCase):
    def setUp(self):
        self.fixture = manual.ManualFeedTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.state.experimental_bet_action = True
        self.fixture.state.service_instance_id = INSTANCE

    def session(self):
        path = self.fixture.automatic_session(experimental_bet_action=True)
        approval = manual.capture.read_json(path / "approval.json")
        approval["experimental_bet_action"] = True
        manual.capture.write_json(path / "approval.json", approval)
        return path

    def test_actual_passive_feed_projects_only_explicit_bound_automatic_diagnostics_and_revokes(self):
        path = self.session()
        self.fixture.append_automatic(path, self.fixture.health(), candidate_record(self.fixture.clock))
        self.fixture.feed.poll()
        snapshot = self.fixture.feed.snapshot()
        self.assertEqual(snapshot["experimental_candidates"]["numeric_text"], "12.50")
        self.assertIsNone(snapshot["partial_observation"])
        self.assertIsNone(snapshot["observation"])
        self.assertIsNone(snapshot["advice"])
        self.assertEqual(snapshot["history"]["events"], [])
        approval = manual.capture.read_json(path / "approval.json")
        approval["experimental_bet_action"] = False
        manual.capture.write_json(path / "approval.json", approval)
        self.assertIsNone(self.fixture.feed.snapshot()["experimental_candidates"])

    def test_service_flag_false_cannot_be_overridden_by_valid_receipt_or_event(self):
        self.fixture.state.experimental_bet_action = False
        path = self.session()
        self.fixture.append_automatic(path, self.fixture.health(), candidate_record(self.fixture.clock))
        self.fixture.feed.poll()
        self.assertIsNone(self.fixture.feed.snapshot()["experimental_candidates"])

    def test_actual_feed_terminal_stop_and_service_mismatch_clear_candidates(self):
        path = self.session()
        self.fixture.append_automatic(path, self.fixture.health(), candidate_record(self.fixture.clock))
        self.fixture.feed.poll()
        self.assertIsNotNone(self.fixture.feed.snapshot()["experimental_candidates"])
        record = candidate_record(self.fixture.clock, generation=2)
        record["service_instance_id"] = "c" * 32
        self.fixture.append_automatic(path, record)
        self.fixture.feed.poll()
        self.assertIsNone(self.fixture.feed.snapshot()["experimental_candidates"])
        self.assertEqual(manual.capture.public_snapshot(root=self.fixture.root)["stop_reason"], "feed-failed")


if __name__ == "__main__":
    unittest.main()
