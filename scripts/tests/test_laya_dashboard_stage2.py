"""Offline partial-consumer tests: fake clocks, native DTOs and a static Node DOM."""

import copy
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.tests.test_laya_dashboard import Clock, IDENTITY, dashboard, native_decision, native_observation


def capability(field, seat=None):
    floors = {"role": .995, "hero_seated": .995, "game_phase": .995,
              "board_count": 1.0, "board_slot": 1.0, "pot_size": .8, "displayed_stack": .8}
    trained = field in floors
    return {"field": field, "seat": seat, "training": "trained_unapproved" if trained else "unsupported",
            "acceptance_floor": floors.get(field), "held_out_approved": False, "human_verified": False,
            "provenance": "it1-existing-pass" if trained else "observation-only-proposal"}


class PartialTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.state = dashboard.DashboardState("synthetic", monotonic=self.clock.mono, wall=self.clock.wall)
        self.state.begin_stream()
        self.health()

    def health(self, generation=1, epoch=1, **extra):
        now = int(self.clock.wall() * 1000)
        self.state.ingest({"schema_version": 2, "event": "capture_health", "generation": generation,
                           "epoch": epoch, "identity": IDENTITY, "fresh_capture": True, "frame_count": 7,
                           "emitted_at_unix_ms": now, "captured_at_unix_ms": now,
                           "frame_width": 800, "frame_height": 613, **extra})

    def test_public_capture_epoch_survives_missing_observation_and_tracks_epoch_only_changes(self):
        snap = self.state.snapshot()
        self.assertIsNone(snap["partial_observation"])
        self.assertEqual(snap["capture"]["epoch"], 1)
        self.health(generation=2, epoch=2)
        snap = self.state.snapshot()
        self.assertEqual(snap["capture"]["epoch"], 2)
        self.assertIsNone(snap["partial_observation"])
        self.assertNotIn("identity", snap["capture"])
        self.assertRegex(snap["capture"]["source_id"], r"^[0-9a-f]{16}$")
        self.assertEqual(snap["capture"]["generation"], 2)
        self.assertNotIn("PRIVATE", json.dumps(snap["capture"]))

    def test_public_capture_epoch_preserves_known_source_during_freshness_lag_not_source_loss(self):
        self.health(generation=2, fresh_capture=False)
        snap = self.state.snapshot()
        self.assertEqual(snap["capture"]["epoch"], 1)
        self.assertFalse(snap["capture"]["fresh_capture"])
        self.assertIsNone(snap["partial_observation"])
        self.health(generation=3, epoch=2, identity=None)
        self.assertIsNone(self.state.snapshot()["capture"]["epoch"])

    def test_public_capture_epoch_clears_on_terminal_blocked_and_expired_owner(self):
        self.state.end_stream()
        self.assertIsNone(self.state.snapshot()["capture"]["epoch"])
        self.state.begin_stream()
        self.assertIsNone(self.state.snapshot()["capture"]["epoch"])
        self.health()
        self.state.attach_blocked("source-unavailable")
        self.assertIsNone(self.state.snapshot()["capture"]["epoch"])
        self.state.begin_stream()
        self.health()
        self.clock.value += 3
        self.assertIsNone(self.state.snapshot()["capture"]["epoch"])

    def record(self, generation=1, epoch=1, **extra):
        now = int(self.clock.wall() * 1000)
        capabilities = [capability(field) for field in ("role", "hero_seated", "game_phase",
                                                       "board_count", "board_slot", "pot_size")]
        for seat in range(1, 7):
            capabilities += [capability(field, seat) for field in dashboard.SEAT_FIELDS]
        return {"schema_version": 2, "event": "partial_observation",
                "observation": {"generation": generation, "epoch": epoch, "identity": IDENTITY,
                                "captured_at_ms": 1000 + generation},
                "captured_at_unix_ms": now - 500, "emitted_at_unix_ms": now,
                "expires_at_unix_ms": now + 1000, "valid_for_ms": 1000,
                "game_phase": "flop", "board_count": 3, "role": None, "hero_seated": None,
                "board_slots": [{"rank": "ace", "suit": "hearts"}, None,
                                {"rank": "two", "suit": "spades"}, None, None],
                "pot_size": 12345,
                "seats": [{"seat": seat, "displayed_stack": stack} for seat, stack in
                          enumerate((100, 200, None, 0, 500, 600), 1)],
                "verified_fields": list(dashboard.PARTIAL_FIELDS), "capabilities": capabilities,
                "quality_approved": False, **extra}

    def reading(self, **extra):
        self.state.ingest(self.record(**extra))
        return self.state.snapshot()["partial_observation"]

    def scoped_invalidation(self, source, **extra):
        ticket = copy.deepcopy(source["observation"])
        return {"schema_version": 2, "event": "partial_observation_invalidated",
                "observation": ticket, "generation": ticket["generation"], "epoch": ticket["epoch"],
                "identity": copy.deepcopy(ticket["identity"]), "reason": "source-region-changed",
                "captured_at_unix_ms": ticket.get("captured_at_unix_ms"),
                "emitted_at_unix_ms": int(self.clock.wall() * 1000), **extra}

    def manual_tail(self, records, **current_extra):
        instance, session = "b" * 32, "a" * 32
        current = {"session_id": session, "mode": "inference-enabled", "inference_enabled": True,
                    "source_policy": "automatic-bounded", "status": "capturing", "remaining_ms": 10000,
                    "activity_state": "active", "recorded_frames": 7, "max_frames": 100, **current_extra}
        self.state.set_model("ready")
        feed = dashboard.ManualSessionFeed(self.state, instance)
        feed.session_id, feed.stream_id = session, self.state.session_id
        feed.path = dashboard.ROOT / ".local" / "offline-scoped-tail"
        feed.source_policy, feed.deadline = "automatic-bounded", self.clock.mono() + 10
        feed.identity = IDENTITY["exe_name"].lower(), IDENTITY["process_id"], IDENTITY["hwnd"].lower()
        data = b"".join((json.dumps({"service_instance_id": instance, "source_policy": "automatic-bounded",
                                    "activity_state": "active", **record}) + "\n").encode() for record in records)
        filename = Mock()
        filename.exists.return_value = True
        filename.stat.return_value.st_size = len(data)
        filename.open.side_effect = lambda *_: io.BytesIO(data)
        with patch.object(dashboard.manual_capture, "public_snapshot", return_value=current), \
                patch.object(dashboard.manual_capture, "private_path", return_value=filename), \
                patch.object(dashboard.manual_capture, "fail_session"), \
                patch.object(dashboard.manual_capture, "stop_session"):
            feed.poll()
            feed.poll()
        return feed

    def test_independent_stack_pot_and_card_slots_survive_unknown_role_or_one_bad_card(self):
        board = self.record()["board_slots"]
        board[1] = {"rank": [], "suit": "clubs"}
        value = self.reading(board_slots=board, role="your_turn", hero_seated=True,
                             action_required=True, available_actions=["call"], quality_approved=True)
        self.assertEqual(value["role"], "uncertain")
        self.assertEqual(value["pot_size"], 12345)
        self.assertEqual([s["displayed_stack"] for s in value["seats"]], [100, 200, None, 0, 500, 600])
        self.assertEqual(value["board_slots"][0], {"rank": "A", "suit": "hearts"})
        self.assertIsNone(value["board_slots"][1])
        self.assertIsNotNone(value["board_slots"][2])
        self.assertFalse(value["quality_approved"])
        snapshot = self.state.snapshot()
        self.assertIsNone(snapshot["observation"])
        self.assertIsNone(snapshot["advice"])
        self.assertFalse(snapshot["server"]["advice_ready"])

    def test_automatic_verifying_source_health_and_status_preserve_readout_without_history(self):
        self.state.begin_stream()
        self.health(source_policy="automatic-bounded", activity_state="verifying", reason="activity-verifying")
        source = self.record(source_policy="automatic-bounded", activity_state="verifying",
                             hero_seated=True, role="your_turn", action_required=True)
        self.state.ingest(source)
        before = self.state.snapshot()
        self.assertEqual(before["partial_observation"]["pot_size"], 12345)
        self.assertEqual(before["partial_observation"]["role"], "uncertain")
        self.assertIsNone(before["partial_observation"]["hero_seated"])
        deadline = self.state.partial_deadline
        for event in ("observation", "table", "history", "decision", "recommendation"):
            self.state.ingest({**source, "event": event, "hero_cards": [], "board": [], "game_phase": "preflop",
                               "summary": {"counts": {"folds": 1}, "events": [{"event": "action"}]}})
            self.assertEqual(self.state.snapshot()["partial_observation"], before["partial_observation"])
        self.state.ingest({"schema_version": 2, "event": "status", "state": "verifying",
                           "source_policy": "automatic-bounded", "activity_state": "verifying"})
        self.health(2, source_policy="automatic-bounded", activity_state="verifying", reason="activity-verifying")
        snapshot = self.state.snapshot()
        self.assertEqual(snapshot["partial_observation"], before["partial_observation"])
        self.assertEqual(self.state.partial_deadline, deadline)
        self.assertTrue(snapshot["capture"]["fresh_capture"])
        self.assertIsNone(snapshot["observation"])
        self.assertIsNone(snapshot["advice"])
        self.assertEqual(snapshot["history"]["state"], "unavailable")
        self.assertEqual(snapshot["history"]["events"], [])
        self.assertEqual(snapshot["history"]["gaps"], 0)

    def test_automatic_verifying_invalidations_clear_readout_without_history_gaps(self):
        for scoped in (False, True):
            with self.subTest(scoped=scoped):
                self.state.begin_stream()
                self.health(2, source_policy="automatic-bounded", activity_state="verifying")
                source = self.record(2, source_policy="automatic-bounded", activity_state="verifying")
                self.state.ingest(source)
                event = self.scoped_invalidation(source) if scoped else {
                    "schema_version": 2, "event": "observation_invalidated", "generation": 2,
                    "epoch": 1, "reason": "frame-changed"}
                self.state.ingest({**event, "source_policy": "automatic-bounded", "activity_state": "verifying"})
                snapshot = self.state.snapshot()
                self.assertIsNone(snapshot["partial_observation"])
                self.assertEqual(snapshot["history"]["state"], "unavailable")
                self.assertEqual(snapshot["history"]["gaps"], 0)
                self.state.ingest(source)
                self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_explicit_unseated_role_needs_both_verified_families(self):
        value = self.reading(role="observing", hero_seated=False)
        self.assertEqual(value["role"], "observing")
        self.state.begin_stream()
        self.health()
        value = self.reading(role="observing", hero_seated=False, verified_fields=["role", "pot_size"])
        self.assertEqual(value["role"], "uncertain")
        self.assertIsNone(value["hero_seated"])
        self.assertEqual(value["pot_size"], 12345)

    def test_complete_same_ticket_cannot_refill_a_withheld_partial_amount(self):
        source = self.record(pot_size=None)
        self.state.ingest(source)
        strict = {**source, "event": "observation", "pot_size": 99999, "hero_cards": [],
                  "board": [{"rank": "A", "suit": "hearts"}, {"rank": "K", "suit": "clubs"},
                            {"rank": "2", "suit": "spades"}],
                  "hero_seated": False, "action_required": False, "role": "observing",
                  "verified_fields": ["pot_size", "hero_seated", "action_required"]}
        self.state.ingest(strict)
        snapshot = self.state.snapshot()
        self.assertIsNone(snapshot["partial_observation"]["pot_size"])
        self.assertEqual(snapshot["partial_observation"]["seats"][0]["displayed_stack"], 100)
        self.assertIsNone(snapshot["observation"])
        self.assertIsNone(snapshot["advice"])

    def test_native_full_sibling_or_relabelled_partial_cannot_acquire_advice(self):
        self.state.set_model("ready", calibrated=True, floors_loaded=True)
        source = self.record(pot_size=None)
        self.state.ingest(source)
        for generation in (1, 2):
            full = native_observation(self.clock, generation=generation, quality_approved=True)
            full["observation"]["captured_at_ms"] = source["observation"]["captured_at_ms"]
            self.health(generation)
            self.state.ingest(full)
            self.state.ingest(native_decision(full, quality_approved=True))
            value = self.state.snapshot()
            self.assertIsNone(value["advice"])
            self.assertIsNone(value["observation"])
            self.assertIsNone(value["partial_observation"]["pot_size"])
            self.assertFalse(value["server"]["advice_ready"])

    def test_new_partial_bundle_replaces_full_analysis_without_carrying_metrics(self):
        self.state.set_model("ready")
        full = native_observation(self.clock)
        self.state.ingest(full)
        self.state.ingest(native_decision(full))
        self.assertIsNotNone(self.state.snapshot()["advice"])
        self.clock.value += .1
        self.health(2)
        self.state.ingest(self.record(2, quality_approved=True))
        self.state.ingest(native_decision(full))
        value = self.state.snapshot()
        self.assertEqual(value["partial_observation"]["pot_size"], 12345)
        self.assertIsNone(value["observation"])
        self.assertIsNone(value["advice"])
        self.assertFalse(value["partial_observation"]["quality_approved"])

    def test_automatic_receipt_downgrade_withholds_decisions_and_snapshot_stays_pure(self):
        self.state.set_model("ready")
        full = native_observation(self.clock)
        self.state.ingest(full)
        self.state.ingest(native_decision(full))
        feed = dashboard.ManualSessionFeed(self.state, "b" * 32)
        current = {"source_policy": "automatic-bounded", "activity_state": "verifying", "status": "capturing"}
        with patch.object(dashboard.manual_capture, "public_snapshot", return_value=current), \
                patch.object(dashboard.manual_capture, "stop_session", side_effect=AssertionError("GET stopped capture")), \
                patch.object(dashboard.manual_capture, "fail_session", side_effect=AssertionError("GET changed runtime")):
            value = feed.snapshot()
        self.assertIsNone(value["advice"])
        self.assertIsNone(value["observation"])
        self.assertFalse(value["server"]["advice_ready"])
        self.assertFalse(self.state.analysis_inputs)
        self.state.ingest(native_decision(full))
        self.assertIsNone(self.state.snapshot()["advice"])

    def test_untrained_asserted_seat_values_and_names_never_enter_public_or_sanitized_ledger(self):
        source = self.record()
        for seat in source["seats"]:
            seat.update({field: 999 for field in dashboard.SEAT_FIELDS if field != "displayed_stack"})
            seat.update(name="PRIVATE-NAME", position="btn", badge="raise", acting=True)
        source.update(raw_response="PRIVATE-RAW", prompt="PRIVATE-PROMPT", pixels="PRIVATE-PIXELS")
        self.state.ingest(source)
        value = self.state.snapshot()
        for seat in value["partial_observation"]["seats"]:
            self.assertTrue(all(seat[field] is None for field in dashboard.SEAT_FIELDS if field != "displayed_stack"))
        text = json.dumps(value)
        for private in ("PRIVATE", "verified_fields", "capabilities", '"acceptance_floor"', "process_id", "hwnd"):
            self.assertNotIn(private, text)

    def test_capability_metadata_is_not_a_generic_permission_to_run_new_fields_or_lower_floors(self):
        cases = [{"training": "unsupported"}, {"acceptance_floor": .79}, {"acceptance_floor": True},
                 {"acceptance_floor": float("nan")}, {"acceptance_floor": 10 ** 1000},
                 {"human_verified": True}, {"held_out_approved": True}, {"provenance": "PRIVATE"}]
        for extra in cases:
            with self.subTest(extra=extra):
                self.state.begin_stream()
                self.health()
                caps = self.record()["capabilities"]
                caps[5].update(extra)
                value = self.reading(capabilities=caps)
                self.assertIsNone(value["pot_size"])
                self.assertEqual(value["seats"][0]["displayed_stack"], 100)
        self.state.begin_stream()
        self.health()
        caps = self.record()["capabilities"]
        caps.append(capability("pot_size"))
        self.assertIsNone(self.reading(capabilities=caps)["pot_size"])

    def test_missing_or_malformed_verified_capabilities_fail_closed(self):
        for extra in ({"verified_fields": "pot_size"}, {"verified_fields": ["visible_wager"]},
                      {"capabilities": None}, {"capabilities": []}, {"capabilities": [{}] * 97}):
            self.state.begin_stream()
            self.health()
            value = self.reading(**extra)
            self.assertIsNone(value["pot_size"])
            self.assertEqual(value["board_slots"], [None] * 5)
            self.assertTrue(all(s["displayed_stack"] is None for s in value["seats"]))

    def test_physical_slot_mapping_is_explicit_not_vector_order_and_duplicates_cannot_shift_it(self):
        seats = list(reversed(self.record()["seats"]))
        value = self.reading(seats=seats)
        self.assertEqual([s["seat"] for s in value["seats"]], list(range(1, 7)))
        self.assertEqual([s["displayed_stack"] for s in value["seats"]], [100, 200, None, 0, 500, 600])
        for invalid in (seats[:-1], [seats[0]] * 6, ["PRIVATE"] * 6,
                        [{**seat, "seat": True} for seat in seats]):
            self.state.begin_stream()
            self.health()
            value = self.reading(seats=invalid)
            self.assertTrue(all(s["displayed_stack"] is None for s in value["seats"]))
            self.assertEqual(value["pot_size"], 12345)

    def test_six_qualified_wagers_are_distinct_from_stacks_and_never_street_contributions(self):
        source = self.record()
        for seat in source["seats"]:
            seat["visible_wager"] = seat["seat"] * 7
            seat["visible_wager_text"] = "0.%02d" % (seat["seat"] * 7)
            seat["street_contribution"] = 999
        for item in source["capabilities"]:
            if item["field"] == "visible_wager":
                item.update(training="read_only_approved", acceptance_floor=.999,
                            held_out_approved=True, human_verified=True,
                            provenance="observation-only-calibrated-pass")
        self.state.ingest(source)
        view = self.state.snapshot()["partial_observation"]
        self.assertEqual([s["visible_wager"] for s in view["seats"]], [7, 14, 21, 28, 35, 42])
        self.assertEqual([s["visible_wager_text"] for s in view["seats"]], ["0.07", "0.14", "0.21", "0.28", "0.35", "0.42"])
        self.assertEqual(view["field_statuses"]["wagers"]["status"], "accepted")
        self.assertEqual([s["displayed_stack"] for s in view["seats"]], [100, 200, None, 0, 500, 600])
        self.assertTrue(all(s["street_contribution"] is None for s in view["seats"]))
        self.assertFalse(view["quality_approved"])
        self.assertIsNone(self.state.snapshot()["advice"])
        for bad in ({"acceptance_floor": None}, {"acceptance_floor": 0},
                    {"acceptance_floor": 10**1000}, {"acceptance_floor": True},
                    {"human_verified": False}, {"held_out_approved": False},
                    {"training": "trained_unapproved"}, {"provenance": "it1-existing-pass"}):
            self.state.begin_stream()
            self.health()
            invalid = copy.deepcopy(source)
            for item in invalid["capabilities"]:
                if item["field"] == "visible_wager" and item["seat"] == 1:
                    item.update(bad)
            value = self.reading(**{k: invalid[k] for k in ("seats", "capabilities")})
            self.assertIsNone(value["seats"][0]["visible_wager"])
            self.assertEqual(value["seats"][1]["visible_wager"], 14)
            self.assertEqual(value["seats"][0]["displayed_stack"], 100)

    def test_scene_readings_require_individual_qualified_families_and_do_not_create_positions(self):
        source = self.record()
        for seat in source["seats"]:
            seat.update(occupied=True, status="active", badge="none", dealer=seat["seat"] == 4,
                        small_blind=seat["seat"] == 5, big_blind=seat["seat"] == 6,
                        acting=seat["seat"] == 1, position="BTN", position_group="late")
        for item in source["capabilities"]:
            if item["field"] in dashboard.SCENE_LABELS:
                item.update(training="read_only_approved", acceptance_floor=.999,
                            held_out_approved=True, human_verified=True,
                            provenance="observation-only-calibrated-pass")
        self.state.ingest(source)
        view = self.state.snapshot()["partial_observation"]
        self.assertTrue(view["seats"][0]["acting"])
        self.assertTrue(view["seats"][3]["dealer"])
        self.assertEqual(view["seats"][0]["badge"], "none")
        self.assertIn("acting", view["seats"][0]["scene_fields"])
        self.assertTrue(all(s["position"] is None and s["position_group"] is None for s in view["seats"]))
        self.assertIsNone(self.state.snapshot()["advice"])
        self.state.begin_stream()
        self.health()
        source["seats"][1]["acting"] = True
        self.state.ingest(source)
        self.assertTrue(all(s["acting"] is None for s in self.state.snapshot()["partial_observation"]["seats"]))
        self.assertEqual(self.state.snapshot()["partial_observation"]["pot_size"], 12345)

    def test_invalid_amounts_are_unknown_not_zero(self):
        for amount in (None, True, -1, "100", 100.0, float("inf"), 0x100000000):
            self.state.begin_stream()
            self.health()
            seats = self.record()["seats"]
            seats[0]["displayed_stack"] = amount
            value = self.reading(pot_size=amount, seats=seats)
            self.assertIsNone(value["pot_size"])
            self.assertIsNone(value["seats"][0]["displayed_stack"])
            self.assertEqual(value["seats"][3]["displayed_stack"], 0)

    def test_duplicate_cards_and_contradictory_board_context_clear_only_dependent_fields(self):
        board = self.record()["board_slots"]
        board[1] = board[0]
        value = self.reading(board_slots=board)
        self.assertEqual(value["board_slots"][:2], [None, None])
        self.assertIsNotNone(value["board_slots"][2])
        self.state.begin_stream()
        self.health()
        value = self.reading(game_phase="preflop")
        self.assertIsNone(value["game_phase"])
        self.assertEqual(value["board_count"], 3)
        self.assertIsNotNone(value["board_slots"][0])
        self.assertIsNotNone(value["board_slots"][2])
        self.assertEqual(value["pot_size"], 12345)
        self.state.begin_stream()
        self.health()
        value = self.reading(game_phase="preflop", board_count=None)
        self.assertIsNone(value["game_phase"])
        self.assertIsNotNone(value["board_slots"][0])
        self.assertEqual(value["pot_size"], 12345)

    def test_new_capture_replaces_unknowns_without_cross_hand_or_occupant_transfer(self):
        self.reading()
        self.clock.value += .2
        self.health(2)
        value = self.reading(generation=2, game_phase=None, board_count=None, board_slots=[None] * 5,
                             pot_size=None, seats=[{"seat": n, "occupant_epoch": n + 100} for n in range(1, 7)])
        self.assertIsNone(value["pot_size"])
        self.assertEqual(value["board_slots"], [None] * 5)
        self.assertTrue(all(s["displayed_stack"] is None and s["occupant_epoch"] is None for s in value["seats"]))

    def test_advice_clear_and_older_discard_do_not_blank_current_independent_fields(self):
        before = self.reading(generation=2)
        self.state.ingest({"schema_version": 2, "event": "clear", "generation": 2, "reason": "action-not-required"})
        self.assertEqual(self.state.snapshot()["partial_observation"], before)
        self.assertIsNone(self.state.snapshot()["advice"])
        self.state.ingest({"schema_version": 2, "event": "decision", "action": "call", "quality_approved": True})
        self.assertEqual(self.state.snapshot()["partial_observation"], before)
        self.assertIsNone(self.state.snapshot()["advice"])
        self.state.ingest({"schema_version": 2, "event": "discarded", "generation": 1,
                           "reason": "obsolete-observation"})
        self.assertEqual(self.state.snapshot()["partial_observation"], before)
        self.state.ingest({"schema_version": 2, "event": "observation_invalidated", "generation": 2,
                           "epoch": 1, "reason": "frame-changed"})
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.assertIsNone(self.reading(generation=2))

    def test_duplicates_polls_and_new_generation_cannot_renew_original_capture_age(self):
        source = self.record()
        self.state.ingest(source)
        self.clock.value += .5
        self.state.ingest(source)
        self.assertLessEqual(self.state.snapshot()["partial_observation"]["remaining_ms"], 500)
        newer = copy.deepcopy(source)
        newer["observation"]["generation"] = 2
        newer.update(emitted_at_unix_ms=int(self.clock.wall() * 1000), valid_for_ms=2000,
                     expires_at_unix_ms=int(self.clock.wall() * 1000) + 2000)
        self.state.ingest(newer)
        self.assertLessEqual(self.state.snapshot()["partial_observation"]["remaining_ms"], 500)
        self.clock.value += .501
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.state.ingest(newer)
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_scoped_invalidation_keeps_newer_health_eligible_and_replays_inert(self):
        for recorded_utc in (False, True):
            with self.subTest(recorded_utc=recorded_utc):
                self.state.begin_stream()
                self.health(2)
                old = self.record(2, verified_fields=["pot_size"])
                if recorded_utc:
                    old["observation"]["captured_at_unix_ms"] = old["captured_at_unix_ms"]
                self.state.ingest(old)
                original_source = self.state.partial_source, self.state.partial_source_deadline
                self.clock.value += .1
                self.health(3)
                health = self.state.snapshot()["capture"]
                invalidation = self.scoped_invalidation(old)
                self.state.ingest(invalidation)
                cleared = self.state.snapshot()
                self.assertIsNone(cleared["partial_observation"])
                self.assertEqual(cleared["capture"], health)
                self.assertEqual(self.state.version, (3, 1))
                self.assertEqual(self.state.invalidated_version, (2, 1))
                self.assertEqual((self.state.partial_source, self.state.partial_source_deadline), original_source)
                self.assertEqual(cleared["field_statuses"]["pot_size"], {"status": "unavailable", "reason": "stale"})
                for replay in (old, invalidation):
                    self.state.ingest(replay)
                self.assertIsNone(self.state.snapshot()["partial_observation"])
                self.assertEqual(self.state.invalidated_version, (2, 1))

                new = self.record(3, verified_fields=["seats.2.displayed_stack"])
                if recorded_utc:
                    new["observation"]["captured_at_unix_ms"] = new["captured_at_unix_ms"]
                self.state.ingest(new)
                before = self.state.snapshot()
                reading = before["partial_observation"]
                self.assertEqual((reading["generation"], reading["epoch"]), (3, 1))
                self.assertEqual(reading["seats"][1]["displayed_stack"], 200)
                self.assertIsNone(reading["pot_size"], "a newer bundle must not refill old Pot")
                self.assertEqual(reading["expires_at_unix_ms"], new["expires_at_unix_ms"])
                self.assertIsNone(before["observation"])
                self.assertIsNone(before["advice"])
                for replay in (invalidation, old, invalidation):
                    self.state.ingest(replay)
                    after = self.state.snapshot()
                    after["event_seq"] = before["event_seq"]
                    self.assertEqual(after, before)
                    self.assertEqual(self.state.version, (3, 1))
                    self.assertEqual(self.state.invalidated_version, (2, 1))

    def test_scoped_invalidation_requires_exact_published_ticket_and_metadata(self):
        self.health(2)
        source = self.record(2)
        source["observation"]["captured_at_unix_ms"] = source["captured_at_unix_ms"]
        self.state.ingest(source)
        valid = self.scoped_invalidation(source, fields=["seats.1.displayed_stack"])
        ticket = valid["observation"]
        foreign = {**IDENTITY, "hwnd": "0x2"}
        cases = [{key: value} for key, values in (
            ("schema_version", (None, 1, 2.0, "2")), ("generation", (None, True, 1, 3)),
            ("epoch", (None, True, 0, 2)), ("reason", (None, [], "frame-changed")),
            ("observation", (None, [], {})), ("identity", (None, [], foreign)),
            ("captured_at_unix_ms", (None, True, source["captured_at_unix_ms"] + 1)),
            ("emitted_at_unix_ms", (None, True, valid["emitted_at_unix_ms"] + 1,
                                    source["captured_at_unix_ms"] - 1)),
            ("valid_for_ms", (None, 1000)), ("expires_at_unix_ms", (None, valid["emitted_at_unix_ms"] + 1000)),
            ("fields", (None, [], True, 1, "pot_size", {}, [None], [[]], [{}], [True],
                        ["pot_size", "pot_size"], ["pot_size", "unknown"], ["seats.0.displayed_stack"],
                        ["seats.7.displayed_stack"], ["seats.1.street_contribution"], ["board_slots.0"],
                        ["board_slots.6"], ["pot_size"] * (len(dashboard.PARTIAL_FIELDS) + 1))))
            for value in values]
        cases += [{"observation": {**ticket, key: value}} for key, values in (
            ("generation", (True, 3)), ("epoch", (True, 2)),
            ("captured_at_ms", (None, True, -1, 1003)),
            ("captured_at_unix_ms", (None, True, source["captured_at_unix_ms"] + 1)),
            ("identity", (None, foreign, {**IDENTITY, "process_id": 43}, {**IDENTITY, "exe_name": "other.exe"})))
            for value in values]
        cases += [{"observation": {key: value for key, value in ticket.items() if key != "captured_at_unix_ms"}},
                  {"identity": foreign, "observation": {**ticket, "identity": foreign}}]
        records = [{**valid, **extra} for extra in cases]
        records += [{key: value for key, value in valid.items() if key != missing}
                    for missing in ("schema_version", "observation", "generation", "epoch", "identity",
                                    "reason", "captured_at_unix_ms", "emitted_at_unix_ms")]
        before = self.state.snapshot()
        boundary = self.state.version, self.state.invalidated_version, self.state.status_deadline
        for record in records:
            with self.subTest(record=record):
                self.state.ingest(record)
                after = self.state.snapshot()
                after["event_seq"] = before["event_seq"]
                self.assertEqual(after, before)
                self.assertEqual((self.state.version, self.state.invalidated_version, self.state.status_deadline), boundary)
                self.assertIsNone(self.state.invalidated_partial_ticket)

    def test_scoped_invalidation_cannot_clear_full_or_diagnostic_only_state(self):
        source = self.record()
        self.diagnostics([dict(field="pot_size", status="rejected", reason="below-floor")])
        invalidation = self.scoped_invalidation(source)
        before = self.state.snapshot()["field_statuses"]
        deadline = self.state.status_deadline
        self.state.ingest(invalidation)
        self.assertEqual(self.state.snapshot()["field_statuses"], before)
        self.assertEqual(self.state.status_deadline, deadline)
        self.state.ingest({**source, "event": "observation", "game_phase": "preflop",
                           "hero_cards": [], "board": [], "verified_fields": ["pot_size"]})
        before = self.state.snapshot()["observation"]
        self.assertIsNotNone(before)
        self.state.ingest(invalidation)
        self.assertEqual(self.state.snapshot()["observation"], before)
        self.assertIsNone(self.state.invalidated_partial_ticket)

    def test_field_invalidation_without_replacement_keeps_pot_and_original_clocks(self):
        source = self.record(2, pot_size_text="123.45")
        source["observation"]["captured_at_unix_ms"] = source["captured_at_unix_ms"]
        source["seats"][0]["displayed_stack_text"] = "1.00"
        self.state.ingest(source)
        self.clock.value += .2
        self.health(3)
        before = self.state.snapshot()
        clocks = (self.state.partial_ticket, self.state.partial_source, self.state.partial_deadline,
                  self.state.partial_source_deadline, self.state.status_source,
                  self.state.status_deadline, self.state.status_expires)
        boundary = self.state.version, self.state.invalidated_version
        invalidation = self.scoped_invalidation(source, fields=["seats.1.displayed_stack"])
        self.state.ingest(invalidation)
        after = self.state.snapshot()
        expected = copy.deepcopy(before["partial_observation"])
        expected["seats"][0].update(displayed_stack=None, displayed_stack_text=None)
        expected["field_statuses"]["seats.1.displayed_stack"] = {"status": "unavailable", "reason": "stale"}
        self.assertEqual(after["partial_observation"], expected)
        self.assertEqual(after["field_statuses"], expected["field_statuses"])
        self.assertEqual(after["capture"], before["capture"])
        self.assertEqual((self.state.version, self.state.invalidated_version), boundary)
        self.assertEqual((self.state.partial_ticket, self.state.partial_source, self.state.partial_deadline,
                          self.state.partial_source_deadline, self.state.status_source,
                          self.state.status_deadline, self.state.status_expires), clocks)
        self.assertEqual(expected["pot_size"], 12345)
        self.assertEqual(expected["role"], "uncertain")
        # Replayed/relabelled values and diagnostics cannot refill or renew the same source.
        for generation in (2, 3, 4):
            replay = copy.deepcopy(source)
            replay["observation"]["generation"] = generation
            replay.update(valid_for_ms=3000, expires_at_unix_ms=int(self.clock.wall() * 1000) + 3000)
            for event in ("partial_observation", "observation", "perception_diagnostics"):
                self.state.ingest({**replay, "event": event, "game_phase": "preflop", "hero_cards": [], "board": [],
                                   "frame_width": 800, "frame_height": 613, "passes": [],
                                   "fields": [dict(field="displayed_stack", seat=1, status="rejected", reason="below-floor")],
                                   "source_current": True, "admission": "source_current"})
                self.assertEqual(self.state.snapshot()["partial_observation"], expected)
                self.assertEqual(self.state.status_expires, clocks[-1])
        gaps = self.state.history["gaps"]
        self.state.ingest(invalidation)
        self.assertEqual(self.state.history["gaps"], gaps)
        self.clock.value += .801
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.state.ingest(source)
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_field_invalidation_clears_empty_board_and_role_without_erasing_numbers(self):
        source = self.record(2, board_count=0, board_slots=[None] * 5, game_phase="preflop",
                             role="observing", hero_seated=False)
        self.state.ingest(source)
        before = self.state.snapshot()["partial_observation"]
        self.assertEqual(before["field_statuses"]["board"]["status"], "accepted")
        fields = ["board_count", "game_phase", "role", "hero_seated"]
        self.state.ingest(self.scoped_invalidation(source, fields=fields))
        view = self.state.snapshot()["partial_observation"]
        self.assertIsNone(view["board_count"])
        self.assertIsNone(view["game_phase"])
        self.assertEqual(view["role"], "uncertain")
        self.assertIsNone(view["hero_seated"])
        self.assertEqual(view["pot_size"], before["pot_size"])
        self.assertEqual(view["seats"], before["seats"])
        for field in [*fields, "board"]:
            self.assertEqual(view["field_statuses"][field], {"status": "unavailable", "reason": "stale"})
        self.assertEqual(view["captured_at_unix_ms"], before["captured_at_unix_ms"])
        self.assertEqual(view["expires_at_unix_ms"], before["expires_at_unix_ms"])
        # New lane publication is still full replacement, never accumulation.
        self.clock.value += .1
        self.health(3)
        new = self.reading(generation=3, verified_fields=["seats.2.displayed_stack"])
        self.assertEqual(new["seats"][1]["displayed_stack"], 200)
        self.assertIsNone(new["pot_size"])
        self.assertIsNone(new["seats"][0]["displayed_stack"])
        self.state.ingest(self.scoped_invalidation(source, fields=["pot_size"]))
        self.assertEqual(self.state.snapshot()["partial_observation"], new)

    def test_field_invalidation_verifying_projection_ignores_hidden_native_role_not_changed_stack(self):
        envelope = {"source_policy": "automatic-bounded", "activity_state": "verifying"}
        source = self.record(2, role="observing", hero_seated=False, **envelope)
        self.state.ingest(source)
        before = self.state.snapshot()["partial_observation"]
        self.assertEqual(before["role"], "uncertain")
        gaps = self.state.history["gaps"]
        self.state.ingest(self.scoped_invalidation(source, fields=["role", "hero_seated", "game_phase",
                                                                  "seats.1.displayed_stack"], **envelope))
        view = self.state.snapshot()["partial_observation"]
        self.assertIsNone(view["seats"][0]["displayed_stack"])
        self.assertEqual(view["field_statuses"]["seats.1.displayed_stack"]["reason"], "stale")
        self.assertEqual(view["pot_size"], before["pot_size"])
        self.assertEqual(view["expires_at_unix_ms"], before["expires_at_unix_ms"])
        self.assertEqual(view["field_statuses"]["role"], before["field_statuses"]["role"])
        self.assertEqual(self.state.history["gaps"], gaps)

    def test_field_invalidation_preserves_five_second_cap_despite_newer_health(self):
        now = int(self.clock.wall() * 1000)
        source = self.record(2, valid_for_ms=4500, expires_at_unix_ms=now + 4500)
        self.state.ingest(source)
        self.clock.value += .5
        self.health(3)
        self.state.ingest(self.scoped_invalidation(source, fields=["seats.1.displayed_stack"]))
        deadline = self.state.partial_deadline
        for advance in (2, 1.998):
            self.clock.value += advance
            self.health(4)
            self.assertEqual(self.state.snapshot()["partial_observation"]["pot_size"], 12345)
            self.assertEqual(self.state.partial_deadline, deadline)
        self.clock.value += .003
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_field_invalidation_updates_only_supported_card_wager_and_scene_fields(self):
        source = self.record()
        source["board_slots"][1] = {"rank": "king", "suit": "clubs"}
        source["seats"][0].update(visible_wager=125, visible_wager_text="1.25", occupied=True, badge="check")
        for item in source["capabilities"]:
            if item["field"] in ("visible_wager", "occupied", "badge") and item["seat"] == 1:
                item.update(training="read_only_approved", acceptance_floor=.999,
                            held_out_approved=True, human_verified=True, provenance="observation-only-calibrated-pass")
        self.state.ingest(source)
        self.state.ingest(self.scoped_invalidation(source, fields=["board_slots.2", "board_count", "game_phase",
                                                                  "seats.1.visible_wager", "seats.1.badge",
                                                                  "seats.2.visible_wager"]))
        view = self.state.snapshot()["partial_observation"]
        self.assertIsNone(view["board_slots"][1])
        self.assertIsNotNone(view["board_slots"][0])
        self.assertIsNotNone(view["board_slots"][2])
        self.assertIsNone(view["seats"][0]["visible_wager"])
        self.assertIsNone(view["seats"][0]["visible_wager_text"])
        self.assertEqual(view["seats"][0]["visible_wager_status"], "unknown")
        self.assertEqual(view["seats"][0]["scene_fields"], ["occupied"])
        self.assertEqual(view["field_statuses"]["scene"]["status"], "accepted")
        for field in ("board", "board_slots.2", "board_count", "game_phase", "seats.1.visible_wager", "seats.1.badge", "wagers"):
            self.assertEqual(view["field_statuses"][field], {"status": "unavailable", "reason": "stale"})
        self.assertEqual(view["field_statuses"]["seats.2.visible_wager"]["reason"], "missing-capability")
        self.state.ingest(self.scoped_invalidation(source, fields=["seats.1.occupied"]))
        self.assertEqual(self.state.snapshot()["field_statuses"]["scene"], {"status": "unavailable", "reason": "stale"})
        self.assertEqual(self.state.snapshot()["partial_observation"]["pot_size"], 12345)

    def test_field_invalidation_with_no_survivors_fully_invalidates_original_ticket(self):
        source = self.record(2, verified_fields=["pot_size"])
        self.state.ingest(source)
        self.health(3)
        self.state.ingest(self.scoped_invalidation(source, fields=["pot_size"]))
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.assertEqual(self.state.version, (3, 1))
        self.assertEqual(self.state.invalidated_version, (2, 1))
        self.state.ingest(source)
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_field_invalidation_refuses_expired_packet_even_before_snapshot(self):
        for clock in ("wall", "monotonic"):
            with self.subTest(clock=clock):
                self.state.begin_stream()
                self.health()
                source = self.record()
                self.state.ingest(source)
                invalidation = self.scoped_invalidation(source, fields=["seats.1.displayed_stack"])
                deadline = self.state.partial_deadline
                now = getattr(self.state, clock)()
                with patch.object(self.state, clock, return_value=now + 1.001):
                    self.state.ingest(invalidation)
                    self.assertIsNone(self.state.invalidated_partial_ticket)
                    self.assertEqual(self.state.partial_deadline, deadline)
                    self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_partial_expiry_does_not_tombstone_independently_fresh_next_lane(self):
        for poll_first in (False, True):
            with self.subTest(poll_first=poll_first):
                self.state.begin_stream()
                self.health(2)
                old = self.record(2, verified_fields=["pot_size"])
                self.state.ingest(old)
                self.clock.value += .5
                self.health(3)
                new = self.record(3, board_count=0, board_slots=[None] * 5, verified_fields=["board_count"])
                self.clock.value += .501
                if poll_first:
                    self.assertIsNone(self.state.snapshot()["partial_observation"])
                expired = self.scoped_invalidation(old, reason="observation-expired")
                self.state.ingest(expired)
                self.assertEqual(self.state.invalidated_version, (2, 1))
                self.assertEqual(self.state.version, (3, 1))
                self.assertIsNone(self.state.snapshot()["partial_observation"])
                self.state.ingest(new)
                view = self.state.snapshot()["partial_observation"]
                self.assertEqual(view["board_count"], 0)
                self.assertIsNone(view["pot_size"])
                self.assertEqual(view["captured_at_unix_ms"], new["captured_at_unix_ms"])
                self.assertEqual(view["expires_at_unix_ms"], new["expires_at_unix_ms"])
                self.assertLessEqual(view["remaining_ms"], 500)
                self.state.ingest(expired)
                self.assertEqual(self.state.snapshot()["partial_observation"], view)
                self.clock.value += .5
                self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_partial_expiry_event_cannot_erase_unexpired_or_mismatched_packet(self):
        source = self.record()
        self.state.ingest(source)
        before = self.state.snapshot()["partial_observation"]
        for extra in ({}, {"fields": ["pot_size"]}):
            self.state.ingest(self.scoped_invalidation(source, reason="observation-expired", **extra))
            self.assertEqual(self.state.snapshot()["partial_observation"], before)
            self.assertIsNone(self.state.invalidated_partial_ticket)

    def test_scoped_invalidation_blocks_relabelled_capture_and_complete_sibling(self):
        self.health(2)
        source = self.record(2)
        self.state.ingest(source)
        self.health(3)
        self.state.ingest(self.scoped_invalidation(source))
        boundary = self.state.invalidated_version
        status_source = self.state.status_source, self.state.status_deadline
        for generation in (2, 3, 4):
            replay = copy.deepcopy(source)
            replay["observation"]["generation"] = generation
            for event in ("partial_observation", "observation", "perception_diagnostics"):
                self.state.ingest({**replay, "event": event, "game_phase": "preflop", "hero_cards": [], "board": [],
                                   "frame_width": 800, "frame_height": 613, "passes": [],
                                   "fields": [dict(field="pot_size", status="rejected", reason="below-floor")],
                                   "source_current": True, "admission": "source_current"})
                snapshot = self.state.snapshot()
                self.assertIsNone(snapshot["partial_observation"])
                self.assertIsNone(snapshot["observation"])
                self.assertEqual(snapshot["field_statuses"]["pot_size"]["reason"], "stale")
                self.assertEqual(self.state.invalidated_version, boundary)
                self.assertEqual(self.state.version, (3, 1))
                self.assertEqual((self.state.status_source, self.state.status_deadline), status_source)

    def test_global_invalidation_still_vetoes_current_health_after_scoped_clear(self):
        for generation in (2, 3):
            with self.subTest(global_generation=generation):
                self.state.begin_stream()
                self.health(2)
                old = self.record(2)
                self.state.ingest(old)
                self.health(3)
                invalidation = self.scoped_invalidation(old)
                self.state.ingest(invalidation)
                self.state.ingest({"schema_version": 2, "event": "observation_invalidated",
                                   "generation": generation, "epoch": 1, "reason": "frame-changed"})
                self.state.ingest(invalidation)
                self.assertEqual(self.state.invalidated_version, (3, 1))
                self.assertIsNone(self.reading(generation=3))
                self.health(4)
                self.assertIsNotNone(self.reading(generation=4))

    def test_scoped_invalidation_preserves_new_result_original_source_expiry(self):
        self.health(2)
        old = self.record(2)
        self.state.ingest(old)
        new = self.record(3)
        new["observation"]["captured_at_unix_ms"] = new["captured_at_unix_ms"]
        self.clock.value += .4
        self.health(3)
        self.state.ingest(self.scoped_invalidation(old))
        self.state.ingest(new)
        reading = self.state.snapshot()["partial_observation"]
        self.assertEqual(reading["captured_at_unix_ms"], new["captured_at_unix_ms"])
        self.assertEqual(reading["expires_at_unix_ms"], new["expires_at_unix_ms"])
        self.assertLessEqual(reading["remaining_ms"], 600)
        deadline = self.state.partial_source_deadline
        self.clock.value += .5
        rewritten = copy.deepcopy(new)
        rewritten.update(emitted_at_unix_ms=int(self.clock.wall() * 1000), valid_for_ms=3000,
                         expires_at_unix_ms=int(self.clock.wall() * 1000) + 3000)
        self.state.ingest(self.scoped_invalidation(old))
        self.state.ingest(rewritten)
        self.assertEqual(self.state.partial_source_deadline, deadline)
        self.assertEqual(self.state.snapshot()["partial_observation"]["expires_at_unix_ms"], new["expires_at_unix_ms"])
        self.clock.value += .101
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.state.ingest(rewritten)
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_scoped_invalidation_does_not_rearm_expired_or_retired_session(self):
        self.health(2)
        source = self.record(2)
        self.state.ingest(source)
        self.clock.value += 1.001
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        deadline = self.state.partial_source_deadline
        tombstone = self.state.invalidated_partial_ticket
        invalidation = self.scoped_invalidation(source)
        self.state.ingest(invalidation)
        self.assertEqual(self.state.partial_source_deadline, deadline)
        self.assertEqual(self.state.invalidated_partial_ticket, tombstone)
        session = self.state.session_id
        self.state.end_stream()
        self.state.ingest(invalidation, session_id=session)
        self.state.ingest(source, session_id=session)
        self.assertEqual(self.state.snapshot()["capture"]["state"], "disconnected")
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.state.begin_stream()
        self.health(2)
        self.reading(generation=2)
        before = self.state.snapshot()
        self.state.ingest(invalidation, session_id=session)
        self.assertEqual(self.state.snapshot(), before)

    def test_scoped_invalidation_private_ledger_is_sanitized_without_public_ticket(self):
        with tempfile.TemporaryDirectory(dir=dashboard.ROOT / ".local") as directory:
            path = Path(directory) / "ledger.jsonl"
            self.state.begin_stream(path)
            self.health(2)
            source = self.record(2)
            source["observation"]["captured_at_unix_ms"] = source["captured_at_unix_ms"]
            self.state.ingest(source)
            keys = self.state.snapshot().keys()
            self.health(3)
            event = self.scoped_invalidation(source, raw_response="PRIVATE-RAW", pixels="PRIVATE-PIXELS",
                                             field_statuses={"pot_size": {"status": "accepted", "reason": None}},
                                             pot_size=999, quality_approved=True, advice={"action": "call"})
            self.state.ingest(event)
            snapshot = self.state.snapshot()
            self.state.end_stream()
            text = path.read_text()
            saved = [json.loads(line) for line in text.splitlines()
                     if json.loads(line)["event"] == "partial_observation_invalidated"]
            self.assertEqual(len(saved), 1)
            record = saved[0]
            self.assertEqual(record["reason"], "source-region-changed")
            self.assertEqual((record["generation"], record["epoch"]), (2, 1))
            self.assertEqual(record["captured_at_ms"], source["observation"]["captured_at_ms"])
            self.assertEqual(record["captured_at_unix_ms"], source["captured_at_unix_ms"])
            self.assertEqual(record["emitted_at_unix_ms"], event["emitted_at_unix_ms"])
            self.assertEqual(record["target_id"], self.state.target)
            self.assertEqual(set(record), {"event", "sequence", "recorded_utc", "reason", "generation", "epoch",
                                           "captured_at_ms", "captured_at_unix_ms", "emitted_at_unix_ms", "target_id"})
            self.assertEqual(snapshot.keys(), keys)
            self.assertIsNone(snapshot["partial_observation"])
            self.assertIsNone(snapshot["observation"])
            self.assertIsNone(snapshot["advice"])
            self.assertTrue(all(status["status"] == "unavailable" for status in snapshot["field_statuses"].values()))
            for private in ("PRIVATE", "exe_name", "process_id", "hwnd", "partial_ticket", "captured_at_ms"):
                self.assertNotIn(private, json.dumps(snapshot))
            for private in ("PRIVATE", "exe_name", "process_id", "hwnd", "raw_response", "pixels"):
                self.assertNotIn(private, text)

    def test_partial_original_ticket_utc_must_agree_with_lease_source(self):
        for value in (None, True, -1, int(self.clock.wall() * 1000), "original"):
            with self.subTest(value=value):
                self.state.begin_stream()
                self.health()
                source = self.record()
                source["observation"]["captured_at_unix_ms"] = value
                self.state.ingest(source)
                self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_scoped_tail_refuses_foreign_or_malformed_targets_without_ending_stream(self):
        self.health(2)
        source = self.record(2)
        self.state.ingest(source)
        self.health(3)
        invalidation = self.scoped_invalidation(source)
        foreign = copy.deepcopy(invalidation)
        foreign["observation"]["identity"]["hwnd"] = "0x2"
        before = self.state.snapshot()
        feed = self.manual_tail([foreign, {**invalidation, "observation": ["malformed"]}])
        self.assertFalse(feed.failed)
        self.assertEqual(feed.stream_id, self.state.session_id)
        self.assertEqual(self.state.snapshot()["partial_observation"], before["partial_observation"])
        self.assertEqual(self.state.snapshot()["capture"], before["capture"])
        feed = self.manual_tail([invalidation, self.record(3), invalidation])
        self.assertFalse(feed.failed)
        self.assertEqual(self.state.snapshot()["partial_observation"]["generation"], 3)
        self.assertEqual(self.state.invalidated_version, (2, 1))

    def test_scoped_tail_keeps_session_envelope_and_value_source_fail_closed(self):
        for fault in ("instance", "policy", "foreign-values", "terminal", "deadline", "frame-cap"):
            with self.subTest(fault=fault):
                self.state.begin_stream()
                self.health(2)
                source = self.record(2)
                self.state.ingest(source)
                self.health(3)
                record, current = self.scoped_invalidation(source), {}
                if fault == "instance":
                    record["service_instance_id"] = "c" * 32
                elif fault == "policy":
                    record["source_policy"] = "manual"
                elif fault == "foreign-values":
                    record = self.record(3)
                    record["observation"]["identity"] = {**IDENTITY, "hwnd": "0x2"}
                elif fault == "terminal":
                    current["status"] = "stopped"
                elif fault == "deadline":
                    current["remaining_ms"] = 0
                else:
                    current["recorded_frames"] = 100
                feed = self.manual_tail([record, self.record(3)], **current)
                self.assertIsNone(feed.stream_id)
                self.assertIsNone(self.state.snapshot()["partial_observation"])
                self.assertIsNone(self.state.snapshot()["observation"])
                self.assertFalse(self.state.snapshot()["capture"]["fresh_capture"])

    def test_bad_source_identity_order_or_age_clears_and_cannot_be_reactivated_by_old_source(self):
        now = int(self.clock.wall() * 1000)
        cases = [{"valid_for_ms": 5001}, {"expires_at_unix_ms": now + 5000},
                 {"captured_at_unix_ms": now + 1}, {"emitted_at_unix_ms": now + 1},
                 {"expires_at_unix_ms": now},
                 {"observation": {"identity": {**IDENTITY, "hwnd": "0x2"}, "generation": 1,
                                  "epoch": 1, "captured_at_ms": 1001}}]
        for extra in cases:
            self.state.begin_stream()
            self.health()
            self.reading()
            self.state.ingest(self.record(**extra))
            self.assertIsNone(self.state.snapshot()["partial_observation"])
            self.reading()
            self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.state.begin_stream()
        self.health()
        self.reading()
        self.clock.value += .2
        self.state.ingest(self.record(2, captured_at_unix_ms=now - 1000))
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_heartbeat_resize_identity_change_invalidation_eof_and_old_session_are_fail_closed(self):
        self.reading()
        self.state.ingest({"schema_version": 2, "event": "observation_invalidated", "generation": 1,
                           "epoch": 1, "reason": "frame-changed"})
        self.assertIsNone(self.reading())
        self.health(2, 2)
        self.assertIsNotNone(self.reading(generation=2, epoch=2))
        self.clock.value += 2.6
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        old_session = self.state.session_id
        self.state.end_stream()
        self.state.begin_stream()
        self.health()
        self.reading()
        sequence = self.state.event_seq
        dashboard.drain_feed(io.BytesIO((json.dumps(self.record(99)) + "\n").encode()), self.state,
                             session_id=old_session)
        self.assertEqual(self.state.event_seq, sequence)
        self.assertIsNotNone(self.state.snapshot()["partial_observation"])
        self.assertEqual(self.state.snapshot()["capture"]["state"], "active")

    def test_duplicate_health_uses_original_emission_age_and_resize_clears_without_history_reset(self):
        now = int(self.clock.wall() * 1000)
        self.reading(valid_for_ms=4000, expires_at_unix_ms=now + 4000)
        self.clock.value += .8
        self.health(emitted_at_unix_ms=now, captured_at_unix_ms=now)
        self.assertEqual(self.state.snapshot()["capture"]["last_heartbeat_unix_ms"], now)
        self.clock.value += 1.701
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.state.begin_stream()
        self.health()
        self.reading()
        self.state.history["gaps"] = 7
        session = self.state.session_id
        self.health(2, frame_width=900, frame_height=686)
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.assertEqual(self.state.history["gaps"], 7)
        self.assertEqual(self.state.session_id, session)
        self.assertIsNotNone(self.reading(generation=2))

    def test_private_diagnostics_are_closed_bounded_and_never_browser_data(self):
        with tempfile.TemporaryDirectory(dir=dashboard.ROOT / ".local") as directory:
            path = Path(directory) / "ledger.jsonl"
            self.state.begin_stream(path)
            self.state.diagnostics.max_events = 2
            self.health()
            self.reading()
            source = self.record(event="perception_diagnostics", frame_width=800, frame_height=613,
                                 passes=[{"pass": "p0_full", "crop_bounds": [[0, 0, 800, 613]],
                                          "crop_dimensions": [[800, 613]], "total_ms": 12.5,
                                          "questions": [{"question": "screen_kind", "answer": {"type": "choice", "value": "poker_table"},
                                                         "score": .999, "effective_floor": .995, "status": "accepted", "reason": "accepted"},
                                                        {"question": "game_phase", "answer": {"type": "choice", "value": "PRIVATE-NAME"},
                                                         "reason": "PRIVATE-PROMPT"},
                                                        {"question": "PRIVATE-QUESTION", "answer": "PRIVATE-RAW"}]}],
                                 fields=[{"field": "pot_size", "status": "accepted", "reason": "accepted",
                                          "admission_status": "unknown", "admission_reason": "awaiting-consensus"}],
                                 timing={"inference_ms": 10.5, "render_ms": None, "prompt": "PRIVATE"},
                                 raw_response="PRIVATE-RAW", names=["PRIVATE-NAME"], pixels="PRIVATE-PIXELS")
            for _ in range(3):
                self.state.ingest(source)
            self.assertEqual(self.state.diagnostics.count, 2)
            self.assertFalse(self.state.diagnostics.complete)
            self.state.end_stream()
            private = path.with_name("perception.jsonl").read_text()
            saved = json.loads(private.splitlines()[0])["diagnostics"]
            self.assertEqual(saved["passes"][0]["questions"][0]["score"], .999)
            self.assertIsNone(saved["passes"][0]["questions"][1]["answer"])
            self.assertEqual(saved["passes"][0]["crop_dimensions"], [[800, 613]])
            self.assertEqual(saved["fields"][0]["status"], "accepted")
            self.assertEqual(saved["fields"][0]["admission_status"], "unknown")
            self.assertEqual(saved["fields"][0]["admission_reason"], "awaiting-consensus")
            self.assertIsNone(saved["timing"]["render_ms"])
            self.assertNotIn("PRIVATE", private)
            for text in (json.dumps(self.state.snapshot()), path.read_text()):
                for key in ("questions", "crop_bounds", "inference_ms", "raw_response", "PRIVATE", "score"):
                    self.assertNotIn(key, text)

    def test_stale_or_unsafe_private_diagnostics_do_not_clear_read_only_fields(self):
        self.reading()
        self.state.ingest(self.record(event="perception_diagnostics", expires_at_unix_ms=1))
        self.state.ingest(self.record(event="perception_diagnostics", passes="PRIVATE"))
        self.assertIsNotNone(self.state.snapshot()["partial_observation"])
        self.assertFalse(self.state.diagnostics.complete)

    def test_private_overflow_keeps_actual_segment_count_not_an_invented_eight(self):
        value = dashboard.private_perception({"frame_width": 800, "frame_height": 613,
                                             "passes": [{"pass": "p3_pot", "crop_bounds": [],
                                                         "crop_dimensions": [], "questions": [],
                                                         "segments": {"n": 12, "overflow": True}}]})
        self.assertEqual(value["passes"][0]["segments"], {"n": 12, "overflow": True})

    def test_obsolete_zero_lease_diagnostics_are_private_history_not_source_admission(self):
        with tempfile.TemporaryDirectory(dir=dashboard.ROOT / ".local") as directory:
            path = Path(directory) / "ledger.jsonl"
            self.state.begin_stream(path)
            self.health(2, 2)
            self.reading(generation=2, epoch=2)
            before = self.state.snapshot()["partial_observation"]
            self.state.ingest(self.record(1, 1, event="perception_diagnostics", valid_for_ms=0,
                                         expires_at_unix_ms=int(self.clock.wall() * 1000),
                                         frame_width=800, frame_height=613, passes=[], fields=[], timing={},
                                         source_current=False, admission="obsolete_observation"))
            self.assertEqual(self.state.snapshot()["partial_observation"], before)
            self.assertEqual(self.state.version, (2, 2))
            self.assertEqual(self.state.diagnostics.count, 1)
            self.state.end_stream()
            record = json.loads(path.with_name("perception.jsonl").read_text())
            self.assertEqual(record["valid_for_ms"], 0)
            self.assertFalse(record["diagnostics"]["source_current"])
            self.assertEqual(record["diagnostics"]["admission"], "obsolete_observation")
            self.assertNotIn("source_current", json.dumps(self.state.snapshot()))

    def test_reference_preserves_root_education_and_matches_bundled_asset(self):
        reference = dashboard.references()
        app = (dashboard.ROOT / "scripts/dashboard/app.js").read_text(encoding="utf-8")
        bundled = json.loads(re.search(r"const LOCAL_REFERENCE = (.*?);\s*/\* END BUNDLED REFERENCE", app, re.S).group(1))
        self.assertEqual(reference, bundled)
        sections = {item["id"]: item for item in reference["sections"]}
        self.assertTrue({"hand-rankings", "pot-odds", "outs-and-draws", "opening-examples", "facing-raises"} <= sections.keys())
        positions = sections["six-max-positions"]
        self.assertEqual(positions["tables"][0]["rows"][0], ["UTG / LJ", "Early", 1, 3])
        self.assertEqual(len(positions["tables"][1]["rows"]), 9)
        self.assertIn("reference only", positions["tables"][1]["caption"])
        self.assertIn("dead-button", " ".join(positions["bullets"]))

    def diagnostics(self, fields, **extra):
        self.state.ingest(self.record(event="perception_diagnostics", frame_width=800, frame_height=613,
                                     passes=[], fields=fields, source_current=True, admission="source_current", **extra))

    def test_literal_text_is_preserved_only_for_verified_matching_numeric_amounts(self):
        source = self.record(pot_size=123450, pot_size_text="1,234.5")
        source["seats"][0].update(displayed_stack=700, displayed_stack_text="0007")
        source["seats"][3]["displayed_stack_text"] = "0"
        view = dashboard.partial_view(source)
        self.assertEqual(view["pot_size_text"], "1,234.5")
        self.assertEqual(view["seats"][0]["displayed_stack_text"], "0007")
        self.assertEqual(view["seats"][3]["displayed_stack_text"], "0")
        for text in ("$1,234.5", "1234.50 chips", "1,234.6", "1e3", "1,23.45", "PRIVATE", "1" * 1000, "\uff11\uff12\uff13\uff14.\uff15", [], None):
            source["pot_size_text"] = text
            with self.subTest(text=text):
                value = dashboard.partial_view(source)
                self.assertIsNone(value["pot_size_text"])
                self.assertEqual(value["pot_size"], 123450)
        source["verified_fields"] = []
        self.assertIsNone(dashboard.partial_view(source)["seats"][0]["displayed_stack_text"])

    def test_field_reasons_are_closed_source_bound_and_never_admit_a_value(self):
        self.reading(pot_size=None, board_count=None, game_phase=None, board_slots=[None] * 5)
        fields = [dict(field="pot_size", status="rejected", reason="below-floor",
                       admission_status="rejected", admission_reason="below-floor"),
                  dict(field="board_slot", board_slot=1, status="rejected", reason="occluded",
                       admission_status="rejected", admission_reason="occluded"),
                  dict(field="displayed_stack", seat=3, status="accepted", reason="accepted",
                       admission_status="unknown", admission_reason="awaiting-consensus"),
                  dict(field="visible_wager", seat=1, status="unknown", reason="unsupported"),
                  dict(field="displayed_stack", seat=2, status="rejected", reason="source-region-changed",
                       admission_status="rejected", admission_reason="source-region-changed"),
                  dict(field="PRIVATE-FIELD", status="accepted", reason="PRIVATE"),
                  dict(field="hero_seated", status="unknown", reason="PRIVATE")]
        self.diagnostics(fields)
        snapshot = self.state.snapshot()
        statuses = snapshot["partial_observation"]["field_statuses"]
        self.assertEqual(snapshot["field_statuses"], statuses)
        self.assertEqual(statuses["pot_size"], {"status": "unavailable", "reason": "below-floor"})
        self.assertEqual(statuses["board_slots.1"]["reason"], "occluded")
        self.assertEqual(statuses["board"]["reason"], "occluded")
        self.assertEqual(statuses["seats.3.displayed_stack"]["reason"], "insufficient-context")
        self.assertEqual(statuses["seats.1.visible_wager"]["reason"], "missing-capability")
        self.assertEqual(statuses["scene"]["reason"], "missing-capability")
        self.assertEqual(statuses["seats.2.displayed_stack"], {"status": "accepted", "reason": None})
        self.assertEqual(statuses["hero_cards"]["reason"], "missing-capability")
        self.assertEqual(statuses["center_chip"]["reason"], "missing-capability")
        self.assertEqual(statuses["pot_convention"]["reason"], "insufficient-context")
        self.assertTrue(all(v["reason"] in (*dashboard.UNAVAILABLE_REASONS, None) for v in statuses.values()))
        self.assertIsNone(snapshot["partial_observation"]["pot_size"])
        self.assertNotIn("PRIVATE", json.dumps(snapshot))
        self.assertNotIn("admission_reason", json.dumps(snapshot))

    def test_unavailable_diagnostic_reasons_work_without_a_partial_and_expire_original_lease(self):
        self.diagnostics([dict(field="table_layout", status="rejected", reason="unsupported")])
        before = self.state.snapshot()
        self.assertIsNone(before["partial_observation"])
        self.assertEqual(before["field_statuses"]["pot_size"]["reason"], "unsupported-layout")
        self.assertTrue(all(v["status"] == "unavailable" for v in before["field_statuses"].values()))
        original = self.record(event="perception_diagnostics", frame_width=800, frame_height=613,
                               passes=[], fields=[], source_current=True, admission="source_current")
        self.clock.value += .8
        self.state.ingest(original)
        self.clock.value += .201
        self.assertEqual(self.state.snapshot()["field_statuses"]["pot_size"]["reason"], "stale")

    def test_old_candidate_unmatched_or_expired_diagnostics_cannot_rewrite_current_statuses(self):
        self.reading(pot_size=None)
        before = copy.deepcopy(self.state.snapshot())
        fields = [dict(field="pot_size", status="rejected", reason="below-floor")]
        cases = [dict(source_current=False), dict(admission="candidate"), dict(generation=2), dict(captured_mono=1002),
                 dict(captured_at_unix_ms=int(self.clock.wall() * 1000) - 501), dict(valid_for_ms=0)]
        for extra in cases:
            raw = self.record(event="perception_diagnostics", frame_width=800, frame_height=613,
                              passes=[], fields=fields, source_current=True, admission="source_current")
            if "generation" in extra:
                raw["observation"]["generation"] = extra["generation"]
            elif "captured_mono" in extra:
                raw["observation"]["captured_at_ms"] = extra["captured_mono"]
            else:
                raw.update(extra)
            self.state.ingest(raw)
            self.assertEqual(self.state.snapshot()["field_statuses"], before["field_statuses"])
        self.state.end_stream()
        self.diagnostics(fields)
        self.assertEqual(self.state.snapshot()["field_statuses"]["pot_size"]["reason"], "stale")

    def test_new_generation_diagnostics_cannot_renew_same_source_or_revive_after_expiry(self):
        fields = [dict(field="pot_size", status="rejected", reason="below-floor")]
        raw = self.record(event="perception_diagnostics", frame_width=800, frame_height=613,
                          passes=[], fields=fields, source_current=True, admission="source_current")
        self.state.ingest(raw)
        self.clock.value += .8
        later = copy.deepcopy(raw)
        later["observation"]["generation"] = 2
        later.update(emitted_at_unix_ms=int(self.clock.wall() * 1000), valid_for_ms=2000,
                     expires_at_unix_ms=int(self.clock.wall() * 1000) + 2000)
        self.state.ingest(later)
        self.clock.value += .201
        self.assertEqual(self.state.snapshot()["field_statuses"]["pot_size"]["reason"], "stale")
        self.state.ingest(later)
        self.assertEqual(self.state.snapshot()["field_statuses"]["pot_size"]["reason"], "stale")

    def test_p7_closed_diagnostic_vocabulary_does_not_discard_valid_scene_trace(self):
        value = dashboard.private_perception({"frame_width": 800, "frame_height": 613,
                    "passes": [{"pass": "p7_seat_1_scene", "crop_bounds": [], "crop_dimensions": [],
                                "questions": [{"question": "occupied", "answer": {"type": "choice", "value": "open"},
                                               "reason": "explicit-unknown", "status": "unknown"}]}]})
        question = value["passes"][0]["questions"][0]
        self.assertEqual(question["answer"], {"type": "choice", "value": "open"})
        self.assertEqual(question["reason"], "explicit-unknown")


