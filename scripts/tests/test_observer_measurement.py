"""Finite offline observer collector/analysis checks; no runtime or client access."""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("observer_measurement", ROOT / ".local/laya/train/measure_observer.py")
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


class FiniteCollectorTests(unittest.TestCase):
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
