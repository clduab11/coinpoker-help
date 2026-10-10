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

from scripts.tests.test_laya_dashboard import Clock, IDENTITY, dashboard


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
            seat["street_contribution"] = 999
        for item in source["capabilities"]:
            if item["field"] == "visible_wager":
                item.update(training="read_only_approved", acceptance_floor=.999,
                            held_out_approved=True, human_verified=True,
                            provenance="observation-only-calibrated-pass")
        self.state.ingest(source)
        view = self.state.snapshot()["partial_observation"]
        self.assertEqual([s["visible_wager"] for s in view["seats"]], [7, 14, 21, 28, 35, 42])
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
        self.assertIsNone(value["board_count"])
        self.assertEqual(value["board_slots"], [None] * 5)
        self.assertEqual(value["pot_size"], 12345)
        self.state.begin_stream()
        self.health()
        value = self.reading(game_phase="preflop", board_count=None)
        self.assertIsNone(value["game_phase"])
        self.assertEqual(value["board_slots"], [None] * 5)
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


NODE_UI = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const input = JSON.parse(process.argv[1]), source = fs.readFileSync(input.app, 'utf8');
const html = fs.readFileSync(input.html, 'utf8');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.childNodes = []; this.dataset = {}; this.attrs = {}; this.hidden = false;
    this.value = ''; this.listeners = {}; this.classes = new Set(); this._text = '';
    this.classList = { toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name),
      add: (name) => this.classes.add(name), contains: (name) => this.classes.has(name) }; }
  set className(value) { this.classes = new Set(value.split(/\s+/)); } get className() { return [...this.classes].join(' '); }
  set textContent(value) { this._text = String(value); this.childNodes = []; }
  get textContent() { return this._text + this.childNodes.map(x => x.textContent).join(''); }
  append(...items) { for (const item of items) item.tagName === '#fragment' ? this.append(...item.childNodes) : this.childNodes.push(item); }
  replaceChildren(...items) { this._text = ''; this.childNodes = []; this.append(...items); }
  setAttribute(name, value) { this.attrs[name] = String(value); } getAttribute(name) { return this.attrs[name]; }
  addEventListener(name, callback) { this.listeners[name] = callback; } focus() {}
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
  createElement: tag => new Element(tag), createDocumentFragment: () => new Element('#fragment'), addEventListener() {} };
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
const visible = () => !nodes.get('monitor-readings').hidden;
accept(input.snapshot);
if (input.scenario === 'render') {
  assert(visible()); assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
  const seats = nodes.get('seat-readings').childNodes;
  assert.equal(seats.length, 6); assert.deepEqual(seats.map(s => s.dataset.seat), ['1','2','3','4','5','6']);
  for (const row of seats) for (const label of ['Displayed stack', 'Visible wager', 'Street contribution']) assert(row.textContent.includes(label));
  assert(seats[3].textContent.includes('0.00 chips')); assert(!seats[2].textContent.includes('0.00 chips'));
  assert.equal(nodes.get('board-cards').childNodes.length, 3);
  assert(nodes.get('metrics-readings').hidden); assert(nodes.get('controls-reading').hidden);
  assert(nodes.get('call-reading').hidden); assert(nodes.get('reading-limit').textContent.includes('untrained'));
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
} else if (input.scenario === 'capture-rewrite') {
  const rewritten = structuredClone(input.snapshot); rewritten.event_seq += 1;
  rewritten.partial_observation.captured_at_unix_ms += 1; accept(rewritten); assert(!visible());
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

    def run_ui(self, scenario, snapshot=None):
        payload = {"scenario": scenario, "snapshot": snapshot or self.snapshot,
                   "app": str(dashboard.ROOT / "scripts/dashboard/app.js"),
                   "html": str(dashboard.ROOT / "scripts/dashboard/index.html")}
        result = subprocess.run(["node", "-e", NODE_UI, json.dumps(payload)], text=True, encoding="utf-8",
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