NODE_UI = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8')), source = fs.readFileSync(input.app, 'utf8');
const html = fs.readFileSync(input.html, 'utf8');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.childNodes = []; this.dataset = {}; this.attrs = {}; this.hidden = false;
    this.value = ''; this.listeners = {}; this.classes = new Set(); this._text = ''; this.mutations = 0;
    this.classList = { toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name),
      add: (name) => this.classes.add(name), contains: (name) => this.classes.has(name) }; }
  set className(value) { this.classes = new Set(value.split(/\s+/)); } get className() { return [...this.classes].join(' '); }
  set textContent(value) { this.mutations += 1; this._text = String(value); this.childNodes = []; }
  get textContent() { return this._text + this.childNodes.map(x => x.textContent).join(''); }
  append(...items) { for (const item of items) item.tagName === '#fragment' ? this.append(...item.childNodes) : this.childNodes.push(item); }
  replaceChildren(...items) { this._text = ''; this.childNodes = []; this.append(...items); }
  setAttribute(name, value) { this.attrs[name] = String(value); } getAttribute(name) { return this.attrs[name]; }
  addEventListener(name, callback) { this.listeners[name] = callback; } focus() { document.activeElement = this; }
}
const nodes = new Map();
for (const match of html.matchAll(/<([a-z0-9]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
  const item = new Element(match[1]); item.id = match[3]; item.hidden = /\bhidden\b/.test(match[2]);
  for (const attr of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) item.setAttribute(attr[1], attr[2]);
  item.className = item.attrs.class || ''; nodes.set(item.id, item);
}
nodes.get('history-filter').value = 'all';
let wall = input.snapshot.capture.last_heartbeat_unix_ms, mono = 0, timer = 0;
class MockDate extends Date { static now() { return wall; } }
const document = { hidden: false, getElementById: id => { assert(nodes.has(id), `missing DOM id ${id}`); return nodes.get(id); },
  querySelectorAll: () => [...nodes.values()].filter(x => x.attrs.role === 'tab'),
  createElement: tag => new Element(tag), createDocumentFragment: () => new Element('#fragment'),
  activeElement: null, listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; } };
const window = { setTimeout: () => ++timer, clearTimeout() {}, setInterval() {}, addEventListener() {} };
const context = { document, window, Date: MockDate, performance: { now: () => mono }, Intl, URL, TextDecoder,
  AbortController, fetch: () => { throw Error('offline test: no network'); } };
vm.createContext(context);
vm.runInContext(source.replace(/\}\)\(\);\s*$/, 'globalThis.test = { normalizeSnapshot, acceptSnapshot, refreshClocks, suspend, resume, loadReference }; })();'), context);
const test = context.test, value = x => test.normalizeSnapshot(x);
const accept = raw => { const normalized = value(raw); assert(normalized); test.acceptSnapshot(normalized, 0); };
const newer = (gen, seq) => { const raw = structuredClone(input.snapshot); raw.event_seq = seq;
  raw.capture.last_heartbeat_unix_ms = wall; const obs = raw.partial_observation || raw.observation;
  obs.generation = gen; obs.captured_at_unix_ms = wall - 500; obs.expires_at_unix_ms = wall + 1000; return raw; };
