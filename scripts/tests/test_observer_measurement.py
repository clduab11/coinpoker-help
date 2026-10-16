"""Finite offline observer collector/analysis checks; no runtime or client access."""

import argparse
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("observer_measurement", ROOT / "scripts/measure_observer.py")
measurement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measurement)


def capture(stamp=1000, sequence=1):
    return {"service_instance_id": "service", "session_id": "feed", "capture_session_id": "a" * 32,
        "source_id": "source", "epoch": 1, "sequence": sequence, "captured_at_ms": stamp + 900000,
        "captured_at_unix_ms": stamp, "sha256": "f" * 64, "width": 939, "height": 714}


def state(stamp=1000, sequence=1):
    original = capture(stamp, sequence)
    return {"schema_version": 1, "session_id": "feed", "server": {"instance_id": "service"},
        "capture_session": {"session_id": "a" * 32, "status": "running"},
        "capture": {"source_id": "source", "epoch": 1, "state": "available"},
        "table_context": {"capture": original, "role": "observing", "hero_seat": None,
            "requested_at_unix_ms": stamp, "attempt_started_at_unix_ms": stamp + 1,
            "completed_at_unix_ms": stamp + 2, "processing_ms": 1, "table_context_id": "table",
            "seats": [{"seat": seat, "occupancy": "occupied", "identity": f"Player{seat}",
                "occupant_epoch": 1, "continuity": "confirmed", "status": "confirmed", "stats": None}
                for seat in range(1, 7)], "events": [],
            "evidence": {"complete": True, "role": {"origin": "observer_controls", "capture": original}}}}


def profile(original=None):
    original = original or capture()
    return {"source": "client_profile_tooltip", "owner": "Player1", "seat": 1, "occupant_epoch": 1,
        "capture": original, "captured_at_unix_ms": original["captured_at_unix_ms"], "evidence_id": "f" * 64,
        "sample_size": None, "scope": None, "status": "provisional",
        "metrics": {"vpip": {"label": "VPIP", "literal": "0%", "percent": 0, "status": "accepted"},
            "pfr": {"label": "PFR", "literal": "12.5%", "percent": 12.5, "status": "accepted"},
            "three_bet": {"label": "3-BET", "literal": "-", "percent": None, "status": "dash"},
            "c_bet": {"label": "C-BET", "literal": None, "percent": None, "status": "missing"}}}


def sample(value, sampled=None):
    return {"state": value, "sampled_at_unix_ms": sampled if sampled is not None else
            value["table_context"]["capture"]["captured_at_unix_ms"] + 3}


def run(end=50000):
    return {"session": "a" * 32, "service_instance": "service", "api_session": "feed",
        "source_id": "source", "source_epoch": 1, "started_at_unix_ms": 1000,
        "ended_at_unix_ms": end, "poll_ms": 1000}


class HermeticImportTests(unittest.TestCase):
    def test_clean_imports_without_private_implementation_or_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tests = root / "scripts/tests"
            tests.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/measure_observer.py", root / "scripts/measure_observer.py")
            test_path = tests / Path(__file__).name
            shutil.copy2(__file__, test_path)
            code = """
import importlib.util
from pathlib import Path
import sys
import numpy
from PIL import Image

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('clean_measurement_tests', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.measurement.ROOT == path.parents[2]
assert module.measurement.PRIVATE == path.parents[2] / '.local'
assert not module.measurement.PRIVATE.exists()
module.measurement.measurement_self_test()
assert not module.measurement.PRIVATE.exists()
"""
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(test_path)],
                cwd=root, capture_output=True, text=True, check=False, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((root / ".local").exists())
            self.assertEqual(list(root.rglob("__pycache__")), [])


