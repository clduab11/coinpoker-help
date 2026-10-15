import concurrent.futures
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dashboard_server", SCRIPTS / "laya-server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
dashboard = server.dashboard


class Clock:
    def __init__(self):
        self.value = 100.0

    def mono(self):
        return self.value

    def wall(self):
        return 1_800_000_000.0 + self.value


IDENTITY = {"process_id": 42, "hwnd": "0x100000001", "exe_name": "PRIVATE-NAME.exe"}


def native_observation(clock, generation=1, epoch=1, **extra):
    """Full ObservationView + leased_record envelope, not a partial capability grant."""
    now = int(clock.wall() * 1000)
    controls = dashboard.unknown_controls()
    for control in controls:
        if control["action"] in ("fold", "call", "raise"):
            control.update(presence="present", enabled="enabled")
    return {"schema_version": 2, "event": "observation",
            "observation": {"identity": IDENTITY, "generation": generation, "epoch": epoch,
                            "captured_at_ms": 1000 + generation, "captured_at_unix_ms": now - 500},
            "emitted_at_unix_ms": now, "captured_at_unix_ms": now - 500,
            "expires_at_unix_ms": now + 1000, "valid_for_ms": 1000,
            "game_phase": "flop", "hero_cards": [{"rank": "A", "suit": "hearts"}, {"rank": "K", "suit": "hearts"}],
            "board": [{"rank": "Q", "suit": "hearts"}, {"rank": "7", "suit": "clubs"}, {"rank": "2", "suit": "hearts"}],
            "pot_size": 150, "to_call": 50, "hero_chips": 1000, "min_raise_to": 100, "max_raise_to": 1000,
            "role": "your_turn", "hero_seated": True, "action_required": True,
            "available_actions": ["fold", "call", "raise"], "controls": controls,
            "acting_seat": None, "acting_to_call": None, "wagers": [],
            "metrics": dict.fromkeys(dashboard.METRIC_FIELDS),
            "verified_fields": ["pot_size", "hero_seated", "action_required", "hero_chips", "controls", "to_call",
                                "min_raise_to", "max_raise_to"], "quality_approved": False, **extra}


def native_decision(source, **extra):
    return {key: copy.deepcopy(source[key]) for key in ("schema_version", "observation", "captured_at_unix_ms",
            "emitted_at_unix_ms", "expires_at_unix_ms", "valid_for_ms")} | {
                "event": "decision", "action": "call", "amount": 50, "ev": 70.0, "equity": .6,
                "pot_odds": .25, "break_even": .25, "opponent": "unknown", "confidence": None, **extra}


class StateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.state = dashboard.DashboardState("coinpoker-laya-vision", monotonic=self.clock.mono, wall=self.clock.wall)
        self.state.begin_stream()

    def health(self, generation=1, epoch=1, **extra):
        now = int(self.clock.wall() * 1000)
        record = {"schema_version": 2, "event": "capture_health", "generation": generation,
                  "epoch": epoch, "identity": IDENTITY, "fresh_capture": True, "frame_count": 7,
                  "emitted_at_unix_ms": now, "captured_at_unix_ms": now,
                  "frame_width": 800, "frame_height": 613, **extra}
        self.state.ingest(record)

    def observation(self, generation=1, epoch=1, **extra):
        now = int(self.clock.wall() * 1000)
        record = {"schema_version": 2, "event": "observation",
                  "observation": {"identity": IDENTITY, "generation": generation, "epoch": epoch,
                                  "captured_at_ms": 123 + generation},
                  "emitted_at_unix_ms": now, "captured_at_unix_ms": now - 500,
                  "expires_at_unix_ms": now + 1000, "valid_for_ms": 1000,
                   "game_phase": "flop", "hero_cards": [],
                   "board": [{"rank": "ace", "suit": "hearts"}, {"rank": "king", "suit": "clubs"},
                             {"rank": "two", "suit": "spades"}], "pot_size": 150,
                   "role": "uncertain", "verified_fields": ["pot_size"], **extra}
        self.state.ingest(record)

    def reading(self, role="observing", **extra):
        controls = dashboard.unknown_controls()
        turn = role == "your_turn"
        if turn:
            for item in controls:
                if item["action"] in ("fold", "call", "raise"):
                    item.update(presence="present", enabled="enabled")
        return {"role": role, "hero_seated": False if role == "observing" else True,
                "action_required": turn, "controls": controls,
                "hero_cards": [{"rank": "T", "suit": "spades"}, {"rank": "9", "suit": "diamonds"}] if turn else [],
                "to_call": 50 if turn else None, "hero_chips": 1000 if turn else None,
                "min_raise_to": 100 if turn else None, "max_raise_to": 1000 if turn else None,
                "verified_fields": ["pot_size", "hero_seated", "action_required", "controls", "to_call",
                                    "hero_chips", "min_raise_to", "max_raise_to"], **extra}

    def test_unapproved_observation_is_experimental_without_placeholder_amounts(self):
        self.health()
        self.observation(to_call=0, hero_chips=0, available_actions=["fold", "call"], quality_approved=True)
        value = self.state.snapshot()
        self.assertEqual(value["observation"]["board"][0]["rank"], "A")
        self.assertTrue(value["observation"]["experimental"])
        self.assertIsNone(value["observation"]["amounts"]["to_call"])
        self.assertIsNone(value["observation"]["available_actions"])
        self.assertTrue(all(c["presence"] == c["enabled"] == "unknown" for c in value["observation"]["controls"]))
        self.assertIsNone(value["advice"])
        self.assertFalse(value["server"]["advice_ready"])
        self.assertEqual(value["observation"]["role"], "uncertain")
        self.assertIsNone(value["observation"]["hero_seated"])
        self.assertIsNone(value["observation"]["action_required"])
        self.assertFalse(value["observation"]["quality_approved"])
        self.assertEqual(value["server"]["quality_gate"], "failed")

    def test_explicit_roles_change_without_erasing_observing_history(self):
        self.state.ingest({"schema_version": 2, "event": "history", "summary": {
            "counts": {"folds": 1, "checks": 0, "calls": 0, "bets": 1, "raises": 2},
            "events": [{"event": "action", "street": "preflop", "event_sequence": 1,
                        "action": {"seat": 2, "kind": "raise", "amount": 100, "all_in": False,
                                   "trusted": True, "full_raise": True, "preflop_raise_ordinal": 3}}]}})
        prefix = self.state.snapshot()["history"]
        session = self.state.session_id
        for generation, role in enumerate(("observing", "seated_waiting", "your_turn", "observing"), 1):
            self.health(generation)
            self.observation(generation, **self.reading(role))
            value = self.state.snapshot()
            self.assertEqual(value["observation"]["role"], role)
            self.assertEqual(value["history"], prefix)
            self.assertEqual(value["session_id"], session)
            self.assertIsNone(value["advice"])
            self.assertFalse(value["server"]["advice_ready"])
        self.state.end_stream()
        self.assertEqual(self.state.snapshot()["history"]["events"], prefix["events"])
        self.state.begin_stream()
        self.assertNotEqual(self.state.session_id, session)
        self.assertEqual(self.state.snapshot()["history"]["events"], [])

    def test_empty_cards_or_an_asserted_role_do_not_establish_seating(self):
        for extra in ({}, {"role": "observing"}, {"role": "your_turn", "action_required": True},
                      {"role": "seated_waiting", "hero_seated": True, "action_required": False},
                      {"role": "observing", "hero_seated": False, "action_required": False,
                       "verified_fields": "hero_seated"}):
            with self.subTest(extra=extra):
                self.state.begin_stream()
                self.health()
                self.observation(**extra)
                reading = self.state.snapshot()["observation"]
                self.assertEqual(reading["role"], "uncertain")
                self.assertIsNone(reading["hero_seated"])
                self.assertIsNone(reading["action_required"])
                self.assertIsNone(reading["available_actions"])

    def test_seated_folded_waiting_and_unknown_turn_are_distinct_from_observing(self):
        for required, expected in ((False, "seated_waiting"), (None, "uncertain"), (True, "uncertain")):
            self.state.begin_stream()
            self.health()
            self.observation(**self.reading(expected, hero_seated=True, action_required=required, hero_chips=1000))
            reading = self.state.snapshot()["observation"]
            self.assertEqual(reading["role"], expected)
            self.assertTrue(reading["hero_seated"])
            self.assertEqual(reading["hero_cards"], [])
            self.assertIsNone(reading["available_actions"])
            self.assertIsNone(reading["amounts"]["to_call"])
            self.assertEqual(reading["amounts"]["hero_chips"], 1000)
            self.assertIsNone(reading["hero_seat"], "explicit Hero identity is not physical seat 4")
            self.assertEqual(reading["field_statuses"]["hero_chips"]["status"], "accepted")
            self.assertEqual(reading["action_required"], False if required is False else None)

    def test_explicit_hero_seat_and_amount_text_are_verified_not_inferred(self):
        for seat in (1, 2, 3, 4, 5, 6, 0, 7, True, "4", None):
            self.state.begin_stream()
            self.health()
            self.observation(**self.reading("uncertain", hero_seat=seat, hero_chips=1000,
                                           amount_texts={"hero_chips": "10", "pot_size": "$1.50"},
                                           verified_fields=["hero_seated", "hero_chips", "hero_seat", "pot_size"]))
            view = self.state.snapshot()["observation"]
            self.assertEqual(view["amounts"]["hero_chips"], 1000)
            self.assertEqual(view["hero_seat"], seat if type(seat) is int and 1 <= seat <= 6 else None)
            self.assertEqual(view["amount_texts"]["hero_chips"], "10")
            self.assertIsNone(view["amount_texts"]["pot_size"])
        self.state.begin_stream()
        self.health()
        self.observation(**self.reading("uncertain", hero_seat=4, hero_chips=1000, verified_fields=["hero_chips"]))
        view = self.state.snapshot()["observation"]
        self.assertIsNone(view["hero_seat"])
        self.assertIsNone(view["amounts"]["hero_chips"])

    def test_contradictory_seating_cards_controls_or_amounts_remain_uncertain(self):
        call = {"action": "call", "presence": "present", "enabled": "enabled"}
        check = {"action": "check", "presence": "present", "enabled": "enabled"}
        cases = (
            self.reading(hero_cards=[{"rank": "9", "suit": "diamonds"}, {"rank": "T", "suit": "spades"}]),
            self.reading(controls=[call]),
            self.reading("seated_waiting", controls=[call]),
            self.reading("your_turn", hero_cards=[]),
            self.reading("your_turn", controls=[check], to_call=50),
            self.reading("your_turn", to_call=0),
            self.reading("your_turn", controls=[check, call]),
            self.reading("your_turn", min_raise_to=200, max_raise_to=100),
            self.reading("your_turn", controls=[call, call]),
            self.reading("your_turn", controls=[{**call, "presence": "absent"}]),
            self.reading("your_turn", controls=[{**call, "enabled": True}]),
            self.reading("your_turn", controls=[]),
            self.reading("observing", hero_seated=True),
        )
        for source in cases:
            with self.subTest(source=source):
                self.state.begin_stream()
                self.health()
                self.observation(**source)
                value = self.state.snapshot()["observation"]
                self.assertEqual(value["role"], "uncertain")
                self.assertIsNone(value["action_required"])
                self.assertIsNone(value["available_actions"])
                self.assertIsNone(value["amounts"]["to_call"])
                self.assertTrue(all(item["presence"] == item["enabled"] == "unknown" for item in value["controls"]))
                if source["hero_seated"] is True:
                    self.assertTrue(value["hero_seated"])
                    self.assertEqual(value["amounts"]["hero_chips"], source["hero_chips"])

    def test_current_verified_turn_has_independent_offered_controls_not_advice(self):
        self.health()
        self.observation(**self.reading("your_turn", available_actions=["PRIVATE"], quality_approved=True,
                                        metrics={"equity_pct": 100, "hand_rank": "PRIVATE"}))
        value = self.state.snapshot()
        reading = value["observation"]
        self.assertEqual(reading["role"], "your_turn")
        self.assertEqual(reading["hero_cards"][0]["rank"], "10")
        self.assertEqual(reading["available_actions"], ["fold", "call", "raise"])
        self.assertEqual(reading["amounts"]["to_call"], 50)
        self.assertEqual(reading["amounts"]["hero_chips"], 1000)
        self.assertEqual(reading["controls"][3]["presence"], "unknown", "missing Bet is not verified absent")
        self.assertEqual(reading["metrics"], {"hand_rank": None, "pot_odds": None, "draw": None, "equity_pct": None})
        self.assertIsNone(value["advice"])
        self.assertFalse(reading["quality_approved"])
        self.assertEqual(value["server"]["quality_gate"], "failed")
        self.assertNotIn("PRIVATE", json.dumps(value))

    def test_observer_call_cost_requires_its_own_verified_acting_seat_not_hero_call(self):
        self.health()
        self.observation(**self.reading(acting_seat=3, acting_to_call=50, to_call=999, hero_chips=999,
                                       verified_fields=list(dashboard.VERIFIED_FIELDS), quality_approved=True,
                                       metrics={"pot_odds": {"seat": 3, "required_equity_pct": 25},
                                                "draw": {"outs": 9, "next_card_pct": 19, "by_river_pct": 35},
                                                "hand_rank": "Flush", "equity_pct": 80}))
        value = self.state.snapshot()["observation"]
        self.assertEqual(value["role"], "observing")
        self.assertEqual(value["acting_seat"], 3)
        self.assertEqual(value["amounts"]["acting_to_call"], 50)
        self.assertEqual(value["amounts"]["pot_size"], 150)
        self.assertIsNone(value["amounts"]["to_call"])
        self.assertIsNone(value["amounts"]["hero_chips"])
        self.assertEqual(value["metrics"], {"hand_rank": None, "pot_odds": None, "draw": None, "equity_pct": None})

    def test_observer_unknown_actor_or_unverified_amount_never_produces_pot_odds(self):
        cases = [{"acting_seat": seat, "acting_to_call": 50} for seat in (None, 0, 7, True, 3.0, "3")]
        cases += [{"acting_seat": 3, "acting_to_call": amount} for amount in (None, -1, True, 50.0, "50", float("inf"))]
        cases += [{"acting_seat": 3, "acting_to_call": 50, "verified_fields": ["pot_size", "hero_seated", "action_required"]}]
        for extra in cases:
            self.state.begin_stream()
            self.health()
            fields = {"verified_fields": list(dashboard.VERIFIED_FIELDS), **extra}
            self.observation(**self.reading(**fields))
            value = self.state.snapshot()["observation"]
            self.assertIsNone(value["amounts"]["acting_to_call"])
            self.assertIsNone(value["amounts"]["to_call"])
            self.assertIsNone(value["metrics"]["pot_odds"])
        self.health(2)
        self.observation(2, **self.reading(acting_seat=6, acting_to_call=0, verified_fields=list(dashboard.VERIFIED_FIELDS)))
        self.assertEqual(self.state.snapshot()["observation"]["amounts"]["acting_to_call"], 0)

    def test_wagers_are_bounded_one_based_and_private_with_nullable_amounts(self):
        self.health()
        self.observation(**self.reading(wagers=[{"seat": 1, "amount": 0, "name": "PRIVATE"},
                                               {"seat": 6, "amount": None}, {"seat": 3, "amount": True}],
                                       verified_fields=list(dashboard.VERIFIED_FIELDS)))
        value = self.state.snapshot()["observation"]
        self.assertEqual(value["wagers"], [{"seat": 1, "amount": 0}, {"seat": 6, "amount": None}, {"seat": 3, "amount": None}])
        self.assertNotIn("PRIVATE", json.dumps(value))
        for wagers in ([{"seat": 0, "amount": 20}], [{"seat": 7, "amount": 20}],
                       [{"seat": 1, "amount": 20}, {"seat": 1, "amount": 30}],
                       [{"seat": 1, "amount": 20}] * 7, ["PRIVATE"]):
            self.state.begin_stream()
            self.health()
            self.observation(**self.reading(wagers=wagers, verified_fields=list(dashboard.VERIFIED_FIELDS)))
            self.assertEqual(self.state.snapshot()["observation"]["wagers"], [])
        self.health(2)
        self.observation(2, **self.reading(wagers=[{"seat": 1, "amount": 20}]))
        self.assertEqual(self.state.snapshot()["observation"]["wagers"], [])

    def test_critical_amounts_require_per_field_verification_and_finite_integers(self):
        for amount in (None, True, -1, "50", 50.0, float("nan"), float("inf"), 9_007_199_254_740_992):
            self.state.begin_stream()
            self.health()
            self.observation(**self.reading("your_turn", to_call=amount, hero_chips=amount))
            value = self.state.snapshot()["observation"]
            self.assertIsNone(value["amounts"]["to_call"])
            self.assertIsNone(value["amounts"]["hero_chips"])
        self.health(2)
        self.observation(2, **self.reading("your_turn", verified_fields=["hero_seated", "action_required", "controls"]))
        self.assertTrue(all(value is None for value in self.state.snapshot()["observation"]["amounts"].values()))

    def test_role_and_controls_cannot_return_after_eof_or_same_source_tombstone(self):
        self.health()
        self.observation(**self.reading("your_turn"))
        self.state.end_stream()
        self.observation(**self.reading("your_turn"))
        self.assertIsNone(self.state.snapshot()["observation"])
        self.health(2)
        self.observation(2, **self.reading("seated_waiting"))
        self.state.ingest({"schema_version": 2, "event": "observation_invalidated", "generation": 2,
                           "epoch": 1, "reason": "turn-changed"})
        self.observation(2, **self.reading("your_turn"))
        self.assertIsNone(self.state.snapshot()["observation"])
        self.health(3)
        self.observation(3, **self.reading("your_turn"))
        self.assertEqual(self.state.snapshot()["observation"]["role"], "your_turn")

    def test_capture_health_is_not_recording_readiness(self):
        self.state.ingest({"schema_version": 2, "event": "configuration", "identity_configured": True})
        self.health()
        self.assertEqual(self.state.snapshot()["readiness"], "UI_READY")
        self.assertEqual(self.state.snapshot()["capture"]["recorded_frames"], 0)
        self.health(recording_enabled=True, recorded_frames=123)
        self.assertEqual(self.state.snapshot()["readiness"], "UI_READY")
        self.assertFalse(self.state.snapshot()["capture"]["recording_enabled"])

    def test_legacy_absent_or_explicit_disabled_recorder_fields_are_normal_unknowns(self):
        self.health()
        capture = self.state.snapshot()["capture"]
        self.assertEqual((capture["recording_status"], capture["recorded_frames"], capture["recorded_bytes"]),
                         ("disabled", 0, 0))
        self.assertFalse(capture["recording_enabled"])
        self.assertFalse(capture["recording_complete"])
        self.health(recording_enabled=False, recorded_frames=0, recorded_bytes=0,
                    recording_status="disabled", recording_complete=False)
        self.assertEqual(self.state.snapshot()["capture"]["recording_status"], "disabled")
        self.observation()
        self.assertEqual(self.state.snapshot()["observation"]["role"], "uncertain")
        self.assertIsNone(self.state.snapshot()["observation"]["amounts"]["to_call"])
        self.assertEqual(self.state.snapshot()["readiness"], "UI_READY")

    def test_recording_counters_are_monotonic_durable_prefix_not_readiness(self):
        self.health(recording_enabled=True, recorded_frames=2, recorded_bytes=200,
                    recording_status="active", recording_complete=True)
        self.health(2, frame_count=10, recording_enabled=True, recorded_frames=3, recorded_bytes=300,
                    recording_status="active", recording_complete=True, recording_path="PRIVATE-PATH",
                    title="PRIVATE-TITLE", readiness="RECORDING_READY")
        capture = self.state.snapshot()["capture"]
        self.assertEqual((capture["recorded_frames"], capture["recorded_bytes"]), (3, 300))
        self.assertTrue(capture["recording_complete"])
        self.assertEqual(self.state.snapshot()["readiness"], "UI_READY")
        self.health(3, frame_count=11, recording_enabled=True, recorded_frames=2, recorded_bytes=400,
                    recording_status="active", recording_complete=True)
        capture = self.state.snapshot()["capture"]
        self.assertEqual((capture["recorded_frames"], capture["recorded_bytes"]), (3, 300))
        self.assertEqual(capture["recording_status"], "io_failure")
        self.assertFalse(capture["recording_complete"])
        self.health(4, frame_count=12, recording_enabled=True, recorded_frames=4, recorded_bytes=500,
                    recording_status="active", recording_complete=True)
        self.assertEqual(self.state.snapshot()["capture"]["recorded_frames"], 3)
        self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])
        self.assertNotIn("PRIVATE", json.dumps(self.state.snapshot()))

    def test_caps_failures_and_missing_stats_preserve_prefix_and_cannot_reopen(self):
        for terminal in ("count_limit", "disk_limit", "io_failure"):
            with self.subTest(terminal=terminal):
                self.state.begin_stream()
                self.health(recording_enabled=True, recorded_frames=2, recorded_bytes=200,
                            recording_status="active", recording_complete=True)
                self.health(2, recording_enabled=True, recorded_frames=2, recorded_bytes=200,
                            recording_status=terminal, recording_complete=False)
                self.assertEqual(self.state.snapshot()["capture"]["recording_status"], terminal)
                self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])
                self.health(3, recording_enabled=True, recorded_frames=3, recorded_bytes=300,
                            recording_status="active", recording_complete=True)
                self.assertEqual(self.state.snapshot()["capture"]["recorded_frames"], 2)
                self.assertEqual(self.state.snapshot()["capture"]["recorded_bytes"], 200)
                self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])
        self.state.begin_stream()
        self.health(recording_enabled=True, recorded_frames=2, recorded_bytes=200,
                    recording_status="active", recording_complete=True)
        self.health(2)
        capture = self.state.snapshot()["capture"]
        self.assertEqual((capture["recorded_frames"], capture["recorded_bytes"]), (2, 200))
        self.assertEqual(capture["recording_status"], "io_failure")
        self.assertFalse(capture["recording_complete"])

    def test_malformed_unsafe_recording_stats_never_claim_complete_or_reset_counts(self):
        base = {"recording_enabled": True, "recorded_frames": 2, "recorded_bytes": 200,
                "recording_status": "active", "recording_complete": True}
        invalid = [{field: value} for field in ("recorded_frames", "recorded_bytes")
                   for value in (None, True, -1, 2.0, "2", float("nan"), float("inf"))]
        invalid += [{"recorded_frames": 20001}, {"recorded_bytes": 2 * 1024 * 1024 * 1024 + 1},
                    {"recorded_frames": 8}, {"recorded_frames": 0}, {"recorded_bytes": 0},
                    {"recording_enabled": 1}, {"recording_enabled": False},
                    {"recording_complete": "true"}, {"recording_status": []},
                    {"recording_status": "disabled"}, {"recording_status": "count_limit"},
                    {"frame_count": None}, {"frame_count": True}, {"frame_count": 0}]
        for extra in invalid:
            with self.subTest(extra=extra):
                self.state.begin_stream()
                self.health(recording_enabled=True, recorded_frames=1, recorded_bytes=100,
                            recording_status="active", recording_complete=True)
                self.health(2, **{**base, **extra})
                capture = self.state.snapshot()["capture"]
                self.assertFalse(capture["recording_complete"])
                self.assertEqual((capture["recorded_frames"], capture["recorded_bytes"]), (1, 100))
                self.assertEqual(self.state.snapshot()["readiness"], "UI_READY")
        self.state.begin_stream()
        self.health(recording_enabled=True, recorded_frames=1, recorded_bytes=100,
                    recording_status="active", recording_complete=False)
        self.health(2, **base)
        self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])

    def test_eof_or_expired_heartbeat_is_not_recording_completion(self):
        self.health(recording_enabled=True, recorded_frames=1, recorded_bytes=100,
                    recording_status="active", recording_complete=True)
        self.clock.value += 3
        self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])
        self.state.end_stream()
        self.assertEqual(self.state.snapshot()["capture"]["recorded_frames"], 1)
        self.health(2, recording_enabled=True, recorded_frames=2, recorded_bytes=200,
                    recording_status="active", recording_complete=True)
        self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])

    def test_invalid_capture_identity_bounds_or_delayed_health_is_not_recording_proof(self):
        base = {"recording_enabled": True, "recorded_frames": 1, "recorded_bytes": 100,
                "recording_status": "active", "recording_complete": True}
        invalid = [{"frame_width": width} for width in (None, True, 0, -1, 16385, "800")]
        invalid += [{"frame_count": 0, "recorded_frames": 0, "recorded_bytes": 0},
                    {"frame_height": 0}, {"identity": {**IDENTITY, "process_id": 0}},
                    {"identity": {**IDENTITY, "hwnd": "0x0"}},
                    {"captured_at_unix_ms": int(self.clock.wall() * 1000) + 1}]
        for extra in invalid:
            with self.subTest(extra=extra):
                self.state.begin_stream()
                self.health(**{**base, **extra})
                self.assertFalse(self.state.snapshot()["capture"]["fresh_capture"])
                self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])
                self.assertEqual(self.state.snapshot()["readiness"], "UI_READY")
        self.state.begin_stream()
        self.health(**base)
        self.health(2, emitted_at_unix_ms=int(self.clock.wall() * 1000) - 3000)
        self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])

    def test_temperature_loading_does_not_approve_quality(self):
        self.state.set_model("ready", calibrated=True)
        value = self.state.snapshot()["server"]
        self.assertTrue(value["temperature_calibration_loaded"])
        self.assertEqual(value["quality_gate"], "failed")
        self.assertFalse(value["advice_ready"])

    def test_clear_without_advice_tombstones_controls(self):
        self.health()
        self.observation()
        self.state.ingest({"schema_version": 2, "event": "observation_invalidated", "generation": 1,
                           "epoch": 1, "reason": "frame-changed"})
        self.observation()
        self.assertIsNone(self.state.snapshot()["observation"])
        self.health(2, 2)
        self.observation(2, 2)
        self.assertIsNotNone(self.state.snapshot()["observation"])

    def test_polling_does_not_renew_same_lease(self):
        self.health()
        self.observation()
        self.clock.value += 0.5
        self.assertLessEqual(self.state.snapshot()["observation"]["remaining_ms"], 500)
        self.observation()
        self.assertLessEqual(self.state.snapshot()["observation"]["remaining_ms"], 500)
        self.clock.value += 0.5
        self.assertIsNone(self.state.snapshot()["observation"])
        self.observation()
        self.assertIsNone(self.state.snapshot()["observation"])

    def test_new_observation_gets_its_own_budget_without_poll_renewal(self):
        now = int(self.clock.wall() * 1000)
        self.health()
        self.observation(valid_for_ms=500, expires_at_unix_ms=now + 500)
        self.clock.value += .2
        self.observation(2)
        self.clock.value += .4
        current = self.state.snapshot()["observation"]
        self.assertIsNotNone(current)
        self.assertEqual(current["generation"], 2)
        self.assertLessEqual(current["remaining_ms"], 600)
        self.clock.value += .601
        self.assertIsNone(self.state.snapshot()["observation"])

    def test_old_target_or_epoch_cannot_reactivate(self):
        self.health()
        self.observation()
        self.health(2, 2)
        self.observation()
        self.assertIsNone(self.state.snapshot()["observation"])

    def test_weak_table_and_bare_decision_never_supply_actions(self):
        self.state.ingest({"schema_version": 2, "event": "table", "action_required": True,
                           "available_actions": ["fold"]})
        self.assertIsNone(self.state.snapshot()["observation"])
        self.state.ingest({"schema_version": 2, "event": "decision", "action": "call", "quality_approved": True})
        self.assertIsNone(self.state.snapshot()["advice"])

    def test_heartbeat_loss_eof_and_stream_change_clear(self):
        self.health()
        self.observation()
        self.clock.value += 2.6
        self.assertFalse(self.state.snapshot()["capture"]["fresh_capture"])
        self.assertIsNone(self.state.snapshot()["observation"])
        before = self.state.session_id
        self.state.end_stream()
        self.state.begin_stream()
        self.assertNotEqual(before, self.state.session_id)
        self.assertIsNone(self.state.snapshot()["observation"])

    def test_delayed_future_or_over_budget_observation_is_rejected(self):
        for extra in ({"expires_at_unix_ms": 1}, {"emitted_at_unix_ms": int(self.clock.wall() * 1000) + 1},
                      {"valid_for_ms": 6000}):
            self.state.begin_stream()
            self.health()
            self.observation(**extra)
            self.assertIsNone(self.state.snapshot()["observation"])

    def test_delayed_health_or_numeric_hwnd_does_not_claim_current_capture(self):
        now = int(self.clock.wall() * 1000)
        self.health(emitted_at_unix_ms=now - 3000, captured_at_unix_ms=now - 3000)
        self.assertFalse(self.state.snapshot()["capture"]["fresh_capture"])
        self.health(identity={**IDENTITY, "hwnd": 42})
        self.assertFalse(self.state.snapshot()["capture"]["fresh_capture"])

    def test_duplicate_cards_and_private_fields_never_leak(self):
        self.health()
        self.observation(player_name="PRIVATE-PLAYER", raw_response="SECRET", hero_cards=[{"rank": "ace", "suit": "hearts"}])
        self.assertIsNone(self.state.snapshot()["observation"])
        self.health(2, 2)
        self.observation(2, 2, player_name="PRIVATE-PLAYER", raw_response="SECRET")
        text = json.dumps(self.state.snapshot())
        for private in ("PRIVATE-NAME", "PRIVATE-PLAYER", "SECRET", "process_id", "hwnd"):
            self.assertNotIn(private, text)

    def test_public_model_state_never_exposes_a_checkpoint_path(self):
        state = dashboard.DashboardState("coinpoker-laya-vision", "PRIVATE-CHECKPOINT-PATH/model")
        state.set_model("ready", calibrated=True, floors_loaded=True)
        value = state.snapshot()
        self.assertIsNone(value["server"]["checkpoint"])
        self.assertNotIn("PRIVATE", json.dumps(value))
        self.assertFalse(value["server"]["advice_ready"])

    def test_card_shape_and_street_counts_are_validated_before_roles(self):
        for extra in ({"hero_cards": [{"rank": [], "suit": "spades"}]},
                      {"hero_cards": [{"rank": "T", "suit": "spades"}]},
                      {"hero_cards": [{"rank": "10", "suit": "spades"}, {"rank": "T", "suit": "spades"}]},
                      {"game_phase": "preflop"}, {"board": []}):
            self.state.begin_stream()
            self.health()
            self.observation(**self.reading(**extra))
            self.assertIsNone(self.state.snapshot()["observation"])

    def test_bad_utf8_oversize_or_nonfinite_feed_closes(self):
        for data in (b"\xff\n", b'{"schema_version":2,"x":NaN}\n', b"x" * (dashboard.MAX_RECORD + 1)):
            self.state.begin_stream()
            dashboard.drain_feed(io.BytesIO(data), self.state)
            self.assertEqual(self.state.snapshot()["capture"]["state"], "disconnected")
            self.assertIsNone(self.state.snapshot()["observation"])

    def test_ledger_preserves_prefix_and_stops_at_cap(self):
        with tempfile.TemporaryDirectory(dir=dashboard.ROOT / ".local") as directory:
            path = Path(directory) / "ledger.jsonl"
            ledger = dashboard.PrivateLedger(path, max_events=2)
            for n in range(4):
                ledger.append({"event": "gap", "sequence": n})
            ledger.close()
            self.assertFalse(ledger.complete)
            self.assertEqual([json.loads(r)["sequence"] for r in path.read_text().splitlines()], [0, 1])

    def test_private_history_uses_native_tagged_dto_and_one_based_slots(self):
        self.state.ingest({"schema_version": 2, "event": "history", "summary": {
            "counts": {"folds": 0, "checks": 0, "calls": 1, "bets": 0, "raises": 0},
            "gaps": 2, "occupants": [{"eligible_hands": 1, "name": "PRIVATE"}],
            "events": [{"event": "action", "event_sequence": 2,
                        "action": {"seat": 5, "kind": "call", "amount": 100, "all_in": False,
                                   "name": "PRIVATE"}}]}})
        history = self.state.snapshot()["history"]
        self.assertEqual(history["events"][0]["seat"], 6)
        self.assertEqual(history["events"][0]["action"], "call")
        self.assertEqual(history["counts"]["observed_actions"], 1)
        self.assertEqual(history["counts"]["folds"], 0)
        self.assertEqual(history["counts"]["calls"], 1)
        self.assertEqual(history["counts"]["bets"], 0)
        self.assertEqual(history["counts"]["raises"], 0)
        self.assertIsNone(history["events"][0]["preflop_raise_ordinal"])
        self.assertEqual(history["gaps"], 2)
        self.assertNotIn("PRIVATE", json.dumps(history))

    def test_history_ordinals_need_an_explicit_trusted_full_preflop_prefix(self):
        base = {"seat": 5, "kind": "raise", "amount": 100, "all_in": False,
                "trusted": True, "full_raise": True, "forced": "voluntary",
                "preflop_raise_ordinal": 3, "name": "PRIVATE"}
        actions = [base, {**base, "preflop_raise_ordinal": 4},
                   {**base, "preflop_raise_ordinal": None}, {**base, "preflop_raise_ordinal": True},
                   {**base, "preflop_raise_ordinal": 1}, {**base, "preflop_raise_ordinal": 10001},
                   {**base, "kind": "call"}, {**base, "trusted": False},
                   {**base, "full_raise": False}, {**base, "forced": "big_blind"},
                   {**base, "forced": None}, {**base, "forced": "unknown"},
                   {key: value for key, value in base.items() if key != "forced"}]
        events = [{"event": "action", "event_sequence": sequence, "street": "preflop", "action": action}
                  for sequence, action in enumerate(actions, 1)]
        events += [{"event": "action", "event_sequence": 11, "street": "flop", "action": base},
                   {"event": ["PRIVATE"], "event_sequence": 12}]
        self.state.ingest({"schema_version": 2, "event": "history", "summary": {
            "events": events, "counts": {"folds": True, "bets": -1, "raises": "9", "three_bets": 1, "four_bets": 1}}})
        history = self.state.snapshot()["history"]
        self.assertEqual([event["preflop_raise_ordinal"] for event in history["events"]], [3, 4] + [None] * 13)
        self.assertIsNone(history["counts"]["folds"])
        self.assertIsNone(history["counts"]["bets"])
        self.assertIsNone(history["counts"]["raises"])
        self.assertIsNone(history["counts"]["observed_actions"])
        self.assertEqual(history["counts"]["three_bets"], 1)
        self.assertEqual(history["counts"]["four_bets"], 1)
        self.assertEqual(history["events"][-1]["kind"], "gap")
        self.assertNotIn("PRIVATE", json.dumps(history))

    def test_private_ledger_keeps_sanitized_role_changes_without_a_new_session(self):
        with tempfile.TemporaryDirectory(dir=dashboard.ROOT / ".local") as directory:
            path = Path(directory) / "ledger.jsonl"
            self.state.begin_stream(path)
            for generation, role in enumerate(("observing", "seated_waiting", "your_turn"), 1):
                self.health(generation)
                self.observation(generation, **self.reading(role, player_name="PRIVATE", raw_response="SECRET"))
            self.state.end_stream()
            text = path.read_text()
            records = [json.loads(line) for line in text.splitlines()]
            self.assertEqual([record["observation"]["role"] for record in records if record["event"] == "observation"],
                             ["observing", "seated_waiting", "your_turn"])
            for private in ("PRIVATE", "SECRET", "exe_name", "process_id", "hwnd", "verified_fields"):
                self.assertNotIn(private, text)

    def test_ledger_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory(dir=dashboard.ROOT / ".local") as directory:
            path = Path(directory) / "ledger.jsonl"
            path.write_text("user-data")
            ledger = dashboard.PrivateLedger(path)
            ledger.append({"event": "gap"})
            self.assertFalse(ledger.complete)
            self.assertEqual(path.read_text(), "user-data")

    def test_local_profile_paths_and_unknown_cli_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            dashboard.local_path("../outside.json")
        for config in ({}, {"exe_name": "CoinPoker.exe", "command": "unsafe"},
                       {"exe_name": "CoinPoker.exe", "binary": []},
                       {"exe_name": "CoinPoker.exe", "binary": "../coinpoker.exe"}):
            with self.assertRaises(ValueError):
                dashboard.capture_argv(config)

    def test_reference_and_replay_are_separate_and_no_live_advice(self):
        ref = dashboard.references()
        self.assertEqual(ref["schema_version"], 1)
        self.assertIn("Not live recommendations", ref["scope"])
        sections = {section["id"]: section for section in ref["sections"]}
        self.assertIn([150, 50, 200, 25], sections["pot-odds"]["tables"][0]["rows"])
        self.assertAlmostEqual(sections["outs-and-draws"]["tables"][1]["rows"][3][3], 31.452359, places=6)
        demo = dashboard.replay()
        self.assertEqual(demo["source"], "demo")
        frames = demo["scenarios"][0]["frames"]
        self.assertTrue(all(f["source"] == "demo" and f["advice"] is None for f in frames))
        self.assertEqual(frames[1]["observation"]["available_actions"], ["fold", "call", "raise"])
        self.assertIsNone(frames[2]["observation"])

    def test_capture_profile_uses_actual_native_flags(self):
        with patch.object(Path, "is_file", return_value=True):
            argv = dashboard.capture_argv({"exe_name": "SyntheticClient.exe", "window_title": "SyntheticTable",
                                           "lobby_size": "1280x778", "window_hwnd": "0x1"})
            self.assertEqual(argv[1:], ["--exe-name", "SyntheticClient.exe", "--window-hwnd", "0x1",
                                        "--table-title", "SyntheticTable", "--lobby-size", "1280x778"])
            for invalid in ({"client_width": 800}, {"lobby_size": "0x778"}, {"pid": True}):
                with self.assertRaises(ValueError):
                    dashboard.capture_argv({"exe_name": "SyntheticClient.exe", **invalid})


