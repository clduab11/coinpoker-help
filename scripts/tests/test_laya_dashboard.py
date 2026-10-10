import concurrent.futures
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

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
                                  "captured_at_ms": 123},
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
            self.assertEqual(reading["amounts"]["hero_chips"], 1000 if required is False else None)
            self.assertEqual(reading["action_required"], False if required is False else None)

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
                "trusted": True, "full_raise": True, "preflop_raise_ordinal": 3, "name": "PRIVATE"}
        actions = [base, {**base, "preflop_raise_ordinal": 4},
                   {**base, "preflop_raise_ordinal": None}, {**base, "preflop_raise_ordinal": True},
                   {**base, "preflop_raise_ordinal": 1}, {**base, "preflop_raise_ordinal": 10001},
                   {**base, "kind": "call"}, {**base, "trusted": False},
                   {**base, "full_raise": False}, {**base, "forced": "big_blind"}]
        events = [{"event": "action", "event_sequence": sequence, "street": "preflop", "action": action}
                  for sequence, action in enumerate(actions, 1)]
        events += [{"event": "action", "event_sequence": 11, "street": "flop", "action": base},
                   {"event": ["PRIVATE"], "event_sequence": 12}]
        self.state.ingest({"schema_version": 2, "event": "history", "summary": {
            "events": events, "counts": {"folds": True, "bets": -1, "raises": "9", "three_bets": 1, "four_bets": 1}}})
        history = self.state.snapshot()["history"]
        self.assertEqual([event["preflop_raise_ordinal"] for event in history["events"]], [3, 4] + [None] * 10)
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