class MeasurementTests(unittest.TestCase):
    def test_strict_deadline_and_censored_edges(self):
        exact = measurement.series([{"t": 11000}, {"t": 21000}], "t", 1000, 31000)
        self.assertEqual(exact["gaps_gt_10000ms"], 0)
        self.assertEqual(exact["censored_edges_gt_10000ms"], 0)
        over = measurement.series([{"t": 11001}, {"t": 21002}], "t", 1000, 31003)
        self.assertEqual(over["gaps_gt_10000ms"], 1)
        self.assertEqual(over["censored_edges_gt_10000ms"], 2)
        self.assertEqual(over["missed_10000ms_deadlines_including_censored_edges"], 3)
        empty = measurement.interval_report([], "t", 1000, 31003)
        self.assertEqual(empty["coverage"], "NOT OBSERVED")
        self.assertEqual(empty["deadline_result"], "UNKNOWN")

    def test_context_receipts_dedup_without_hash_only_dedup(self):
        rows = [(1, sample(state())), (2, sample(state(), 1500)), (3, sample(state(11000, 2))),
                (4, sample(state(21001, 3)))]
        result = measurement.analyze_context(rows, run())
        for seat in result["seats"].values():
            wall = seat["context"]["attempted_source_wall"]
            self.assertEqual(wall["count"], 3)
            self.assertEqual(wall["intervals_ms"], [10000, 10001])
            self.assertEqual(wall["gaps_gt_10000ms"], 1)
            self.assertEqual(seat["occupancy"]["accepted_source"]["count"], 3)
        self.assertEqual(result["role"]["accepted_source"]["count"], 3)
        self.assertEqual(result["test_result"], "UNKNOWN")

    def test_exact_source_namespaces_and_clock_types(self):
        for field in measurement.CAPTURE_KEYS[:5]:
            value = state()
            value["table_context"]["capture"] = {**capture(), field: 2 if field == "epoch" else "other"}
            result = measurement.analyze_context([(0, sample(value))], run())
            self.assertEqual(result["contexts"]["attempted_source_wall"]["count"], 0, field)
            self.assertTrue(result["rejected_records"], field)
        for field, invalid in (("sequence", True), ("width", False), ("sha256", "bad"), ("captured_at_ms", 1.5)):
            with self.assertRaises(ValueError):
                measurement.capture_key({**capture(), field: invalid})

    def test_missing_work_clocks_and_unknown_seats_are_not_attempt_start_proof(self):
        value = state()
        context = value["table_context"]
        for key in measurement.CLOCK_KEYS[:3]:
            del context[key]
        context["seats"][1].update(identity=None, occupancy="unknown", status="unknown", continuity="uncertain")
        context["hero_seat"] = 4
        result = measurement.analyze_context([(0, sample(value))], run())
        self.assertEqual(result["seats"]["2"]["context"]["attempt_starts"]["count"], 0)
        self.assertEqual(result["seats"]["2"]["identity"]["accepted_source"]["count"], 0)
        self.assertEqual(result["rejected_records"]["hero-while-observing"], 1)
        self.assertEqual(result["role"]["accepted_source"]["count"], 0)

    def test_profile_closure_keeps_original_and_atomic_metric_unknowns(self):
        opened = state()
        opened["table_context"]["seats"][0]["stats"] = profile()
        closed = state(2000, 2)
        closed["table_context"]["seats"][0]["stats"] = {**profile(), "status": "last_observed"}
        closed["table_context"]["profile"] = {"status": "closed", "detected": False}
        result = measurement.analyze_context([(0, sample(opened)), (1, sample(closed)),
            (2, sample(closed, 2500))], run(3000))
        imported = result["seats"]["1"]["profile"]
        self.assertEqual(imported["imports"]["count"], 1)
        self.assertEqual(imported["import_events"][0]["captured_at_unix_ms"], 1000)
        self.assertEqual(imported["import_events"][0]["stats"]["metrics"]["vpip"]["percent"], 0)
        self.assertEqual(imported["unknown_scope_imports"], 1)
        self.assertEqual(imported["unknown_sample_size_imports"], 1)
        self.assertEqual(result["sample_counts"]["profile_status_closed"], 2)

    def test_non_atomic_popup_keeps_child_original_and_exact_parent_proof(self):
        parent = capture()
        child = {**parent, "captured_at_unix_ms": 1002, "captured_at_ms": parent["captured_at_ms"] + 2,
            "sha256": "e" * 64, "width": 320, "height": 240, "parent_capture": parent,
            "non_atomic": True, "popup_index": 0, "popup_window": {"hwnd": 123, "owner_hwnd": 45}}
        value = state()
        value["table_context"]["seats"][0]["stats"] = profile(child)
        projected, audit = measurement.CompactProjection().project(value)
        self.assertTrue(audit["complete"])
        self.assertEqual(projected["table_context"]["seats"][0]["stats"]["capture"], child)
        result = measurement.analyze_context([(0, sample(projected))], run())
        imported = result["seats"]["1"]["profile"]["import_events"]
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["captured_at_unix_ms"], 1002)
        self.assertNotEqual(measurement.capture_key(child), measurement.capture_key({**child, "popup_index": 1}))
        bad = copy.deepcopy(value)
        bad["table_context"]["seats"][0]["stats"]["capture"]["parent_capture"]["source_id"] = "other"
        rejected = measurement.analyze_context([(0, sample(bad))], run())["seats"]["1"]["profile"]
        self.assertEqual(rejected["imports"]["count"], 0)
        self.assertIn("popup-parent-scope-or-clock", rejected["rejected_samples"])

    def test_stats_reject_replacement_uncertainty_source_and_timestamp_renewal(self):
        mutations = [lambda seat: seat.update(identity="Replacement", occupant_epoch=2),
            lambda seat: seat.update(identity=None, continuity="uncertain"),
            lambda seat: seat["stats"].update(captured_at_unix_ms=2000),
            lambda seat: seat["stats"].update(source="local_history"),
            lambda seat: seat["stats"]["capture"].update(capture_session_id="b" * 32),
            lambda seat: seat["stats"].update(table_context_id="other")]
        for mutate in mutations:
            value = state(2000, 2)
            seat = value["table_context"]["seats"][0]
            seat["stats"] = profile()
            mutate(seat)
            data = measurement.analyze_context([(0, sample(value))], run())["seats"]["1"]["profile"]
            self.assertEqual(data["imports"]["count"], 0)
            self.assertTrue(data["rejected_samples"])

    def test_duplicate_identity_and_conflicting_original_metrics_rejected(self):
        first = state()
        first["table_context"]["seats"][0]["stats"] = profile()
        collision = copy.deepcopy(first)
        collision["table_context"]["seats"][1]["identity"] = "Player1"
        result = measurement.analyze_context([(0, sample(collision))], run())
        self.assertEqual(result["seats"]["1"]["profile"]["imports"]["count"], 0)
        changed = copy.deepcopy(first)
        changed["table_context"]["seats"][0]["stats"]["metrics"]["vpip"]["percent"] = 25
        result = measurement.analyze_context([(0, sample(first)), (1, sample(changed, 1500))], run())
        self.assertEqual(result["seats"]["1"]["profile"]["imports"]["count"], 0)

    def test_gapped_samples_do_not_hold_state_across_unobserved_period(self):
        result = measurement.analyze_context([(0, sample(state(), 1000)),
            (1, sample(state(21000, 2), 21000))], run(22000))
        duration = result["seats"]["1"]["poll_bounded_duration"]["occupancy"]
        self.assertEqual(duration["known_ms"], 3000)
        self.assertEqual(duration["unobserved_ms"], 18000)

    def test_event_changes_completeness_conflicts_and_closure_counter_boundary(self):
        first, second = state(), state(2000, 2)
        event = {"event_id": "event", "kind": "table-context", "capture": capture(), "evidence_id": "f" * 64,
                 "evidence": {"complete": False}, "changes": [{"kind": "replacement", "seat": 2}]}
        first["table_context"]["events"] = [event]
        second["table_context"]["events"] = [{**event, "evidence": {"complete": True}}]
        first["event_evidence"] = {"complete": True, "bytes": 10, "closure_count": 1}
        second["event_evidence"] = {"complete": False, "bytes": 9, "closure_count": 2}
        later = state(4000, 3)
        later["event_evidence"] = {"complete": True, "bytes": 50, "closure_count": 99}
        result = measurement.analyze_context([(0, sample(first)), (1, sample(second)), (2, sample(later))], run(3000))
        self.assertEqual(result["event_change_kind_counts"], {"replacement": 1})
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["event_evidence"]["statuses"]["COMPLETE_REPORTED_NOT_CONTENT_AUDITED"], 1)
        evidence = result["producer_evidence"]
        self.assertEqual(evidence["latest_collected"]["event_evidence"]["status"]["closure_count"], 2)
        self.assertEqual(len(evidence["counter_regressions"]), 1)
        self.assertTrue(evidence["incomplete_reported"])
        second["table_context"]["events"][0]["capture"] = capture(2000, 2)
        conflicted = measurement.analyze_context([(0, sample(first)), (1, sample(second))], run(3000))
        self.assertEqual(conflicted["event_kind_counts"], {})

    def test_typed_case_coverage_and_bad_change_source_do_not_become_passes(self):
        value = state()
        value["table_context"]["events"] = [{"event_id": "event", "kind": "table-context", "capture": capture(),
            "evidence_id": "f" * 64, "evidence_complete": True, "changes": [
                {"kind": "occupant_confirmed", "capture": capture()},
                {"kind": "profile_import", "capture": {**capture(), "capture_session_id": "other"}}]}]
        result = measurement.analyze_context([(0, sample(value))], run())
        coverage = result["case_coverage"]
        self.assertEqual(coverage["occupant_confirmed"]["coverage"], "OBSERVED")
        self.assertEqual(coverage["profile_import"]["coverage"], "NOT OBSERVED")
        self.assertEqual(coverage["occupant_replaced"]["test_result"], "UNKNOWN")
        self.assertEqual(result["event_evidence"]["statuses"], {"INCOMPLETE": 1})

    def test_ui_original_and_dom_publication_stay_separate(self):
        receipt = {"field": "identity", "seat": 1, "value": "Player1", "status": "confirmed",
                   "capture": capture(), "published_at_unix_ms": 1100, "published_at_monotonic_ms": 123}
        receipts = [receipt, receipt, {**receipt, "published_at_unix_ms": 1200},
            {**receipt, "status": "last_seen", "published_at_unix_ms": 1500},
            {**receipt, "capture": capture(2000, 2), "published_at_unix_ms": 2100},
            {**receipt, "published_at_unix_ms": 6000}]
        result = measurement.analyze_context([(0, sample(state()))], run(5000), receipts)["ui"]
        self.assertEqual(result["counts"]["accepted_publications"], 2)
        self.assertEqual(result["counts"]["duplicate_export_records"], 1)
        self.assertEqual(result["counts"]["unchanged_original_republished"], 1)
        self.assertEqual(result["rejected_records"]["ui-original-not-in-collected-window"], 1)
        self.assertEqual(result["fields"][0]["distinct_original_captures"]["count"], 1)
        self.assertEqual(result["publications"][0]["source_to_dom_publication_ms"], 100)

    def test_native_context_attempts_are_explicit_and_do_not_retrofill_ui(self):
        rows = [(1, {"event": "context_attempt", "capture": capture(stamp, sequence),
            "requested_at_unix_ms": stamp, "attempt_started_at_unix_ms": stamp + 1,
            "completed_at_unix_ms": stamp + 2, "error": "ocr-failed" if sequence == 2 else None})
            for sequence, stamp in ((1, 1000), (2, 11000), (3, 21001))]
        rows.append((2, {**rows[0][1], "requested_at_unix_ms": 1500, "attempt_started_at_unix_ms": 1501,
                         "completed_at_unix_ms": 1502}))
        receipt = {"field": "identity", "seat": 1, "capture": capture(11000, 2), "published_at_unix_ms": 12000}
        result = measurement.analyze_context([(0, sample(state()))], run(), [receipt], native_attempts=rows)
        native = result["native_context_attempts"]
        self.assertEqual(native["attempted_source_wall"]["count"], 3)
        self.assertEqual(native["attempt_starts"]["count"], 4)
        self.assertEqual(native["attempted_source_wall"]["gaps_gt_10000ms"], 1)
        self.assertEqual(result["ui"]["rejected_records"]["ui-original-not-in-collected-window"], 1)

    def test_compact_projection_omits_histories_and_only_emits_event_changes(self):
        value = state()
        value["history"] = {"events": ["unused"] * 10000}
        event = {"event_id": "event", "kind": "table-context", "capture": capture(),
                 "evidence": {"complete": False}}
        value["table_context"]["events"] = [event]
        projector = measurement.CompactProjection()
        first, audit = projector.project(value)
        second, _ = projector.project(value)
        self.assertNotIn("history", first)
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["table_context"]["capture"], capture())
        self.assertLess(len(measurement.dump(first)), len(measurement.dump(value)) // 2)
        self.assertTrue(audit["complete"])
        self.assertEqual(second["table_context"]["events"], [])
        event["evidence"]["complete"] = True
        third, audit = projector.project(value)
        self.assertEqual(len(third["table_context"]["events"]), 1)
        self.assertEqual(audit["event_counters"]["changed_events"], 1)

    def test_fast_numeric_originals_and_integer_event_ids_survive_compact_projection(self):
        value = state()
        ref = capture()
        reading = {"status": "provisional", "literal": "0.07", "value": 7, "capture": copy.deepcopy(ref),
                   "bounds": [1, 2, 20, 30], "crop_sha256": "a" * 64}
        value["numeric_observation"] = {"source": "cpu-visible-numeric", "provisional": True,
            "quality_approved": False, "capture": ref, "expires_at_unix_ms": 2500,
            "processing_ms": 40.5, "published_at_unix_ms": 1050, "pot": reading,
            "seats": [{"seat": i, "stack": copy.deepcopy(reading), "wager": copy.deepcopy(reading)} for i in range(1, 7)]}
        value["table_context"]["events"] = [{"event_id": 1, "kind": "visible-numeric-change", "capture": ref,
            "evidence_id": "f" * 64, "changes": [{"kind": "pot_change", "literal": "0.07", "value": 7}]}]
        projector = measurement.CompactProjection()
        projected, audit = projector.project(value)
        self.assertTrue(audit["complete"], audit)
        self.assertEqual(projected["numeric_observation"]["pot"], reading)
        self.assertEqual(projected["numeric_observation"]["processing_ms"], 40.5)
        self.assertEqual(projected["table_context"]["events"][0]["event_id"], 1)
        self.assertEqual(projector.project(value)[0]["table_context"]["events"], [])
        for invalid in (True, 0, 1.5):
            value["table_context"]["events"][0]["event_id"] = invalid
            self.assertFalse(projector.project(value)[1]["complete"])

    def test_projected_event_caps_are_explicit_not_capture_controls(self):
        value = state()
        value["table_context"]["events"] = [{"event_id": str(index), "capture": capture()} for index in range(4)]
        projected, audit = measurement.CompactProjection(event_limit=1, row_limit=2).project(value)
        self.assertEqual(len(projected["table_context"]["events"]), 1)
        self.assertEqual(projected["capture_session"]["status"], "running")
        self.assertFalse(audit["complete"])
        self.assertEqual(audit["event_counters"]["row_drops"], 2)
        self.assertEqual(audit["event_counters"]["event_drops"], 1)

    def test_declared_event_cursor_loss_and_regression_are_not_complete(self):
        value = state()
        value["table_context"].update(events_total=1, events=[{"event_id": "first", "capture": capture()}])
        projector = measurement.CompactProjection()
        self.assertTrue(projector.project(value)[1]["complete"])
        value["table_context"].update(events_total=3, events=[{"event_id": "third", "capture": capture()}])
        audit = projector.project(value)[1]
        self.assertFalse(audit["complete"])
        self.assertEqual(audit["event_counters"]["cursor_drops"], 1)
        value["table_context"]["events_total"] = 2
        audit = projector.project(value)[1]
        self.assertEqual(audit["event_counters"]["cursor_regressions"], 1)

    def test_confirmed_roles_at_each_physical_seat_and_provisional_roster_separation(self):
        for seat in range(1, 7):
            value = state()
            context = value["table_context"]
            context.update(role="your_turn", hero_seat=seat)
            context["evidence"]["role"].update(origin="own_action_controls", hero_seat=seat, status="provisional")
            context["seats"][seat - 1].update(status="provisional", continuity="uncertain")
            result = measurement.analyze_context([(0, sample(value))], run())
            self.assertEqual(result["role"]["events"][0]["hero_seat"], seat)
            self.assertEqual(result["seats"][str(seat)]["occupancy"]["accepted_source"]["count"], 0)
            self.assertEqual(result["seats"][str(seat)]["context"]["attempted_source_wall"]["count"], 1)

    def test_legacy_numeric_and_visual_current_fields_survive_projection(self):
        value = state()
        source = {key: capture()[key] for key in ("session_id", "source_id", "epoch", "sequence", "captured_at_ms")}
        visual = {**source, **{key: capture()[key] for key in
            ("service_instance_id", "captured_at_unix_ms", "sha256", "width", "height")},
            "board": {"candidate_cards": [], "reason": "unknown", "template_artifacts": {"version": 1}},
            "actions": {"capture": source, "processing_ms": 1,
                "seats": [{"seat": seat, **{family: {"source_capture": source, "status": "unknown", "value": None,
                    "crop_bounds": [0, 0, 1, 1], "crop_sha256": "a" * 64, "expires_at_ms": 2000}
                    for family in ("badge", "visible_wager")}} for seat in range(1, 7)]}, "sightings": []}
        reading = {"epoch": 1, "generation": 1, "captured_at_unix_ms": 1000, "expires_at_unix_ms": 6000,
            "seats": [{"seat": 1, "displayed_stack": {"literal": "0", "amount": 0}}],
            "field_statuses": {"seats.1.displayed_stack": {"status": "accepted", "reason": "source_current"}}}
        value.update(visual_observation=visual, partial_observation=reading)
        projected, _ = measurement.CompactProjection().project(value)
        self.assertEqual(projected["visual_observation"], visual)
        self.assertEqual(projected["partial_observation"], reading)

    def test_source_boundaries_are_not_role_transitions_or_temporary_context_absence(self):
        expected = measurement.sample_scope(state())
        changed = state()
        changed["table_context"].update(role="uncertain", hero_seat=None)
        self.assertIsNone(measurement.boundary_reason(measurement.sample_scope(changed), expected, "a" * 32))
        changed["table_context"] = None
        self.assertIsNone(measurement.boundary_reason(measurement.sample_scope(changed), expected, "a" * 32))
        for key in ("capture_session_id", "service_instance_id", "session_id", "source_id", "epoch", "table_context_id"):
            scope = {**expected, key: 2 if key == "epoch" else "other"}
            self.assertIsNotNone(measurement.boundary_reason(scope, expected, "a" * 32), key)

    def test_bounded_reads_partial_tails_and_frozen_closure_prefix(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(measurement, "ROOT", Path(directory)):
            path = Path(directory) / "rows.jsonl"
            prefix = b'{"value":1}\n'
            path.write_bytes(prefix + b'{"value":99}\n')
            metadata = []
            rows = measurement.read_rows(path, metadata, boundary_size=len(prefix))
            self.assertEqual(rows, [(0, {"value": 1})])
            self.assertFalse(metadata[0]["capped"])
            self.assertEqual(metadata[0]["sha256_of_scanned_prefix"], hashlib.sha256(prefix).hexdigest())
            path.write_bytes(prefix + b'{"value":2}')
            metadata = []
            measurement.read_rows(path, metadata, byte_limit=len(prefix) + 2)
            self.assertTrue(metadata[0]["capped"])
            self.assertTrue(metadata[0]["partial_tail"])
            path.write_bytes(b"invalid\n" * 4)
            metadata = []
            with patch.object(measurement, "ROW_LIMIT", 2):
                measurement.read_rows(path, metadata)
            self.assertEqual(metadata[0]["invalid_rows"], 2)
            self.assertTrue(metadata[0]["capped"])
            ui = Path(directory) / "ui.json"
            ui.write_text(json.dumps({"receipts": [], "dropped": 1, "capacity": 12000}))
            _, info = measurement.load_ui_receipts(ui, [])
            self.assertFalse(info["complete"])
            ui.write_text("[")
            _, info = measurement.load_ui_receipts(ui, [])
            self.assertTrue(info["partial_tail"])


class NativeTimingTests(unittest.TestCase):
    def fixture(self, stamp=1000, sequence=1, total=400):
        value = state(stamp, sequence)
        ref = {**capture(stamp, sequence), "generation": sequence}
        value["capture"].update(width=ref["width"], height=ref["height"], generation=sequence)
        timing = {"schema_version": 1, "generation": sequence, "epoch": 1,
            "captured_at_ms": ref["captured_at_ms"], "captured_at_unix_ms": stamp,
            "emitted_at_unix_ms": stamp + 100, "ingested_at_unix_ms": stamp + 200,
            "api_snapshot_at_unix_ms": stamp + 300}
        value.update(native_timing=timing, partial_observation={"generation": sequence, "epoch": 1,
            "captured_at_ms": ref["captured_at_ms"], "captured_at_unix_ms": stamp,
            "expires_at_unix_ms": stamp + 5000, "capture": ref, "field_captures": {}, "pot_size": 12345,
            "field_statuses": {"pot_size": {"status": "accepted"}, "seats.1.displayed_stack": {"status": "accepted"}},
            "seats": [{"seat": 1, "displayed_stack": 0}]})
        receipt = {"field": "pot_size", "seat": None, "value": "123.45 chips", "status": "current",
            "capture": copy.deepcopy(ref), "published_at_unix_ms": stamp + total,
            "published_at_monotonic_ms": 50.25, "native_timing": copy.deepcopy(timing)}
        return (0, sample(value, stamp + 350)), receipt

    def summarize(self, rows, receipts, manifest=None, info=None):
        return measurement.analyze_native_timing(rows, manifest or run(), receipts, info)

    def test_native_stage_units_first_publication_dedup_and_independent_api_polls(self):
        row, receipt = self.fixture()
        stack = {**receipt, "field": "seats.1.displayed_stack", "seat": 1, "value": "0.00 chips"}
        later = copy.deepcopy(row)
        later[1]["state"]["native_timing"]["api_snapshot_at_unix_ms"] += 100
        result = self.summarize([row, later, later], [receipt, stack, receipt,
            {**receipt, "published_at_unix_ms": 1500}, {**receipt, "status": "last-read"},
            {**receipt, "status": "provisional"}])
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["complete_stage_sample_count"], 2)
        self.assertEqual(result["counts"]["duplicate_publications"], 2)
        self.assertEqual(result["counts"]["excluded_non_current"], 2)
        for key, expected in (("capture_to_emit", 100), ("emit_to_ingest", 100),
                              ("ingest_to_api", 100), ("api_to_dom", 100), ("capture_to_dom", 400)):
            self.assertEqual(result["stages_ms"][key], {"count": 2, "min": expected, "max": expected, "p95": expected})
        self.assertEqual(len(result["fields"]), 2)
        self.assertFalse(result["complete_coverage"])
        self.assertEqual(result["quantile_method"], "nearest-rank ceil(0.95*n)")

    def test_native_nearest_rank_p95_strict_target_and_exact_window_boundaries(self):
        pairs = [self.fixture(1000 + i * 10000, i + 1, total=1000 + i * 100) for i in range(21)]
        result = self.summarize([p[0] for p in pairs], [p[1] for p in pairs], run(300000))
        self.assertEqual(result["stages_ms"]["capture_to_dom"]["p95"], 2900)
        self.assertTrue(result["observed_p95_below_3000_ms"])
        row, receipt = self.fixture(total=3000)
        result = self.summarize([row], [receipt], run(4000))
        self.assertEqual(result["sample_count"], 1)
        self.assertFalse(result["observed_p95_below_3000_ms"])
        self.assertEqual(self.summarize([row], [receipt], run(3999))["sample_count"], 0)
        row, receipt = self.fixture(stamp=999)
        self.assertEqual(self.summarize([row], [receipt])["sample_count"], 0)

    def test_native_missing_timing_does_not_backfill_from_later_republication(self):
        row, receipt = self.fixture()
        first = {key: value for key, value in receipt.items() if key != "native_timing"}
        result = self.summarize([row], [first, {**receipt, "published_at_unix_ms": 1500}])
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["complete_stage_sample_count"], 0)
        self.assertEqual(result["unknown_records"], {"missing-native-timing": 1})
        self.assertEqual(result["stages_ms"]["capture_to_dom"]["p95"], 400)
        self.assertIsNone(result["stages_ms"]["api_to_dom"]["p95"])
        empty = self.summarize([row], [])
        self.assertIsNone(empty["stages_ms"]["capture_to_dom"]["p95"])
        self.assertIsNone(empty["observed_p95_below_3000_ms"])

    def test_native_slow_total_missing_or_invalid_components_never_disappears_from_p95(self):
        row, receipt = self.fixture(total=3000)
        fast_row, fast = self.fixture(10000, 2)
        for timing in (None, {**receipt["native_timing"], "ingested_at_unix_ms": 1099}):
            with self.subTest(timing=timing):
                slow = {**receipt, "native_timing": timing}
                result = self.summarize([row, fast_row], [fast, slow])
                self.assertEqual(result["sample_count"], 2)
                self.assertEqual(result["complete_stage_sample_count"], 1)
                self.assertEqual(result["stages_ms"]["capture_to_dom"]["p95"], 3000)
                self.assertFalse(result["observed_p95_below_3000_ms"])

    def test_native_cached_field_total_uses_original_capture_without_latest_transport(self):
        row, receipt = self.fixture(2000, 2)
        older = {**capture(1000, 1), "generation": 1}
        row[1]["state"]["partial_observation"]["field_captures"]["pot_size"] = older
        receipt.update(capture=older, published_at_unix_ms=4000, native_timing=None)
        result = self.summarize([row], [receipt])
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["complete_stage_sample_count"], 0)
        self.assertEqual(result["stages_ms"]["capture_to_dom"]["p95"], 3000)
        # Even a forged latest timing chain cannot be attributed to this older field.
        receipt["native_timing"] = row[1]["state"]["native_timing"]
        result = self.summarize([row], [receipt])
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["complete_stage_sample_count"], 0)
        self.assertTrue(result["rejected_records"])

    def test_native_clock_ticket_source_and_unit_contradictions_are_rejected(self):
        row, receipt = self.fixture()
        variants = [lambda r: r.update(value="12345 chips"), lambda r: r.update(seat=1),
            lambda r: r["native_timing"].update(generation=2), lambda r: r["native_timing"].update(epoch=2),
            lambda r: r["native_timing"].update(captured_at_ms=999),
            lambda r: r["native_timing"].update(captured_at_unix_ms=999),
            lambda r: r["native_timing"].update(emitted_at_unix_ms=999),
            lambda r: r["native_timing"].update(ingested_at_unix_ms=1099),
            lambda r: r["native_timing"].update(api_snapshot_at_unix_ms=1199),
            lambda r: r["native_timing"].update(api_snapshot_at_unix_ms=1401)]
        variants += [lambda r, k=k, v=v: r["native_timing"].update({k: v})
            for k in receipt["native_timing"] for v in (True, None, "1", -1, 1.5, float("inf"), float("nan"), 2**53)]
        variants += [lambda r, k=k: r["capture"].update({k: 2 if k in ("epoch", "sequence", "generation") else "other"})
                     for k in (*measurement.CAPTURE_KEYS[:6], "generation")]
        for mutate in variants:
            with self.subTest(mutate=mutate):
                bad = copy.deepcopy(receipt)
                mutate(bad)
                result = self.summarize([row], [bad])
                self.assertEqual(result["complete_stage_sample_count"], 0)
                self.assertTrue(result["rejected_records"])

    def test_native_api_scope_cached_fields_and_mismatched_transport_do_not_supply_samples(self):
        row, receipt = self.fixture()
        variants = [lambda s: s["capture_session"].update(session_id="other"),
            lambda s: s["server"].update(instance_id="other"), lambda s: s.update(session_id="other"),
            lambda s: s["capture"].update(source_id="other"), lambda s: s["capture"].update(epoch=2),
            lambda s: s["partial_observation"]["field_captures"].update(pot_size=capture(999, 0)),
            lambda s: s["native_timing"].update(ingested_at_unix_ms=1201),
            lambda s: s["partial_observation"].update(captured_at_ms=99)]
        for index, mutate in enumerate(variants):
            with self.subTest(mutate=mutate):
                bad = copy.deepcopy(row)
                mutate(bad[1]["state"])
                result = self.summarize([bad], [receipt])
                self.assertEqual(result["sample_count"], 1 if index == 6 else 0)
                self.assertEqual(result["complete_stage_sample_count"], 0)

    def test_native_summary_is_bounded_and_projection_retains_optional_contract(self):
        row, receipt = self.fixture()
        projected, audit = measurement.CompactProjection().project(row[1]["state"])
        self.assertTrue(audit["complete"])
        self.assertEqual(projected["native_timing"], receipt["native_timing"])
        self.assertEqual(projected["partial_observation"]["field_statuses"]["pot_size"], {"status": "accepted"})
        self.assertEqual(self.summarize([(0, sample(projected, 1350))], [receipt])["sample_count"], 1)
        with patch.object(measurement, "ROW_LIMIT", 1), patch.object(measurement, "EVENT_LIMIT", 1):
            result = self.summarize([row, row], [receipt, receipt], info={"complete": False, "dropped": 1})
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["counts"]["api_rows_over_limit"], 1)
        self.assertEqual(result["counts"]["ui_rows_over_limit"], 1)
        self.assertFalse(result["complete_coverage"])

    def test_native_source_field_and_unit_boundaries_reject_totals_not_only_components(self):
        row, receipt = self.fixture()
        for key, bad in (("capture_session_id", "other"), ("service_instance_id", "other"),
                         ("session_id", "other"), ("source_id", "other"), ("epoch", 2), ("sequence", 2),
                         ("sha256", "a" * 64), ("captured_at_ms", 901001), ("captured_at_unix_ms", 1001),
                         ("width", 940), ("generation", 2)):
            with self.subTest(key=key):
                bad_receipt = copy.deepcopy(receipt)
                bad_receipt["capture"][key] = bad
                result = self.summarize([row], [bad_receipt])
                self.assertEqual(result["sample_count"], 0)
                self.assertTrue(result["rejected_records"])
        for bad in ("12345", "12345 chips", "123.451", "123,45", 12345, None, True):
            with self.subTest(literal=bad):
                self.assertEqual(self.summarize([row], [{**receipt, "value": bad}])["sample_count"], 0)

    def test_native_invalid_api_timing_is_non_gating_and_conflicts_cannot_choose_a_faster_chain(self):
        row, receipt = self.fixture()
        for bad in (None, [], {**receipt["native_timing"], "ingested_at_unix_ms": True}):
            with self.subTest(bad=bad):
                changed = copy.deepcopy(row)
                changed[1]["state"]["native_timing"] = bad
                result = self.summarize([changed], [receipt])
                self.assertEqual(result["sample_count"], 1)
                self.assertEqual(result["complete_stage_sample_count"], 0)
        conflicting = copy.deepcopy(row)
        conflicting[1]["state"]["native_timing"]["ingested_at_unix_ms"] += 1
        result = self.summarize([row, conflicting], [receipt])
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["complete_stage_sample_count"], 0)
        self.assertTrue(result["rejected_records"])

    def test_native_zero_duration_stages_are_measured_not_unknown_defaults(self):
        row, receipt = self.fixture(total=0)
        row[1]["sampled_at_unix_ms"] = 1000
        for key in ("emitted_at_unix_ms", "ingested_at_unix_ms", "api_snapshot_at_unix_ms"):
            row[1]["state"]["native_timing"][key] = receipt["native_timing"][key] = 1000
        result = self.summarize([row], [receipt], run(1000))
        self.assertEqual(result["complete_stage_sample_count"], 1)
        for stage in result["stages_ms"].values():
            self.assertEqual(stage["p95"], 0)

    def test_native_receipt_claimed_current_at_or_after_collected_snapshot_expiry_is_rejected(self):
        row, receipt = self.fixture()
        for published, expected in ((5999, 1), (6000, 0), (6001, 0)):
            with self.subTest(published=published):
                result = self.summarize([row], [{**receipt, "published_at_unix_ms": published}])
                self.assertEqual(result["sample_count"], expected)

    def test_review_replayed_ticket_with_conflicting_originals_excludes_all_bindings_in_any_order(self):
        row, receipt = self.fixture()
        good_row, good = self.fixture(10000, 2, total=3000)
        good.pop("native_timing")
        for changed_key, changed_value in (("sequence", 2), ("sha256", "a" * 64), ("native_source_id", "2")):
            for missing_timing in (False, True):
                cloned_row, cloned_receipt = copy.deepcopy((row, receipt))
                cloned_row[1]["state"]["partial_observation"]["capture"][changed_key] = changed_value
                cloned_receipt["capture"][changed_key] = changed_value
                cloned_receipt["published_at_unix_ms"] = 4000
                if missing_timing:
                    cloned_row[1]["state"].pop("native_timing")
                    cloned_receipt.pop("native_timing")
                for api_order in ([row, cloned_row], [cloned_row, row]):
                    for ui_order in ([receipt, cloned_receipt], [cloned_receipt, receipt]):
                        with self.subTest(key=changed_key, missing_timing=missing_timing,
                                          api_reversed=api_order[0] is cloned_row, ui_reversed=ui_order[0] is cloned_receipt):
                            result = self.summarize([*api_order, good_row], [*ui_order, good])
                            self.assertEqual(result["sample_count"], 1)
                            self.assertEqual(result["complete_stage_sample_count"], 0)
                            self.assertEqual(result["stages_ms"]["capture_to_dom"]["p95"], 3000)
                            self.assertEqual(result["counts"]["ambiguous_native_tickets"], 1)
                            self.assertEqual(result["counts"]["ambiguous_original_captures"], 2)
                            self.assertEqual(result["rejected_records"]["ui-ambiguous-ticket-binding"],
                                             1 if changed_key == "native_source_id" else 2)
                            self.assertEqual(result["counts"].get("duplicate_publications", 0),
                                             1 if changed_key == "native_source_id" else 0)
                            self.assertEqual(result["unknown_records"], {"missing-native-timing": 1})

    def test_review_optional_capture_generation_requires_exact_integer_identity(self):
        row, receipt = self.fixture()
        for bad in (True, False, 1.0, 1.5, None, "1", -1, 2**53):
            for location in ("ui", "api-original", "api-field"):
                with self.subTest(value=bad, location=location):
                    changed_row, changed_receipt = copy.deepcopy((row, receipt))
                    partial = changed_row[1]["state"]["partial_observation"]
                    # Keep an independently valid exact field ref to expose Python numeric equality on the original.
                    partial["field_captures"]["pot_size"] = copy.deepcopy(receipt["capture"])
                    target = (changed_receipt["capture"] if location == "ui" else partial["capture"]
                              if location == "api-original" else partial["field_captures"]["pot_size"])
                    target["generation"] = bad
                    result = self.summarize([changed_row], [changed_receipt])
                    self.assertEqual(result["sample_count"], 0)
                    self.assertEqual(result["complete_stage_sample_count"], 0)
                    self.assertTrue(result["rejected_records"])
        without_generation = copy.deepcopy((row, receipt))
        without_generation[0][1]["state"]["partial_observation"]["capture"].pop("generation")
        without_generation[1]["capture"].pop("generation")
        self.assertEqual(self.summarize([without_generation[0]], [without_generation[1]])["complete_stage_sample_count"], 1)