const visible = () => nodes.get('monitor-readings').dataset.reading !== 'unknown';
accept(input.snapshot);
if (input.scenario === 'render') {
  assert(visible()); assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
  const seats = nodes.get('seat-readings').childNodes;
  assert.equal(seats.length, 6); assert.deepEqual(seats.map(s => s.dataset.seat), ['1','2','3','4','5','6']);
   for (const row of seats) for (const label of ['Stack', 'Wager']) assert(row.textContent.includes(label));
  assert(seats[3].textContent.includes('0.00 chips')); assert(!seats[2].textContent.includes('0.00 chips'));
  assert.equal(nodes.get('board-cards').childNodes.length, 5);
  assert(!nodes.get('monitor-readings').hidden);
  assert(nodes.get('metrics-readings').hidden); assert(nodes.get('controls-reading').hidden);
   assert(nodes.get('call-reading').hidden); assert(nodes.get('reading-limit').textContent.toLowerCase().includes('untrained'));
  assert(![...nodes.values()].some(node => node.textContent.includes('PRIVATE') || node.textContent.includes('999999.99 chips')));
  assert.equal([...nodes.values()].filter(x => x.attrs.role === 'tab').length, 2);
  test.loadReference(); assert.equal(nodes.get('reference-sections').childNodes.length, 8);
} else if (input.scenario === 'expiry') {
  mono = 500; wall += 500; accept(input.snapshot); assert(visible());
  mono = 1001; wall += 501; test.refreshClocks(); assert(!visible());
  const replay = newer(1, input.snapshot.event_seq + 10); accept(replay); assert(!visible());
  accept(newer(2, input.snapshot.event_seq + 11)); assert(visible());
} else if (input.scenario === 'lifecycle') {
  document.hidden = true; test.suspend(); assert(!visible()); document.hidden = false; test.resume();
  accept(newer(1, input.snapshot.event_seq + 1)); assert(!visible());
  accept(newer(2, input.snapshot.event_seq + 2)); assert(visible());
  accept(newer(3, input.snapshot.event_seq)); assert(!visible());
  accept(newer(4, input.snapshot.event_seq + 4)); assert(visible());
  const replacement = newer(1, 1); replacement.session_id = 'new-session'; accept(replacement); assert(!visible());
  replacement.event_seq = 2; replacement.partial_observation.generation = 2; accept(replacement); assert(visible());
  accept(input.snapshot); assert(!visible());
} else if (input.scenario === 'actor') {
  assert(visible()); assert.equal(nodes.get('call-label').textContent, 'Acting seat 3 to call');
  assert.equal(nodes.get('amount-call').textContent, '0.50 chips'); assert(nodes.get('metrics-readings').hidden);
  assert(!nodes.get('call-reading').hidden);
} else if (input.scenario === 'empty') {
  assert(!visible()); assert.equal(nodes.get('monitor-empty').textContent, 'Reading uncertain');
  assert(!nodes.get('monitor-readings').hidden); assert.equal(nodes.get('seat-readings').childNodes.length, 6);
  assert(nodes.get('seat-readings').childNodes.every(row => row.textContent.includes('Seat status pending')));
} else if (input.scenario === 'capture-rewrite') {
  const rewritten = structuredClone(input.snapshot); rewritten.event_seq += 1;
  rewritten.partial_observation.captured_at_unix_ms += 1; accept(rewritten); assert(!visible());
} else if (input.scenario === 'field-invalidation') {
  mono = 200; wall += 200; accept(input.next_snapshot); assert(visible());
  assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
  assert.equal(nodes.get('amount-pot').dataset.reading, 'current');
  const stack = nodes.get('seat-readings').childNodes[0].childNodes[1].childNodes[0].childNodes[1];
  assert.equal(stack.dataset.reading, 'unknown');
  assert.equal(value(input.next_snapshot).observation.seats[0].displayed_stack, null);
  mono = 1001; wall += 801; test.refreshClocks(); assert(!visible());
}
console.log(`offline UI ${input.scenario}: PASS`);
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline static UI tests")
class StaticUiTests(unittest.TestCase):
    def setUp(self):
        fixture = PartialTests()
        fixture.setUp()
        fixture.reading()
        self.snapshot = fixture.state.snapshot()

    def run_ui(self, scenario, snapshot=None, next_snapshot=None):
        payload = {"scenario": scenario, "snapshot": snapshot or self.snapshot,
                   "next_snapshot": next_snapshot,
                   "app": str(dashboard.ROOT / "scripts/dashboard/app.js"),
                   "html": str(dashboard.ROOT / "scripts/dashboard/index.html")}
        result = subprocess.run(["node", "-e", NODE_UI], input=json.dumps(payload), text=True, encoding="utf-8",
                                capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_static_partial_render_retains_unknowns_seat_mapping_and_offline_reference(self):
        self.run_ui("render")

    def test_asserted_partial_wagers_badges_metrics_or_names_do_not_gain_browser_trust(self):
        raw = copy.deepcopy(self.snapshot)
        for seat in raw["partial_observation"]["seats"]:
            seat.update(visible_wager=99999999, street_contribution=99999999, badge="raise", name="PRIVATE")
        raw["partial_observation"].update(role="your_turn", acting_seat=3, action_required=True,
                                          metrics={"hand_rank": "PRIVATE", "equity_pct": 100})
        self.run_ui("render", raw)

    def test_duplicate_polls_cannot_renew_and_expired_source_cannot_revive(self):
        self.run_ui("expiry")

    def test_disconnect_hide_reveal_out_of_order_and_retired_sessions_clear(self):
        self.run_ui("lifecycle")

    def test_same_ticket_cannot_rewrite_its_original_capture_time(self):
        self.run_ui("capture-rewrite")

    def test_same_ticket_field_removal_reaches_browser_without_renewing_pot(self):
        fixture = PartialTests()
        fixture.setUp()
        source = fixture.record()
        fixture.state.ingest(source)
        before = fixture.state.snapshot()
        fixture.clock.value += .2
        fixture.state.ingest(fixture.scoped_invalidation(source, fields=["seats.1.displayed_stack"]))
        self.run_ui("field-invalidation", before, fixture.state.snapshot())

    def test_all_unknown_partial_is_compact_not_a_wall_of_fake_values(self):
        raw = copy.deepcopy(self.snapshot)
        raw["partial_observation"].update(game_phase=None, board_count=None, board_slots=[None] * 5, pot_size=None,
                                          seats=[{"seat": n, "displayed_stack": None} for n in range(1, 7)])
        self.run_ui("empty", raw)

    def test_observing_call_label_names_actor_and_metrics_remain_disabled(self):
        raw = copy.deepcopy(self.snapshot)
        raw["partial_observation"] = None
        raw["observation"] = {"generation": 1, "epoch": 1, "captured_at_unix_ms": raw["capture"]["last_heartbeat_unix_ms"] - 500,
                              "expires_at_unix_ms": raw["capture"]["last_heartbeat_unix_ms"] + 1000, "remaining_ms": 1000,
                              "role": "observing", "hero_seated": False, "action_required": False, "acting_seat": 3,
                              "hero_cards": [], "board": [], "game_phase": "preflop", "controls": [], "wagers": [],
                              "amounts": {"pot_size": 12345, "acting_to_call": 50, "to_call": 999},
                              "metrics": {"hand_rank": "PRIVATE", "equity_pct": 100}, "experimental": True}
        self.run_ui("actor", raw)


if __name__ == "__main__":
    unittest.main()