class NativeProjectionTests(unittest.TestCase):
    health = StateTests.health

    def setUp(self):
        self.clock = Clock()
        self.state = dashboard.DashboardState("synthetic", monotonic=self.clock.mono, wall=self.clock.wall)

    def fresh(self, **extra):
        self.state.set_model("ready", calibrated=True, floors_loaded=True)
        self.state.begin_stream()
        self.health()
        source = native_observation(self.clock, **extra)
        self.state.ingest(source)
        return source

    def test_native_full_observation_and_decision_project_without_claiming_model_certification(self):
        metrics = {"hand_rank": "High Card", "pot_odds": {"seat": None, "required_equity_pct": 25},
                   "draw": {"outs": 9, "next_card_pct": 9 / 47 * 100, "by_river_pct": (1 - 38 / 47 * 37 / 46) * 100},
                   "equity_pct": 60}
        source = self.fresh(metrics=metrics)
        self.state.ingest(native_decision(source, opponent="PRIVATE-NAME", raw_response="PRIVATE-TEXT"))
        with patch.object(dashboard.subprocess, "Popen", side_effect=AssertionError("snapshot spawned a process")), \
                patch.object(dashboard.manual_capture, "stop_session", side_effect=AssertionError("snapshot stopped capture")):
            value = self.state.snapshot()
        view, advice = value["observation"], value["advice"]
        self.assertEqual(view["metrics"], metrics)
        self.assertEqual((advice["action"], advice["amount"], advice["ev"]), ("call", 50, 70))
        self.assertEqual((advice["equity_pct"], advice["pot_odds_pct"], advice["break_even_pct"]), (60, 25, 25))
        self.assertTrue(value["server"]["advice_ready"])
        self.assertEqual(value["server"]["quality_gate"], "failed")
        for projection in (view, advice):
            self.assertFalse(projection["quality_approved"])
            self.assertTrue(projection["experimental"])
            self.assertEqual(projection["session_id"], value["session_id"])
            self.assertEqual(projection["source_id"], value["capture"]["source_id"])
            self.assertEqual(projection["generation"], value["capture"]["generation"])
            self.assertEqual(projection["expires_at_unix_ms"], source["expires_at_unix_ms"])
        self.assertNotIn("PRIVATE", json.dumps(value))
        self.assertNotIn("verified_fields", json.dumps(value))

    def test_each_supported_native_action_requires_exact_offered_control_and_amount(self):
        for action, amount in (("fold", 0), ("call", 50), ("raise", 250), ("check", 0), ("allin", 40)):
            with self.subTest(action=action):
                source = native_observation(self.clock)
                if action == "check":
                    source.update(to_call=0, available_actions=["check", "raise"])
                elif action == "allin":
                    source.update(hero_chips=40, available_actions=["fold", "allin"], min_raise_to=None, max_raise_to=None)
                    source["verified_fields"] = source["verified_fields"][:-2]
                for control in source["controls"]:
                    offered = ("allin" if control["action"] == "all_in" else control["action"]) in source["available_actions"]
                    control.update(presence="present" if offered else "unknown", enabled="enabled" if offered else "unknown")
                source = self.fresh(**source)
                cost = min(source["to_call"], source["hero_chips"])
                odds = cost / (150 + cost) if cost else None
                self.state.ingest(native_decision(source, action=action, amount=amount, pot_odds=odds, break_even=odds))
                self.assertEqual(self.state.snapshot()["advice"]["action"], "all_in" if action == "allin" else action)

    def test_quality_flag_cannot_upgrade_legacy_partial_missing_or_contradictory_evidence(self):
        cases = [{"available_actions": None}, {"available_actions": ["call"]}, {"available_actions": ["call", "call"]},
                 {"available_actions": ["fold", "call", "bet"]}, {"controls": None},
                 {"pot_size": 0}, {"hero_chips": 0}, {"hero_chips": 0x100000000}, {"to_call": None},
                 {"verified_fields": ["pot_size"]}, {"verified_fields": "controls"},
                 {"hero_seated": None}, {"action_required": False}, {"role": "observing"},
                 {"acting_seat": "3"}, {"acting_seat": True}, {"wagers": None}, {"wagers": [{"seat": 1, "amount": 50}]},
                 {"capabilities": [{"training": "trained_unapproved"}]}, {"board_slots": [None] * 5},
                 {"metrics": {}}, {"experimental": {"diagnostic_only": True}}]
        for extra in cases:
            with self.subTest(extra=extra):
                source = self.fresh(quality_approved=True, **extra)
                self.state.ingest(native_decision(source, quality_approved=True))
                value = self.state.snapshot()
                self.assertIsNone(value["advice"])
                self.assertFalse(value["server"]["advice_ready"])
                if value["observation"] is not None:
                    self.assertFalse(value["observation"]["quality_approved"])
                    self.assertEqual(value["observation"]["metrics"], dict.fromkeys(dashboard.METRIC_FIELDS))


    def test_observing_and_waiting_can_have_independent_metrics_but_no_hero_advice(self):
        for role in ("observing", "seated_waiting"):
            observing = role == "observing"
            source = self.fresh(role=role, hero_seated=not observing, action_required=False,
                                hero_cards=[] if observing else native_observation(self.clock)["hero_cards"],
                                controls=dashboard.unknown_controls(), available_actions=None, to_call=None,
                                hero_chips=None if observing else 1000, min_raise_to=None, max_raise_to=None,
                                acting_seat=3, acting_to_call=50, verified_fields=list(dashboard.VERIFIED_FIELDS),
                                metrics={"hand_rank": "High Card", "draw": None, "equity_pct": 60,
                                         "pot_odds": {"seat": 3, "required_equity_pct": 25}})
            self.state.ingest(native_decision(source))
            view = self.state.snapshot()
            self.assertIsNone(view["advice"])
            metrics = view["observation"]["metrics"]
            self.assertEqual(metrics["hand_rank"], None if observing else "High Card")
            self.assertEqual(metrics["equity_pct"], None if observing else 60)
            self.assertEqual(metrics["pot_odds"], {"seat": 3, "required_equity_pct": 25} if observing else None)

    def test_decision_types_ranges_and_action_amounts_are_closed(self):
        invalid = [{field: value} for field in ("equity", "pot_odds", "break_even", "confidence")
                   for value in (True, -1, "0.6", 1.01, float("nan"), float("inf"), 10 ** 1000)]
        invalid += [{"amount": value} for value in (None, True, -1, 50.0, "50", 0x100000000)]
        invalid += [{"ev": value} for value in (None, True, "70", float("inf"), float("nan"), 10 ** 1000)]
        invalid += [{"action": value} for value in (None, {}, [], "CALL", "bet", "all_in", "PRIVATE")]
        invalid += [{"action": "check", "amount": 0}, {"action": "fold", "amount": 1},
                    {"action": "call", "amount": 0}, {"action": "raise", "amount": 99},
                    {"action": "raise", "amount": 1001}, {"pot_odds": .5}, {"break_even": None}]
        source = self.fresh()
        for extra in invalid:
            with self.subTest(extra=extra):
                self.state.ingest(native_decision(source, **extra))
                self.assertIsNone(self.state.snapshot()["advice"])
                self.assertFalse(self.state.snapshot()["server"]["advice_ready"])
        self.state.ingest(native_decision(source))
        self.assertIsNotNone(self.state.snapshot()["advice"])

    def test_metric_types_bounds_and_dependencies_do_not_leak_untrusted_strings(self):
        invalid = (True, -1, 101, "PRIVATE", float("nan"), float("inf"), 10 ** 1000, {}, [])
        for value in invalid:
            source = self.fresh(metrics={"hand_rank": value, "pot_odds": {"seat": None, "required_equity_pct": value},
                                         "draw": {"outs": value, "next_card_pct": value, "by_river_pct": value}, "equity_pct": value})
            self.assertEqual(self.state.snapshot()["observation"]["metrics"], dict.fromkeys(dashboard.METRIC_FIELDS))
            self.state.ingest(native_decision(source))
            self.assertIsNotNone(self.state.snapshot()["advice"])
        for odds, draw in (({"seat": 1, "required_equity_pct": 25}, {"outs": 48, "next_card_pct": 25, "by_river_pct": 50}),
                           ({"seat": None, "required_equity_pct": 50}, {"outs": 9, "next_card_pct": 40, "by_river_pct": 30})):
            self.fresh(metrics={"hand_rank": None, "equity_pct": None, "pot_odds": odds, "draw": draw})
            self.assertEqual(self.state.snapshot()["observation"]["metrics"], dict.fromkeys(dashboard.METRIC_FIELDS))

    def test_exact_ticket_clocks_table_epoch_generation_and_session_binding(self):
        source = self.fresh()
        base = native_decision(source)
        tickets = [{**base["observation"], key: value} for key, value in (
            ("generation", 2), ("generation", True), ("epoch", 2), ("captured_at_ms", 1002),
            ("captured_at_unix_ms", source["captured_at_unix_ms"] + 1),
            ("identity", {**IDENTITY, "hwnd": "0x2"}), ("identity", {**IDENTITY, "process_id": 43}),
            ("identity", {**IDENTITY, "exe_name": "other.exe"}))]
        for ticket in tickets:
            self.state.ingest({**base, "observation": ticket})
            self.assertIsNone(self.state.snapshot()["advice"])
        for extra in ({"captured_at_unix_ms": source["captured_at_unix_ms"] + 1},
                      {"expires_at_unix_ms": source["captured_at_unix_ms"] + 5001, "valid_for_ms": 5000},
                      {"emitted_at_unix_ms": int(self.clock.wall() * 1000) + 1},
                      {"expires_at_unix_ms": int(self.clock.wall() * 1000)}, {"valid_for_ms": True}):
            self.state.ingest({**base, **extra})
            self.assertIsNone(self.state.snapshot()["advice"])
        self.state.ingest(base, session_id="retired-session")
        self.assertIsNone(self.state.snapshot()["advice"])
        self.state.ingest(base, session_id=self.state.session_id)
        self.assertIsNotNone(self.state.snapshot()["advice"])


    def test_poll_replay_and_relabelled_generation_cannot_extend_original_lease(self):
        source = self.fresh()
        self.state.ingest(native_decision(source, expires_at_unix_ms=source["emitted_at_unix_ms"] + 750, valid_for_ms=750))
        original = self.state.snapshot()["advice"]["expires_at_unix_ms"]
        self.clock.value += .5
        self.state.ingest(native_decision(source))
        advice = self.state.snapshot()["advice"]
        self.assertEqual(advice["expires_at_unix_ms"], original)
        self.assertLessEqual(advice["remaining_ms"], 250)
        self.clock.value += .251
        self.assertIsNone(self.state.snapshot()["advice"])
        self.state.ingest(native_decision(source))
        self.assertIsNone(self.state.snapshot()["advice"])
        replay = copy.deepcopy(source)
        replay["observation"]["generation"] = 2
        replay.update(emitted_at_unix_ms=int(self.clock.wall() * 1000), valid_for_ms=3000,
                      expires_at_unix_ms=int(self.clock.wall() * 1000) + 3000, quality_approved=True)
        self.health(2)
        self.state.ingest(replay)
        self.state.ingest(native_decision(replay))
        self.assertIsNone(self.state.snapshot()["advice"])
        self.clock.value += .25
        self.assertIsNone(self.state.snapshot()["observation"])
        self.state.ingest(replay)
        self.assertIsNone(self.state.snapshot()["observation"])

    def test_source_loss_new_generation_and_model_loss_clear_without_rearming_old_data(self):
        for change in (lambda: self.health(2), lambda: self.health(2, 2), lambda: self.health(2, identity={**IDENTITY, "hwnd": "0x2"}),
                       lambda: self.health(fresh_capture=False), lambda: self.state.end_stream(),
                       lambda: self.state.set_model("failed"),
                       lambda: self.state.ingest({"schema_version": 2, "event": "clear", "generation": 1, "reason": "action-not-required"})):
            source = self.fresh(metrics={"hand_rank": "High Card", "equity_pct": 60, "draw": None, "pot_odds": None})
            self.state.ingest(native_decision(source))
            self.assertIsNotNone(self.state.snapshot()["advice"])
            change()
            self.assertIsNone(self.state.snapshot()["advice"])
            self.state.ingest(source)
            self.state.ingest(native_decision(source))
            self.assertIsNone(self.state.snapshot()["advice"])

    def test_independent_monotonic_and_wall_expiry_remove_advice_and_metrics(self):
        for clock in ("monotonic", "wall"):
            source = self.fresh(metrics={"hand_rank": None, "equity_pct": 60, "draw": None, "pot_odds": None})
            self.state.ingest(native_decision(source))
            now = getattr(self.state, clock)()
            with patch.object(self.state, clock, return_value=now + 1.001):
                self.assertIsNone(self.state.snapshot()["advice"])
                self.assertIsNone(self.state.snapshot()["observation"])
            self.state.ingest(source)
            self.assertIsNone(self.state.snapshot()["observation"])

    def test_model_readiness_and_quality_assertions_cannot_requalify_an_old_observation(self):
        self.state.begin_stream()
        self.health()
        source = native_observation(self.clock, quality_approved=True)
        self.state.ingest(source)
        self.state.set_model("ready", calibrated=True, floors_loaded=True)
        self.state.ingest(source)
        self.state.ingest(native_decision(source, quality_approved=True))
        self.assertIsNone(self.state.snapshot()["advice"])
        self.clock.value += .1
        self.health(2)
        fresh = native_observation(self.clock, generation=2)
        self.state.ingest(fresh)
        self.state.ingest(native_decision(fresh))
        self.assertIsNotNone(self.state.snapshot()["advice"])
        self.assertFalse(self.state.snapshot()["observation"]["quality_approved"])

    def test_heartbeat_loss_and_unprovable_all_in_raise_do_not_publish_advice(self):
        source = self.fresh(valid_for_ms=4500, expires_at_unix_ms=int(self.clock.wall() * 1000) + 4500)
        self.state.ingest(native_decision(source))
        self.assertIsNotNone(self.state.snapshot()["advice"])
        self.clock.value += 2.501
        value = self.state.snapshot()
        self.assertIsNone(value["advice"])
        self.assertIsNone(value["observation"])
        self.assertIsNone(value["capture"]["source_id"])
        self.assertFalse(value["server"]["advice_ready"])
        source = native_observation(self.clock, available_actions=["fold", "call", "raise", "allin"])
        source["controls"][-1].update(presence="present", enabled="enabled")
        source = self.fresh(**source)
        self.state.ingest(native_decision(source, action="allin", amount=1000))
        self.assertIsNone(self.state.snapshot()["advice"], "no hero contribution/all-in raise-to proof in ObservationView")
        self.state.ingest(native_decision(source, action="raise", amount=1000))
        self.assertEqual(self.state.snapshot()["advice"]["action"], "raise")


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=dashboard.ROOT / ".local")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(dashboard, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.config = {"binary": "target/debug/coinpoker.exe", "exe_name": "CoinPoker.exe",
                       "pid": 42, "window_hwnd": "0x100000001", "window_title": "NLH",
                       "record_dir": ".local/captures"}

    def test_default_supervisor_is_rooted_and_inert_until_polled_model_ready(self):
        state = dashboard.DashboardState("synthetic")
        with patch.object(dashboard, "PracticeAttachment") as selector, patch.object(dashboard, "LiveFeed") as feed:
            auto = dashboard.AutoAttachFeed(".local/optional-rule.json", state)
            self.addCleanup(auto.stop)
            selector.assert_called_once_with(".local/optional-rule.json", root=self.root)
            selector.return_value.select.assert_not_called()
            auto.poll()
            selector.return_value.select.assert_not_called()
            feed.assert_not_called()
            state.set_model("ready", floors_loaded=True)
            selector.return_value.select.return_value = FakeSelection()
            auto.poll()
            feed.assert_called_once_with(None, state, config=selector.return_value.select.return_value.config)

    def test_internal_capture_flags_have_fixed_private_defaults_and_strict_native_limits(self):
        with patch.object(Path, "is_file", return_value=True):
            argv = dashboard.capture_argv(self.config)
            self.assertEqual(argv[0], str(self.root / "target/debug/coinpoker.exe"))
            self.assertEqual(argv[1:], ["--exe-name", "CoinPoker.exe", "--pid", "42", "--window-hwnd",
                                        "0x100000001", "--table-title", "NLH", "--record-dir", ".local/captures",
                                        "--record-max-frames", "7200", "--record-max-bytes", "1073741824",
                                        "--record-interval-ms", "500"])
            for field, lower, upper in (("record_max_frames", 1, 20000),
                                        ("record_max_bytes", 1, 2 * 1024 * 1024 * 1024),
                                        ("record_interval_ms", 250, 60000)):
                for value in (lower, upper):
                    self.assertIn(str(value), dashboard.capture_argv({**self.config, field: value}))
                for value in (True, float(lower), str(lower), lower - 1, upper + 1, float("inf")):
                    with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                        dashboard.capture_argv({**self.config, field: value})
            without_recorder = {key: value for key, value in self.config.items() if key != "record_dir"}
            self.assertNotIn("--record-dir", dashboard.capture_argv(without_recorder))
            with self.assertRaises(ValueError):
                dashboard.capture_argv({**without_recorder, "record_max_frames": 1})

    def test_no_arbitrary_argv_environment_endpoint_or_invalid_identity(self):
        cases = [{"argv": ["--list-windows"]}, {"env": {"COINPOKER_EXE_NAME": "other.exe"}},
                 {"endpoint": "http://evil.example"}, {"record_dir": "C:/outside"},
                 {"record_dir": ".local/captures/another-run"}, {"binary": "scripts/coinpoker.exe"},
                 {"binary": "target/debug/coinpoker.cmd"}, {"exe_name": "--list-windows"},
                 {"exe_name": "CoinPoker.exe\n"}, {"exe_name": "C:/CoinPoker.exe"}, {"exe_name": "*.exe"},
                 {"window_title": "--vlm-endpoint"}, {"window_title": True}, {"window_title": "NLH\x00"}]
        cases += [{"pid": value} for value in (True, 0, -1, "42", 42.0, 0x100000000)]
        cases += [{"window_hwnd": value} for value in (True, 0, -1, "0x0", "0xGG", "0x" + "f" * 17, [])]
        with patch.object(Path, "is_file", return_value=True):
            for extra in cases:
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    dashboard.capture_argv({**self.config, **extra})

    def test_private_output_paths_reject_escape_devices_ads_and_redirected_root(self):
        self.assertEqual(dashboard.local_path(".local/history/synthetic.jsonl"),
                         self.root / ".local/history/synthetic.jsonl")
        for path in (None, [], "../outside", ".local/../outside", ".local", ".local/NUL.txt",
                     ".local/COM1/record.txt", ".local/a:secret", ".local/line\n.txt", ".local/trailing. "):
            with self.subTest(path=path), self.assertRaises(ValueError):
                dashboard.local_path(path)
        original = Path.resolve

        def redirected(path, *args, **kwargs):
            return self.root / "redirected" if path == self.root / ".local" else original(path, *args, **kwargs)

        with patch.object(Path, "resolve", redirected), self.assertRaises(ValueError):
            dashboard.local_path(".local/captures")

    def test_live_feed_uses_only_internal_config_and_scrubs_case_insensitive_overrides(self):
        state = dashboard.DashboardState("coinpoker-laya-vision")
        process = Mock(stdout=io.BytesIO(), stderr=io.BytesIO())
        process.poll.return_value = 0
        with patch.object(Path, "is_file", return_value=True), patch.object(dashboard.subprocess, "Popen", return_value=process) as spawn, \
                patch.object(dashboard.threading, "Thread") as thread, patch.dict(dashboard.os.environ,
                    {"CoinPoker_EXE_NAME": "PRIVATE-OVERRIDE", "COINPOKER_RECORD_DIR": "PRIVATE-PATH"}):
            thread.return_value.is_alive.return_value = False
            feed = dashboard.LiveFeed(None, state, config=self.config)
            kwargs = spawn.call_args.kwargs
            self.assertEqual(kwargs["cwd"], self.root)
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["stdin"], dashboard.subprocess.DEVNULL)
            overrides = {key: value for key, value in kwargs["env"].items() if key.upper().startswith("COINPOKER_")}
            self.assertEqual(overrides, {"COINPOKER_VLM_ENDPOINT": "http://127.0.0.1:18090/v1/laya/predict",
                                         "COINPOKER_VLM_MODEL": "coinpoker-laya-vision"})
            self.assertEqual(kwargs["stderr"], dashboard.subprocess.PIPE)
            feed.stop()
        self.assertNotIn("PRIVATE", json.dumps(state.snapshot()))

    def test_live_config_path_is_a_strict_selector_not_a_legacy_argv_document(self):
        selected = SimpleNamespace(ok=False)
        selector = Mock()
        selector.select.return_value = selected
        with patch.object(dashboard, "PracticeAttachment", return_value=selector) as attachment, \
                patch.object(dashboard.subprocess, "Popen") as spawn, self.assertRaises(ValueError):
            dashboard.LiveFeed(".local/legacy.json", dashboard.DashboardState("synthetic"))
        attachment.assert_called_once_with(".local/legacy.json", root=self.root)
        spawn.assert_not_called()

    def test_failed_spawn_or_thread_start_has_no_unowned_child_or_public_exception(self):
        for stage in ("spawn", "thread"):
            state = dashboard.DashboardState("synthetic")
            with self.subTest(stage=stage), patch.object(Path, "is_file", return_value=True), \
                    patch.object(dashboard.threading, "Thread") as thread, \
                    patch.object(dashboard.subprocess, "Popen", side_effect=OSError("PRIVATE-SPAWN")) as spawn:
                if stage == "thread":
                    thread.return_value.start.side_effect = RuntimeError("PRIVATE-THREAD")
                with self.assertRaises((OSError, RuntimeError)):
                    dashboard.LiveFeed(None, state, config=self.config)
                if stage == "thread":
                    spawn.assert_not_called()
                self.assertEqual(state.snapshot()["capture"]["state"], "disconnected")
                self.assertNotIn("PRIVATE", json.dumps(state.snapshot()))

    def test_drain_thread_not_ended_cannot_publish_into_a_later_session(self):
        state = dashboard.DashboardState("synthetic")
        process = Mock(stdout=io.BytesIO(), stderr=io.BytesIO())
        process.poll.return_value = 0
        with patch.object(Path, "is_file", return_value=True), patch.object(dashboard.subprocess, "Popen", return_value=process), \
                patch.object(dashboard.threading, "Thread") as thread:
            thread.return_value.is_alive.return_value = True
            feed = dashboard.LiveFeed(None, state, config=self.config)
            with self.assertRaises(OSError):
                feed.stop()
            self.assertEqual(state.snapshot()["message"], "feed-stop-failed")
            thread.return_value.is_alive.return_value = False
            feed.stop()

    def test_stderr_and_private_diagnostics_keep_a_bounded_prefix(self):
        state = dashboard.DashboardState("synthetic")
        process = Mock(stdout=io.BytesIO(), stderr=io.BytesIO(b"PRIVATE-DETAIL\n" * 205))
        process.poll.return_value = 0
        with patch.object(Path, "is_file", return_value=True), patch.object(dashboard.subprocess, "Popen", return_value=process), \
                patch.object(dashboard.threading, "Thread") as thread:
            thread.return_value.is_alive.return_value = False
            feed = dashboard.LiveFeed(None, state, config=self.config)
            feed._read_errors()
            self.assertEqual(feed.error.count, dashboard.MAX_DIAGNOSTICS)
            self.assertFalse(feed.error.complete)
            self.assertLessEqual(feed.error.path.stat().st_size, dashboard.MAX_DIAGNOSTIC_BYTES)
            self.assertEqual(len(feed.error.path.read_text().splitlines()), 200)
            feed.stop()
        self.assertNotIn("PRIVATE", json.dumps(state.snapshot()))
        ledger = dashboard.PrivateLedger(self.root / ".local/byte-cap.jsonl", max_events=200, max_bytes=1024 * 1024)
        ledger.append({"code": "prefix"})
        before = ledger.path.read_bytes()
        ledger.append({"details": "x" * (1024 * 1024)})
        ledger.close()
        self.assertEqual(ledger.path.read_bytes(), before)
        self.assertFalse(ledger.complete)

    def test_private_journal_write_or_close_failure_preserves_acknowledged_prefix(self):
        ledger = dashboard.PrivateLedger(self.root / ".local/failure-prefix.jsonl")
        ledger.append({"code": "prefix"})
        prefix = ledger.path.read_bytes()
        counts = ledger.count, ledger.bytes
        ledger.close()
        ledger.stream = Mock()
        ledger.stream.write.side_effect = OSError("PRIVATE-WRITE-ERROR")
        ledger.stream.close.side_effect = OSError("PRIVATE-CLOSE-ERROR")
        ledger.append({"code": "next"})
        ledger.close()
        self.assertFalse(ledger.complete)
        self.assertEqual((ledger.count, ledger.bytes), counts)
        self.assertEqual(ledger.path.read_bytes(), prefix)