class NamespaceMeasurementTests(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, train = root / ".local", root / ".local/laya/train"
            train.mkdir(parents=True)
            session = private / "laya/manual-capture" / ("a" * 32)
            session.mkdir(parents=True)
            answers, manifest = train / "answers.jsonl", train / "manifest.jsonl"
            answers.write_bytes(b"")
            manifest.write_bytes(b"")
            args = argparse.Namespace(seconds=1.5, poll_ms=500, session="a" * 32,
                answers=str(answers), manifest=str(manifest))
            with patch.object(measurement, "ROOT", root), patch.object(measurement, "PRIVATE", private), \
                    patch.object(measurement, "TRAIN", train), patch.object(measurement.private_path, "__defaults__", (private,)):
                yield root, train, session, args

    def namespace(self, letter="a", retired=False, sizes=(0, 0)):
        ident = "uncommitted-" + (letter if len(letter) == 32 else letter * 32)
        directory = Path(".local/laya/events") / hashlib.sha256(b"service").hexdigest()[:32] / ident
        return {"namespace_id": ident, "status": "retired-uncommitted" if retired else "active",
            "admitted_evidence": False, "semantics": "diagnostic-attempts-only; retirement freezes observed prefixes; late writes excluded",
            "frozen_prefix": retired, "workers_drained": False,
            "scope": {**{key: capture()[key] for key in measurement.CAPTURE_KEYS[:5]}, "width": 939, "height": 714},
            "sequence": 1, "retirement_reason": "changed" if retired else None,
            "visual_log": {"path": str(directory / "visual.jsonl"), "bytes": sizes[0], "complete": True},
            "context_log": {"path": str(directory / "context.jsonl"), "bytes": sizes[1], "complete": True},
            "archive": {"frames": 0, "bytes": 0, "log_bytes": 0, "complete": True}}

    def snapshot(self, namespaces, overflow=0):
        value = state()
        value["table_context"] = None
        value["capture"].update(width=939, height=714)
        value["visual_diagnostics"] = {"schema_version": 1, "namespaces": namespaces, "namespace_overflow_count": overflow}
        active = next((item for item in namespaces if item["status"] == "active"), None)
        if active:
            value["context_diagnostics"] = {"log_path": active["context_log"]["path"], "bytes": active["context_log"]["bytes"], "log_complete": True}
        return value

    def collect(self, train, args, states):
        clock, requests = [0.0], []

        class Connection:
            def __init__(self, *args, **kwargs):
                self.sock = self
                self.done = False

            def request(self, *args, **kwargs):
                requests.append(args)

            def getresponse(self):
                self.raw = measurement.dump(states[min(len(requests) - 1, len(states) - 1)]).encode()
                self.status = 200
                return self

            def isclosed(self):
                return self.done

            def read1(self, limit):
                chunk, self.raw = self.raw[:limit], self.raw[limit:]
                self.done = not self.raw
                return chunk

            def settimeout(self, value):
                pass

            def close(self):
                pass

        def sleep(seconds):
            clock[0] += seconds

        out = train / "collected"
        with patch.object(measurement.time, "monotonic", lambda: clock[0]), patch.object(measurement.time, "sleep", sleep), \
                patch.object(measurement, "utc_ms", lambda: 1000 + round(clock[0] * 1000)), \
                patch.object(measurement.http.client, "HTTPConnection", Connection), patch.object(measurement, "analyze"), patch("builtins.print"):
            measurement.collect(args, out)
        return out, json.loads((out / "run.json").read_bytes())

    def test_namespace_projection_and_supported_same_binding_rotation_keep_native_collection_running(self):
        with self.fixture() as (_, train, _, args):
            first = self.namespace()
            retired = {**copy.deepcopy(first), "status": "retired-uncommitted", "frozen_prefix": True}
            second = self.namespace("b")
            states = [self.snapshot([first]), self.snapshot([retired, second]), self.snapshot([{**retired, "workers_drained": True}, second])]
            projection = measurement.CompactProjection()
            projected, _ = projection.project(states[0])
            self.assertEqual(projected["visual_diagnostics"]["namespaces"][0]["namespace_id"], first["namespace_id"])
            repeated, _ = projection.project(states[0])
            self.assertEqual(repeated["visual_diagnostics"]["namespaces"], [])
            out, result = self.collect(train, args, states)
            self.assertEqual(result["stop_reason"], "duration-limit")
            self.assertEqual(result["samples"], 3)
            self.assertEqual(len(result["visual_namespaces"]["namespaces"]), 2)
            self.assertEqual(len((out / "api.jsonl").read_text().splitlines()), 3)

    def test_namespace_does_not_relax_genuine_source_stop_or_legacy_log_rotation_stop(self):
        for section, key, value, reason in (("capture", "source_id", "changed", "source_id-changed"),
                ("server", "instance_id", "changed", "service_instance_id-changed"),
                ("capture_session", "session_id", "b" * 32, "capture-session-changed"),
                ("capture", "epoch", 2, "epoch-changed")):
            with self.subTest(reason=reason), self.fixture() as (_, train, _, args):
                values = [self.snapshot([self.namespace()]), self.snapshot([self.namespace("b")])]
                values[1][section][key] = value
                _, result = self.collect(train, args, values)
                self.assertEqual(result["stop_reason"], reason)
        with self.fixture() as (_, train, _, args):
            values = [self.snapshot([self.namespace()]), self.snapshot([self.namespace("b")])]
            for value in values:
                value["visual_diagnostics"] = {"schema_version": 1, "legacy": True}
            _, result = self.collect(train, args, values)
            self.assertEqual(result["stop_reason"], "context-log-changed")

    def test_namespace_frozen_retired_prefix_and_scoped_ids_never_admit_late_work(self):
        with self.fixture() as (root, _, _, _):
            record = {"schema_version": 1, "event": "context_attempt", "capture": capture(),
                "requested_at_unix_ms": 1000, "attempt_started_at_unix_ms": 1001, "completed_at_unix_ms": 1002}
            line = (measurement.dump(record) + "\n").encode()
            first, second = self.namespace(sizes=(len(line), len(line))), self.namespace("b", sizes=(len(line), len(line)))
            for namespace in (first, second):
                for kind in ("visual_log", "context_log"):
                    path = root / namespace[kind]["path"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(line + line)  # Late post-retirement writes are already physically present.
            retired = {**copy.deepcopy(first), "status": "retired-uncommitted", "frozen_prefix": True}
            drained = copy.deepcopy(retired)
            drained["workers_drained"] = True
            drained["context_log"]["bytes"] *= 2  # Contradictory later telemetry cannot renew a frozen prefix.
            tracker = measurement.VisualNamespaces()
            api = [(i, sample(value, 1100 + i)) for i, value in enumerate(
                (self.snapshot([first]), self.snapshot([retired, second]), self.snapshot([drained, second])))]
            for _, row in api:
                tracker.observe(row["state"])
            report = tracker.analyze(api, run(), [])
            self.assertEqual(report["counts"]["candidate_records"], 4)
            self.assertEqual(len({item["record_id"] for item in report["candidates"]}), 4)
            self.assertFalse(any(item["admitted_evidence"] for item in report["candidates"]))
            self.assertFalse(report["complete_coverage"])
            self.assertIn("retired-prefix-change", report["issues"])
            self.assertEqual(report["namespaces"][0]["context_log"]["bytes"], len(line))
            self.assertEqual(report["counts"]["api_matched_candidates"], 0)

    def test_namespace_malformed_paths_scope_flags_and_schema_never_authorize_reads(self):
        with self.fixture():
            for mutate in (
                lambda n: n["context_log"].update(path=".local/laya/train/arbitrary.jsonl"),
                lambda n: n["visual_log"].update(path="../outside.jsonl"),
                lambda n: n["visual_log"].update(path="C:/outside.jsonl"),
                lambda n: n["scope"].update(session_id="other"),
                lambda n: n["scope"].update(width=940), lambda n: n["scope"].update(epoch=True),
                lambda n: n.update(namespace_id="arbitrary"), lambda n: n.update(admitted_evidence=True),
                lambda n: n.update(frozen_prefix=True), lambda n: n["context_log"].update(bytes=True)):
                namespace = self.namespace()
                mutate(namespace)
                tracker = measurement.VisualNamespaces()
                self.assertFalse(tracker.observe(self.snapshot([namespace])))
                with patch.object(measurement, "read_rows", side_effect=AssertionError("unexpected read")):
                    report = tracker.analyze([], run(), [])
                self.assertEqual(report["counts"]["candidate_records"], 0)
                self.assertTrue(report["issues"])

    def test_namespace_registry_budgets_overflow_and_empty_unopened_prefix_are_explicit(self):
        with self.fixture():
            with patch.object(measurement, "NAMESPACE_LIMIT", 2):
                tracker = measurement.VisualNamespaces()
                for letter in "abcde":
                    tracker.observe(self.snapshot([self.namespace(letter)], overflow=7))
                report = tracker.analyze([], run(), [])
            self.assertEqual(len(report["namespaces"]), 2)
            self.assertGreaterEqual(report["issues"]["namespace-limit"], 3)
            self.assertIn("producer-overflow", report["issues"])
            self.assertFalse(report["observed_prefixes_complete"])
            tracker = measurement.VisualNamespaces()
            self.assertTrue(tracker.observe(self.snapshot([self.namespace()])))
            empty = tracker.analyze([], run(), [])
            self.assertTrue(empty["observed_prefixes_complete"])
            self.assertEqual(empty["counts"]["candidate_records"], 0)

    def test_namespace_aggregate_byte_row_limits_and_partial_tail_are_not_complete(self):
        with self.fixture() as (root, _, _, _):
            row = (measurement.dump({"capture": capture()}) + "\n").encode()
            namespace = self.namespace(sizes=(len(row) * 3, 1))
            for kind, raw in (("visual_log", row * 3), ("context_log", b"{")):
                path = root / namespace[kind]["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            tracker = measurement.VisualNamespaces()
            tracker.observe(self.snapshot([namespace]))
            with patch.object(measurement, "NAMESPACE_BYTES", len(row) + 1), patch.object(measurement, "NAMESPACE_ROWS", 1):
                report = tracker.analyze([], run(), [])
            self.assertLessEqual(report["counts"]["scanned_rows"], 1)
            self.assertLessEqual(report["counts"]["scanned_bytes"], len(row) + 1)
            self.assertFalse(report["observed_prefixes_complete"])
            self.assertTrue(report["issues"])
            full = tracker.analyze([], run(), [])
            self.assertIn("partial-tail", full["issues"])

    def test_namespace_analyze_report_separates_candidates_from_canonical_legacy_counts(self):
        with self.fixture() as (root, train, session, args):
            namespace = self.namespace()
            raw = (measurement.dump({"event": "context_attempt", "capture": capture(),
                "requested_at_unix_ms": 1000, "attempt_started_at_unix_ms": 1001, "completed_at_unix_ms": 1002}) + "\n").encode()
            for kind in ("context_log", "visual_log"):
                path = root / namespace[kind]["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                namespace[kind]["bytes"] = len(raw)
            out, manifest_run = self.collect(train, args, [self.snapshot([namespace])])
            # Poisoned adjacent legacy log must not be consulted in namespace mode.
            (train / "visual.jsonl").write_bytes(raw * 5)
            with patch("builtins.print"):
                measurement.analyze(out, run=manifest_run)
            report = json.loads((out / "timing.json").read_bytes())
            self.assertEqual(report["diagnostic_namespaces"]["counts"]["candidate_records"], 2)
            self.assertEqual(report["table_context"]["native_context_attempts"]["attempted_source_wall"]["count"], 0)
            self.assertEqual(report["visual"]["confirmed_processed_frames"]["count"], 0)

    def test_namespace_global_history_exceeds_per_api_registry_without_ending_collection(self):
        with self.fixture() as (_, train, _, args):
            args.seconds = 20
            history, values = [], []
            for index in range(40):
                active = self.namespace(f"{index:032x}")
                values.append(self.snapshot([*history[-32:], active], overflow=max(0, index - 32)))
                history.append({**active, "status": "retired-uncommitted", "frozen_prefix": True})
            _, result = self.collect(train, args, values)
            self.assertEqual(result["samples"], 40)
            self.assertEqual(result["stop_reason"], "duration-limit")
            self.assertEqual(len(result["visual_namespaces"]["namespaces"]), 40)
            self.assertFalse(result["collection_complete"])
            self.assertEqual(result["visual_namespaces"]["issues"]["producer-overflow"], 7)
        with self.fixture() as (_, train, _, args):
            args.seconds = 2.5
            values = [self.snapshot([self.namespace(letter)]) for letter in "abcde"]
            with patch.object(measurement, "NAMESPACE_LIMIT", 2):
                out, result = self.collect(train, args, values)
                with patch("builtins.print"):
                    measurement.analyze(out, run=result)
            report = json.loads((out / "timing.json").read_bytes())
            self.assertEqual(result["samples"], 5)
            self.assertEqual(result["stop_reason"], "duration-limit")
            self.assertEqual(len(result["visual_namespaces"]["namespaces"]), 2)
            self.assertIn("namespace-limit", report["diagnostic_namespaces"]["issues"])
            self.assertFalse(report["diagnostic_namespaces"]["observed_prefixes_complete"])

    def test_namespace_bad_header_missing_shortened_invalid_and_api_match_are_explicit(self):
        with self.fixture() as (root, _, _, _):
            for schema in (True, 2, "1", None):
                tracker = measurement.VisualNamespaces()
                value = self.snapshot([self.namespace()])
                value["visual_diagnostics"]["schema_version"] = schema
                self.assertFalse(tracker.observe(value))
                self.assertIn("registry-schema", tracker.analyze([], run(), [])["issues"])
            namespace = self.namespace(sizes=(10, 10))
            tracker = measurement.VisualNamespaces()
            tracker.observe(self.snapshot([namespace]))
            absent = tracker.analyze([], run(), [])
            self.assertIn("missing-log", absent["issues"])
            context = root / namespace["context_log"]["path"]
            context.parent.mkdir(parents=True, exist_ok=True)
            context.write_bytes(b"{\n")
            broken = tracker.analyze([], run(), [])
            self.assertIn("shortened-log", broken["issues"])
            self.assertIn("invalid-json", broken["issues"])
            raw = (measurement.dump({"capture": capture()}) + "\n").encode()
            context.write_bytes(raw)
            namespace["context_log"]["bytes"] = len(raw)
            namespace["visual_log"]["bytes"] = 0
            tracker = measurement.VisualNamespaces()
            value = self.snapshot([namespace])
            value["table_context"] = state()["table_context"]
            tracker.observe(value)
            matched = tracker.analyze([(0, sample(value))], run(), [])
            self.assertEqual(matched["counts"]["api_matched_candidates"], 1)
            self.assertFalse(matched["candidates"][0]["admitted_evidence"])
            self.assertFalse(matched["complete_coverage"])

    def test_namespace_api_event_ids_and_cursor_resets_are_scoped_without_rewriting_original_ids(self):
        with self.fixture() as (_, train, _, args):
            args.seconds = 1
            first, second = self.namespace(), self.namespace("b")
            values = [self.snapshot([first]), self.snapshot([
                {**first, "status": "retired-uncommitted", "frozen_prefix": True}, second])]
            for index, value in enumerate(values):
                context = state(1000 + index * 200, index + 1)["table_context"]
                context["events_total"] = 5 if index == 0 else 1
                context["events"] = [{"event_id": 1, "kind": "identity_change", "seat": 1,
                                      "capture": context["capture"]}]
                value["table_context"] = context
            out, result = self.collect(train, args, values)
            entries = [json.loads(line) for line in (out / "api.jsonl").read_text().splitlines()]
            self.assertTrue(all(row["projection"]["complete"] for row in entries))
            self.assertEqual([row["state"]["table_context"]["events"][0]["event_id"] for row in entries], [1, 1])
            self.assertNotEqual(entries[0]["state"]["table_context"]["diagnostic_namespace_id"],
                                entries[1]["state"]["table_context"]["diagnostic_namespace_id"])
            with patch("builtins.print"):
                measurement.analyze(out, run=result)
            report = json.loads((out / "timing.json").read_bytes())["table_context"]
            self.assertEqual(report["event_kind_counts"]["identity_change"], 2)
            self.assertNotIn("event-id-conflict", report["rejected_records"])

    def test_namespace_failed_reads_still_consume_aggregate_limits(self):
        with self.fixture():
            tracker = measurement.VisualNamespaces()
            tracker.observe(self.snapshot([self.namespace(sizes=(10, 10))]))

            def failing_read(path, inputs, byte_limit, boundary, row_limit):
                inputs.append({"path": str(path), "bytes": byte_limit, "scanned_rows": row_limit})
                raise OSError("synthetic bounded read failure")

            with patch.object(measurement, "NAMESPACE_BYTES", 10), patch.object(measurement, "NAMESPACE_ROWS", 1), \
                    patch.object(measurement, "read_rows", side_effect=failing_read) as reads:
                report = tracker.analyze([], run(), [])
            self.assertEqual(reads.call_count, 1)
            self.assertEqual(report["counts"]["scanned_bytes"], 10)
            self.assertEqual(report["counts"]["scanned_rows"], 1)
            self.assertIn("invalid-read-binding", report["issues"])
            self.assertIn("aggregate-limit", report["issues"])

    def test_review_namespace_delta_replay_keeps_active_event_scope_across_unchanged_polls(self):
        with self.fixture() as (_, train, _, args):
            args.seconds = 3
            first, second = self.namespace(), self.namespace("b")
            retired = {**first, "status": "retired-uncommitted", "frozen_prefix": True}
            values = []
            for index in range(6):
                value = self.snapshot([first] if index < 3 else [retired, second])
                context = state(1000 if index < 3 else 1200, 1 if index < 3 else 2)["table_context"]
                count = 1 if index % 3 == 0 else 2
                context["events_total"] = count
                context["events"] = [{"event_id": event_id, "kind": "identity_change", "seat": event_id,
                    "capture": context["capture"], "reason": "updated-" + str(index)} for event_id in range(1, count + 1)]
                value["table_context"] = context
                values.append(value)
            out, collected = self.collect(train, args, values)
            rows = [json.loads(line) for line in (out / "api.jsonl").read_text().splitlines()]
            self.assertTrue(all(rows[index]["state"]["visual_diagnostics"]["namespaces"] == [] for index in (1, 2, 4, 5)))
            with patch("builtins.print"):
                measurement.analyze(out, run=collected)
            context = json.loads((out / "timing.json").read_bytes())["table_context"]
            self.assertEqual(context["event_kind_counts"]["identity_change"], 4)
            self.assertNotIn("event-id-conflict", context["rejected_records"])
            self.assertEqual({item["diagnostic_namespace_id"] for item in context["events"]},
                             {first["namespace_id"], second["namespace_id"]})

    def test_review_namespace_delta_active_state_does_not_resurrect_after_explicit_invalidation(self):
        with self.fixture():
            value = self.snapshot([self.namespace()])
            delta = self.snapshot([])
            delta["visual_diagnostics"]["namespaces_are_changes"] = True
            delta["context_diagnostics"] = copy.deepcopy(value["context_diagnostics"])
            for invalidation in ("empty", "missing", "schema", "scope", "retired"):
                with self.subTest(invalidation=invalidation):
                    tracker = measurement.VisualNamespaces()
                    self.assertTrue(tracker.observe(value))
                    self.assertTrue(tracker.observe(delta))
                    self.assertEqual(tracker.active_paths, {value["context_diagnostics"]["log_path"]})
                    cleared = copy.deepcopy(value)
                    if invalidation == "empty":
                        cleared["visual_diagnostics"]["namespaces"] = []
                    elif invalidation == "missing":
                        cleared.pop("visual_diagnostics")
                    elif invalidation == "schema":
                        cleared["visual_diagnostics"]["schema_version"] = 2
                    elif invalidation == "retired":
                        cleared["visual_diagnostics"]["namespaces_are_changes"] = True
                        cleared["visual_diagnostics"]["namespaces"][0].update(status="retired-uncommitted", frozen_prefix=True)
                    else:
                        cleared["capture"]["epoch"] = 2
                    tracker.observe(cleared)
                    self.assertEqual(tracker.active_paths, set())
                    tracker.observe(delta)
                    self.assertEqual(tracker.active_paths, set(), "empty delta must not revive invalidated entries")

    def test_review_namespace_cleared_or_invalid_binding_events_remain_unknown_not_legacy(self):
        malformed = {"null": ("namespaces", None), "delta-null": ("namespaces_are_changes", None),
                     "delta-int": ("namespaces_are_changes", 1), "clear-string": ("namespace_registry_cleared", "true"),
                     "clear-nonempty": ("namespace_registry_cleared", True)}
        for invalidate in ("clear", "schema", "projection", *malformed):
            with self.subTest(invalidate=invalidate), self.fixture() as (_, train, _, args):
                args.seconds = 2
                first, second = self.namespace(), self.namespace("b")
                values = [self.snapshot([first]), self.snapshot([first]), self.snapshot([first]), self.snapshot([second])]
                if invalidate == "clear":
                    for value in values[1:3]:
                        value["visual_diagnostics"]["namespaces"] = []
                else:
                    if invalidate == "schema":
                        values[1]["visual_diagnostics"]["schema_version"] = 2
                    elif invalidate in malformed:
                        key, invalid = malformed[invalidate]
                        values[1]["visual_diagnostics"][key] = invalid
                    else:
                        values[1]["visual_diagnostics"]["namespaces"] = "invalid-array"
                    values[2]["visual_diagnostics"] = {"schema_version": 1, "namespaces": [],
                        "namespace_overflow_count": 0, "namespaces_are_changes": True}
                for index, value in enumerate(values):
                    context = state(1000 if index < 3 else 1200, 1 if index < 3 else 2)["table_context"]
                    context["events"] = [{"event_id": 9 if index in (1, 2) else 1, "kind": "identity_change", "seat": 1,
                                          "capture": context["capture"], "reason": "updated-" + str(index)}]
                    context["events_total"] = 1
                    value["table_context"] = context
                out, collected = self.collect(train, args, values)
                if invalidate == "clear":
                    rows = [json.loads(line) for line in (out / "api.jsonl").read_text().splitlines()]
                    self.assertTrue(rows[1]["state"]["visual_diagnostics"]["namespace_registry_cleared"])
                    self.assertTrue(rows[2]["state"]["visual_diagnostics"]["namespace_registry_cleared"])
                with patch("builtins.print"):
                    measurement.analyze(out, run=collected)
                context = json.loads((out / "timing.json").read_bytes())["table_context"]
                self.assertEqual(context["event_kind_counts"]["identity_change"], 2)
                self.assertEqual(context["rejected_records"]["event-namespace-unavailable"], 2)
                self.assertTrue(all(item["diagnostic_namespace_id"] is not None for item in context["events"]))

    def test_review_projection_marks_invalid_namespace_presence_and_markers(self):
        variants = (("namespaces", None), ("namespaces_are_changes", None),
                    ("namespaces_are_changes", 1), ("namespace_registry_cleared", "true"),
                    ("namespace_registry_cleared", True))
        for key, invalid in variants:
            with self.subTest(key=key, value=invalid), self.fixture():
                original = self.snapshot([self.namespace()])
                bad = copy.deepcopy(original)
                bad["visual_diagnostics"][key] = invalid
                raw = measurement.VisualNamespaces()
                self.assertTrue(raw.observe(original))
                self.assertFalse(raw.observe(bad))
                projection = measurement.CompactProjection()
                projection.project(original)
                repaired, metadata = projection.project(bad)
                self.assertTrue(any(issue.startswith("namespace:") for issue in metadata["issues"]))
                self.assertEqual(repaired["visual_diagnostics"]["namespaces"], [])

    def test_review_legacy_to_invalid_namespace_changed_path_still_stops(self):
        for invalidation in ("schema", "malformed", "scope", "source-change"):
            with self.subTest(invalidation=invalidation), self.fixture() as (_, train, _, args):
                values = [self.snapshot([self.namespace()]), self.snapshot([self.namespace("b")])]
                values[0].pop("visual_diagnostics")
                if invalidation in ("schema", "source-change"):
                    values[1]["visual_diagnostics"]["schema_version"] = 2
                elif invalidation == "malformed":
                    values[1]["visual_diagnostics"]["namespaces"] = "invalid"
                else:
                    values[1]["visual_diagnostics"]["namespaces"][0]["scope"]["source_id"] = "wrong"
                if invalidation == "source-change":
                    values[1]["capture"]["source_id"] = "changed"
                _, result = self.collect(train, args, values)
                self.assertEqual(result["stop_reason"], "source_id-changed" if invalidation == "source-change" else "context-log-changed")
                self.assertEqual(result["samples"], 2)

    def test_review_legacy_to_valid_same_binding_namespace_rotation_is_supported(self):
        with self.fixture() as (_, train, _, args):
            values = [self.snapshot([self.namespace()]), self.snapshot([self.namespace("b")])]
            values[0].pop("visual_diagnostics")
            _, result = self.collect(train, args, values)
            self.assertEqual(result["stop_reason"], "duration-limit")
            self.assertEqual(result["samples"], 3)


class FiniteCollectorTests(unittest.TestCase):
    def test_review_cli_analyze_and_summary_expose_nonempty_compact_native_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, train = root / ".local", root / ".local/laya/train"
            train.mkdir(parents=True)
            session = private / "laya/manual-capture" / ("a" * 32)
            session.mkdir(parents=True)
            out = train / "positive-native-timing"
            out.mkdir()
            answers, manifest = train / "answers.jsonl", train / "manifest.jsonl"
            answers.write_bytes(b"")
            manifest.write_bytes(b"")
            row, receipt = NativeTimingTests().fixture()
            (out / "api.jsonl").write_text(measurement.dump(row[1]) + "\n")
            ui = train / "ui.json"
            ui.write_text(measurement.dump({"receipts": [receipt], "dropped": 0, "capacity": 12000}))
            manifest_run = {**run(3000), "session_dir": str(session.relative_to(root)),
                "answers_log": str(answers.relative_to(root)), "manifest": str(manifest.relative_to(root)),
                "elapsed_ms": 2000, "stop_reason": "duration-limit"}
            (out / "run.json").write_text(measurement.dump(manifest_run))
            with patch.object(measurement, "ROOT", root), patch.object(measurement, "PRIVATE", private), \
                    patch.object(measurement, "TRAIN", train), patch.object(measurement.private_path, "__defaults__", (private,)):
                for mode in ("analyze", "summary"):
                    with self.subTest(mode=mode):
                        stream = io.StringIO()
                        with patch.object(sys, "argv", ["measure_observer.py", mode, "--out", str(out), "--ui-receipts", str(ui)]), \
                                contextlib.redirect_stdout(stream):
                            measurement.main()
                        output = json.loads(stream.getvalue())
                        timing = output["native_numeric_timing"]
                        self.assertEqual(timing["sample_count"], 1)
                        self.assertEqual(timing["complete_stage_sample_count"], 1)
                        self.assertEqual(timing["stages_ms"]["capture_to_dom"]["p95"], 400)
                        self.assertEqual(timing["stages_ms"]["api_to_dom"]["count"], 1)
                        self.assertFalse(timing["complete_coverage"])
                        self.assertEqual(timing["counts"]["collected_native_fields"], 2)
                        self.assertEqual(timing["unknown_records"], {})
                        self.assertEqual(timing["rejected_records"], {})
                        self.assertNotIn("source-event-never-summary", stream.getvalue())
                        self.assertNotIn("source_events", timing)
                        saved = json.loads((out / "timing.json").read_bytes())
                        self.assertEqual(saved["native_numeric_timing"]["sample_count"], 1)
                        # Future detailed event lists must not leak into the compact CLI projection.
                        saved["native_numeric_timing"]["source_events"] = ["source-event-never-summary"] * 1000
                        (out / "timing.json").write_text(measurement.dump(saved))

    def test_full_schema_one_analysis_freezes_native_attempts_and_later_ui_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private, train = root / ".local", root / ".local/laya/train"
            train.mkdir(parents=True)
            session = private / "laya/manual-capture" / ("a" * 32)
            session.mkdir(parents=True)
            out = train / "run"
            out.mkdir()
            answers, manifest = train / "answers.jsonl", train / "manifest.jsonl"
            answers.write_bytes(b"")
            manifest.write_bytes(b"")
            log = private / "laya/events/service/context.jsonl"
            log.parent.mkdir(parents=True)
            attempt = {"event": "context_attempt", "capture": capture(), "requested_at_unix_ms": 1000,
                "attempt_started_at_unix_ms": 1001, "completed_at_unix_ms": 1002}
            prefix = (measurement.dump(attempt) + "\n").encode()
            late = {**attempt, "capture": capture(2000, 2), "requested_at_unix_ms": 2000,
                    "attempt_started_at_unix_ms": 2001, "completed_at_unix_ms": 2002}
            log.write_bytes(prefix + (measurement.dump(late) + "\n").encode())
            value = state()
            value["context_diagnostics"] = {"log_path": str(log.relative_to(root)), "log_complete": True,
                                            "bytes": len(prefix), "dropped": 0}
            projected, audit = measurement.CompactProjection().project(value)
            entry = {**sample(projected), "projected": True, "projection": audit, "request_started_at_unix_ms": 1000}
            (out / "api.jsonl").write_text(measurement.dump(entry) + "\n")
            receipt = {"field": "identity", "seat": 1, "capture": capture(2000, 2),
                       "published_at_unix_ms": 2100}
            ui = train / "ui.json"
            ui.write_text(measurement.dump({"receipts": [receipt], "dropped": 0, "capacity": 12000}))
            manifest_run = {**run(3000), "session_dir": str(session.relative_to(root)),
                "answers_log": str(answers.relative_to(root)), "manifest": str(manifest.relative_to(root)),
                "elapsed_ms": 2000, "stop_reason": "duration-limit", "context_log": str(log.relative_to(root)),
                "input_sizes_at_end": {str(log.relative_to(root)): len(prefix)}}
            with patch.object(measurement, "ROOT", root), patch.object(measurement, "PRIVATE", private), \
                    patch.object(measurement.private_path, "__defaults__", (private,)), patch("builtins.print"):
                measurement.analyze(out, run=manifest_run, ui_receipts=ui)
            result = json.loads((out / "timing.json").read_bytes())
            self.assertEqual(result["format"], 1)
            self.assertEqual(result["native_numeric_timing"]["sample_count"], 0)
            self.assertFalse(result["native_numeric_timing"]["complete_coverage"])
            self.assertEqual(result["seats"]["1"]["attempted_source_capture"]["count"], 0)
            context = result["table_context"]
            self.assertEqual(context["native_context_attempts"]["attempted_source_wall"]["count"], 1)
            self.assertGreater(context["native_context_input"]["bytes_after_boundary"], 0)
            self.assertEqual(context["ui"]["rejected_records"]["ui-original-not-in-collected-window"], 1)

    def test_mocked_collection_hash_projection_deadline_and_no_runtime_mutation(self):
        self.collect_fixture()

    def test_mocked_request_cannot_read_past_finite_deadline(self):
        self.collect_fixture(delay=2)

    def collect_fixture(self, delay=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / ".local"
            train = private / "laya/train"
            train.mkdir(parents=True)
            session = private / "laya/manual-capture" / ("a" * 32)
            session.mkdir(parents=True)
            answers, manifest = train / "answers.jsonl", train / "manifest.jsonl"
            answers.write_bytes(b"")
            manifest.write_bytes(b"")
            value = state()
            value["history"] = {"events": ["discarded"] * 10}
            raw = measurement.dump(value).encode()
            clock = [0.0]
            requests = []

            class Response:
                status = 200
                done = False

                def isclosed(self):
                    return self.done

                def read1(self, limit):
                    self.done = True
                    return raw[:limit]

            class Connection:
                def __init__(self, host, port, timeout):
                    self.sock = self

                def request(self, method, path, headers):
                    requests.append((method, path))

                def getresponse(self):
                    clock[0] += delay
                    return Response()

                def settimeout(self, value):
                    pass

                def close(self):
                    pass

            def sleep(seconds):
                clock[0] += seconds

            args = argparse.Namespace(seconds=1, poll_ms=500, session="a" * 32,
                answers=str(answers), manifest=str(manifest))
            out = train / "result"
            with patch.object(measurement, "ROOT", root), patch.object(measurement, "PRIVATE", private), \
                    patch.object(measurement.private_path, "__defaults__", (private,)), \
                    patch.object(measurement, "TRAIN", train), patch.object(measurement.time, "monotonic", lambda: clock[0]), \
                    patch.object(measurement.time, "sleep", sleep), patch.object(measurement, "utc_ms", lambda: 1000 + round(clock[0] * 1000)), \
                    patch.object(measurement.http.client, "HTTPConnection", Connection), patch.object(measurement, "analyze"), \
                    patch("builtins.print"):
                measurement.collect(args, out)
            result = json.loads((out / "run.json").read_bytes())
            entries = [json.loads(line) for line in (out / "api.jsonl").read_text().splitlines()]
            self.assertEqual(requests, [("GET", "/api/state")] * (1 if delay else 2))
            self.assertEqual(result["stop_reason"], "duration-limit")
            self.assertLessEqual(result["samples"], 2)
            if delay:
                self.assertFalse(result["collection_complete"])
                self.assertEqual(entries[0]["error_reason"], "measurement-deadline")
            else:
                self.assertTrue(entries[0]["projected"])
                self.assertNotIn("history", entries[0]["state"])
                self.assertEqual(entries[0]["response_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(entries[0]["response_bytes"], len(raw))
                self.assertEqual(result["input_sizes_at_end"][str((out / "api.jsonl").relative_to(root))],
                                 (out / "api.jsonl").stat().st_size)


if __name__ == "__main__":
    unittest.main()