class FakeSelection:
    def __init__(self, key=("coinpoker.exe", 42, "0x100000001"), *, ok=True, reason="ready", **details):
        self.ok, self.code = ok, reason
        self.key = key if ok else None
        self.config = {"binary": "target/debug/coinpoker.exe", "exe_name": "CoinPoker.exe", "pid": key[1],
                       "window_hwnd": key[2], "window_title": "NLH", "record_dir": ".local/captures",
                       "record_max_frames": 7200, "record_max_bytes": 1073741824, "record_interval_ms": 500}
        self.private_diagnostics = {"title": "PRIVATE-TITLE", "profile_path": "PRIVATE-PATH", **details}


class FakeSelector:
    def __init__(self):
        self.result = FakeSelection()
        self.calls = 0

    def select(self):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeFeed:
    def __init__(self, state, events):
        self.state, self.events = state, events
        self.running = True
        self.stops = 0
        state.begin_stream()
        events.append("start")

    def is_running(self):
        return self.running

    def stop(self):
        self.running = False
        self.stops += 1
        self.events.append("stop")


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=dashboard.ROOT / ".local")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        root_patch = patch.object(dashboard, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.state = dashboard.DashboardState("synthetic")
        self.selector = FakeSelector()
        self.events, self.feeds, self.configs = [], [], []

        def factory(path, state, *, config):
            self.assertIsNone(path)
            self.assertIs(state, self.state)
            self.assertTrue(all(not feed.running for feed in self.feeds), "never overlap capture children")
            self.configs.append(dict(config))
            feed = FakeFeed(state, self.events)
            self.feeds.append(feed)
            return feed

        self.auto = dashboard.AutoAttachFeed(".local/selector.json", self.state, selector=self.selector, feed_factory=factory)
        self.addCleanup(self.auto.stop)

    def ready(self):
        self.state.set_model("ready", floors_loaded=True)
        self.auto.poll()

    def test_model_wait_skips_all_selection_and_spawn_until_ready(self):
        for state in ("disabled", "loading", "failed"):
            self.state.set_model(state)
            self.auto.poll()
            self.assertEqual(self.selector.calls, 0)
            self.assertEqual(self.feeds, [])
        self.ready()
        self.assertEqual(len(self.feeds), 1)
        self.state.set_busy(True)
        self.auto.poll()
        self.assertEqual(len(self.feeds), 1)
        self.state.set_model("failed")
        self.auto.poll()
        self.assertEqual(self.feeds[0].stops, 1)
        self.ready()
        self.assertEqual(len(self.feeds), 1, "model changes cannot reset an attempted recorder identity")

    def test_same_key_resize_title_or_seating_retains_session_history_and_recording_cap(self):
        self.ready()
        session = self.state.session_id
        self.state.history["events"] = [{"kind": "gap", "sequence": 1}]
        self.state.capture.update(frames=7201, recorded_frames=7200, recorded_bytes=10000,
                                  recording_enabled=True, recording_status="count_limit", recording_complete=False)
        for n in range(500):
            self.selector.result = FakeSelection(width=800 + n, height=600, role=("observing", "your_turn")[n % 2],
                                                  title="PRIVATE-CHANGING-TITLE-" + str(n))
            self.auto.poll()
        self.assertEqual(len(self.feeds), 1)
        self.assertEqual(self.feeds[0].stops, 0)
        self.assertEqual(self.state.session_id, session)
        self.assertEqual(self.state.snapshot()["history"]["events"], [{"kind": "gap", "sequence": 1}])
        self.assertEqual(self.state.snapshot()["capture"]["recorded_frames"], 7200)
        self.assertFalse(self.state.snapshot()["capture"]["recording_complete"])
        self.assertEqual(self.auto.diagnostics.count, 2)
        self.assertEqual(self.configs[0]["record_interval_ms"], 500)
        self.assertNotIn("PRIVATE", json.dumps(self.state.snapshot()))

    def test_absent_ambiguous_or_invalid_selector_stops_and_clears_without_losing_prefix(self):
        for reason in ("table-target-absent", "table-target-ambiguous", "practice-profile-invalid"):
            self.ready()
            feed = self.feeds[-1]
            session = self.state.session_id
            self.state.history["events"] = [{"kind": "gap"}]
            self.state.capture.update(recorded_frames=3, recorded_bytes=300, recording_complete=True)
            self.state.observation = {"controls": [{"action": "call"}]}
            self.selector.result = FakeSelection(ok=False, reason=reason)
            self.auto.poll()
            self.assertEqual(feed.stops, 1)
            snapshot = self.state.snapshot()
            self.assertIsNone(snapshot["observation"])
            self.assertIsNone(snapshot["advice"])
            self.assertEqual(snapshot["history"]["events"], [{"kind": "gap"}])
            self.assertEqual(snapshot["capture"]["recorded_frames"], 3)
            self.assertFalse(snapshot["capture"]["recording_complete"])
            self.assertEqual(self.state.session_id, session)
            next_pid = 43 + len(self.feeds)
            self.selector.result = FakeSelection(("coinpoker.exe", next_pid, hex(next_pid)))

    def test_new_identity_stops_before_start_old_identity_is_not_retried(self):
        self.ready()
        first_session = self.state.session_id
        self.selector.result = FakeSelection(("coinpoker.exe", 43, "0x2"))
        self.auto.poll()
        self.assertEqual(self.events, ["start", "stop", "start"])
        self.assertNotEqual(first_session, self.state.session_id)
        self.selector.result = FakeSelection()
        self.auto.poll()
        self.assertEqual(self.events, ["start", "stop", "start", "stop"])
        self.assertEqual(len(self.feeds), 2)
        self.assertEqual(self.state.snapshot()["message"], "attach-retry-suppressed")

    def test_selector_keys_are_opaque_including_a_profile_digest_if_supplied(self):
        for key in (("coinpoker.exe", 42, "0x1", "digest-a"), ("coinpoker.exe", 42, "0x1", "digest-b")):
            self.selector.result = FakeSelection(key)
            self.ready()
            self.auto.poll()
        self.assertEqual(self.events, ["start", "stop", "start"])

    def test_crash_is_latched_once_with_no_restart_new_run_or_diagnostic_flood(self):
        self.ready()
        session = self.state.session_id
        self.feeds[0].running = False
        for _ in range(1000):
            self.auto.poll()
        self.assertEqual(len(self.feeds), 1)
        self.assertEqual(self.feeds[0].stops, 1)
        self.assertEqual(self.state.session_id, session)
        self.assertLessEqual(self.auto.diagnostics.count, 4)
        self.assertEqual(self.state.snapshot()["message"], "attach-retry-suppressed")

    def test_failed_start_consumes_identity_and_never_exposes_exception_or_paths(self):
        def failed(path, state, *, config):
            state.begin_stream()
            raise OSError("PRIVATE-PATH PRIVATE-EXCEPTION")

        self.auto.feed_factory = Mock(side_effect=failed)
        self.ready()
        session = self.state.session_id
        for _ in range(1000):
            self.auto.poll()
        self.auto.feed_factory.assert_called_once()
        self.assertEqual(self.state.session_id, session)
        self.assertIsNone(self.auto.feed)
        self.assertNotIn("PRIVATE", json.dumps(self.state.snapshot()))
        self.assertLessEqual(self.auto.diagnostics.count, 3)

    def test_selector_exception_cannot_keep_capture_or_leak_exception_details(self):
        self.ready()
        self.selector.result = OSError("PRIVATE-PATH PRIVATE-TITLE")
        self.auto.poll()
        self.assertEqual(self.feeds[0].stops, 1)
        self.assertEqual(self.state.snapshot()["message"], "attach-selection-failed")
        self.assertNotIn("PRIVATE", json.dumps(self.state.snapshot()))

    def test_failed_stop_never_loses_ownership_or_starts_a_second_child(self):
        self.ready()
        feed = self.feeds[0]
        original = feed.stop
        feed.stop = Mock(side_effect=OSError("PRIVATE-STOP-ERROR"))
        self.selector.result = FakeSelection(("coinpoker.exe", 43, "0x2"))
        self.auto.poll()
        self.auto.poll()
        self.assertIs(self.auto.feed, feed)
        self.assertTrue(self.auto.closed.is_set())
        self.assertEqual(len(self.feeds), 1)
        self.assertNotIn("PRIVATE", json.dumps(self.state.snapshot()))
        feed.stop = original

    def test_attempts_and_private_diagnostics_have_fixed_memory_record_and_byte_bounds(self):
        self.state.set_model("ready")
        for pid in range(1, 301):
            self.selector.result = FakeSelection(("coinpoker.exe", pid, hex(pid)))
            self.auto.poll()
        self.assertEqual(len(self.feeds), 200)
        self.assertEqual(len(self.auto.attempted), 200)
        self.assertEqual(len(self.auto.diagnosed), 200)
        self.assertLessEqual(self.auto.diagnostics.count, 200)
        self.assertLessEqual(self.auto.diagnostics.path.stat().st_size, 1024 * 1024)
        self.assertFalse(self.auto.diagnostics.complete)
        self.assertNotIn("PRIVATE", json.dumps(self.state.snapshot()))

    def test_start_and_stop_are_idempotent_and_only_own_their_fake_feed(self):
        with patch.object(dashboard.threading, "Thread") as thread:
            self.auto.start()
            self.auto.start()
            thread.assert_called_once()
            thread.return_value.start.assert_called_once()
            self.ready()
            self.auto.stop()
            self.auto.stop()
            self.auto.poll()
            self.assertEqual(self.feeds[0].stops, 1)
            self.assertEqual(len(self.feeds), 1)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.service = server.Service("coinpoker-laya-vision")
        self.httpd = server.BoundedHTTPServer(("127.0.0.1", 0),
                                             server.make_handler(None, self.service.alias, {}, None, self.service))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def request(self, path, data=None, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, headers=headers or {})
        try:
            response = urllib.request.urlopen(req, timeout=2)
        except urllib.error.HTTPError as e:
            response = e
        with response:
            return response.status, response.read(), response.headers

    def test_status_available_without_model_and_no_advice(self):
        status, data, headers = self.request("/api/state")
        self.assertEqual(status, 200)
        state = json.loads(data)
        self.assertEqual(state["server"]["model_state"], "disabled")
        self.assertIsNone(state["advice"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("/v1/models")[0], 503)

    def test_origin_host_and_mutation_paths_fail_closed(self):
        for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Origin": "null"}):
            self.assertEqual(self.request("/api/state", headers=headers)[0], 403)
        self.assertEqual(self.request("/api/start", b"{}")[0], 404)
        self.assertEqual(self.request("/api/state", b"{}")[0], 404)

    def test_assets_whitelist_and_no_arbitrary_files(self):
        for path in ("/../laya-pins.json", "/%2e%2e/laya-pins.json", "/api/state?file=secret"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/api/reference")[0], 200)
        self.assertEqual(self.request("/api/replay")[0], 404)

    def test_json_only_model_not_ready(self):
        self.assertEqual(self.request("/v1/laya/predict", b"{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/v1/laya/predict", b"{}", {"Content-Type": "application/json"})[0], 503)

    def test_slow_prediction_does_not_block_status_and_busy_is_bounded(self):
        entered, release = threading.Event(), threading.Event()
        self.service.engine = object()

        def slow(*_):
            entered.set()
            release.wait(3)
            return 200, {"answers": {}}

        with patch.object(server, "handle_predict", side_effect=slow), concurrent.futures.ThreadPoolExecutor() as pool:
            first = pool.submit(self.request, "/v1/laya/predict", b"{}", {"Content-Type": "application/json"})
            try:
                self.assertTrue(entered.wait(2))
                start = time.monotonic()
                status, data, _ = self.request("/api/state")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(data)["server"]["inference_busy"])
                self.assertLess(time.monotonic() - start, 0.5)
                self.assertEqual(self.request("/v1/laya/predict", b"{}", {"Content-Type": "application/json"})[0], 503)
            finally:
                release.set()
            self.assertEqual(first.result()[0], 200)


if __name__ == "__main__":
    unittest.main()
