#!/usr/bin/env python3
"""Bounded observer measurement and source-preserving analysis with private outputs.

Importing this reusable module performs no collection or private-file reads.
"""

import argparse
import collections
import datetime as dt
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local"
TRAIN = PRIVATE / "laya/train"
API_LIMIT = 256 * 1024
OUTPUT_LIMIT = 32 * 1024 * 1024
INPUT_LIMIT = 64 * 1024 * 1024
LINE_LIMIT = 512 * 1024
ROW_LIMIT = 30000
READOUT_LIMIT = 4 * 1024 * 1024
DEADLINE = 10000
SEAT_PASS = re.compile(r"p([567])_seat_([1-6])_(stack|wager|scene)$")
EVENT_LIMIT = 12000
EVENT_ROW_LIMIT = 256
UI_RECEIPT_LIMIT = 8 * 1024 * 1024
NAMESPACE_LIMIT = 128
NAMESPACE_API_LIMIT = 33
NAMESPACE_BYTES = 8 * 1024 * 1024
NAMESPACE_ROWS = 12000
CAPTURE_KEYS = ("service_instance_id", "session_id", "capture_session_id", "source_id",
                "epoch", "sequence", "captured_at_ms", "captured_at_unix_ms", "sha256", "width", "height")
CAPTURE_BASE_SPEC = dict.fromkeys((*CAPTURE_KEYS, "native_source_id", "table_context_id", "table_epoch", "generation",
    "complete", "source_process_created_at_100ns", "pixel_source", "readability", "occluded_regions"))
CAPTURE_SPEC = {**CAPTURE_BASE_SPEC, "parent_capture": CAPTURE_BASE_SPEC, "popup_index": None, "non_atomic": None,
    "popup_window": dict.fromkeys(("binding_id",))}
CLOCK_KEYS = ("requested_at_unix_ms", "attempt_started_at_unix_ms", "completed_at_unix_ms",
              "requested_at_ms", "attempt_started_at_ms", "completed_at_ms", "processing_ms")
EVIDENCE_SPEC = dict.fromkeys(("enabled", "complete", "count", "bytes", "event_count", "frame_count",
    "max_bytes", "max_events", "max_frames", "byte_limit", "event_limit", "frame_limit", "dropped",
    "dropped_frames", "dropped_candidates", "queue_drops", "rejected", "rejection_counts", "caps",
    "capped", "reason", "reasons", "evidence_id", "original_id", "original_sha256", "crop_sha256",
    "crop_bounds", "width", "height", "refs", "references", "original", "crops", "manifest_id",
    "cursor", "first_event_id", "last_event_id", "events_total", "events_dropped", "partial_tail", "log_complete",
    "log_bytes", "log_dropped", "reused_bytes", "new_image_bytes", "selected_receipts", "closure_count"))
LANE_SPEC = {**dict.fromkeys(("status", "reason", "origin", "hero_seat", "confidence", "method",
    "recognizer", "artifact_version", "expires_at_unix_ms", "crop_bounds", "crop_sha256", "evidence_id",
    "owner", "seat", "occupant_epoch", "detected", "open", "revision", "bounds", "bounds_kind",
    "panel_geometry_qualified", "quality_approved", "provisional", "human_reviewed")), **dict.fromkeys(CLOCK_KEYS),
    "capture": CAPTURE_SPEC}
EVIDENCE_SPEC.update({lane: LANE_SPEC for lane in ("role", "roster", "occupancy", "identity", "profile")})
METRIC_SPEC = dict.fromkeys(("label", "literal", "percent", "status", "reason"))
STATS_SPEC = {**dict.fromkeys(("source", "owner", "seat", "occupant_epoch", "sample_size", "scope",
    "captured_at_unix_ms", "evidence_id", "status", "reason", "table_context_id", "revision")),
    **dict.fromkeys(("bounds", "crop_bounds", "crop_sha256", "method", "recognizer", "artifact_version",
                    "quality_approved", "provisional", "human_reviewed")),
    "capture": CAPTURE_SPEC, "metrics": {name: METRIC_SPEC for name in ("vpip", "pfr", "three_bet", "c_bet")},
    "evidence": EVIDENCE_SPEC, **dict.fromkeys(CLOCK_KEYS)}
EVENT_SPEC = {**dict.fromkeys(("event_id", "kind", "seat", "owner", "identity", "occupancy", "occupant_epoch",
    "continuity", "role", "hero_seat", "status", "reason", "evidence_id", "evidence_complete", "refs",
    "references", "table_context_id", "revision", "previous", "value", "captured_at_unix_ms", "changes",
    "crops", "order_status")),
    "capture": CAPTURE_SPEC, "evidence": EVIDENCE_SPEC, **dict.fromkeys(CLOCK_KEYS)}
CONTEXT_SPEC = {**dict.fromkeys(("role", "hero_seat", "table_context_id", "table_epoch", "status", "reason",
    "expires_at_unix_ms", "dropped_frames", "gaps", "event_cursor", "events_total", "events_dropped")),
    **dict.fromkeys(("quality_approved", "provisional", "human_reviewed", "recognizer", "method", "artifact_version")),
    **dict.fromkeys(CLOCK_KEYS), "capture": CAPTURE_SPEC,
    "seats": (6, {**dict.fromkeys(("seat", "occupancy", "identity", "occupant_epoch", "continuity", "status", "reason",
                                  "bounds", "crop_bounds", "crop_sha256")),
        "capture": CAPTURE_SPEC, "evidence": EVIDENCE_SPEC, "stats": STATS_SPEC}),
    "profile": {**LANE_SPEC, **STATS_SPEC}, "evidence": EVIDENCE_SPEC, "event_evidence": EVIDENCE_SPEC}
FIELD_STATUS_SPEC = dict.fromkeys(("status", "reason", "confidence", "expires_at_unix_ms", "captured_at_unix_ms",
                                 "admission_status", "admission_reason"))
FIELD_STATUS_SPEC.update(source_capture=CAPTURE_SPEC, capture=CAPTURE_SPEC)
FIELD_NAMES = ("pot", "pot_size", "board", "role", "hero_seat", "hero_seated", "action_required", *(
    f"seats.{seat}.{field}" for seat in range(1, 7) for field in
    ("displayed_stack", "visible_wager", "badge", "occupied", "status", "dealer", "small_blind", "big_blind", "acting")))
READING_SPEC = {**dict.fromkeys(("session_id", "source_id", "epoch", "generation", "captured_at_ms",
    "captured_at_unix_ms", "expires_at_unix_ms", "role", "hero_seat", "hero_seated", "pot", "board",
    "pot_size", "pot_size_text", "board_slots", "board_count", "game_phase")),
    "capture": CAPTURE_SPEC, "field_captures": {name: CAPTURE_SPEC for name in FIELD_NAMES},
    "original_capture": dict.fromkeys(("frame_index", "source_utc_unix_ms", "captured_at_monotonic_ms",
        "width", "height", "sha256", "native_source_id", "pixel_source", "readability", "occluded_regions")),
    "field_statuses": {name: FIELD_STATUS_SPEC for name in FIELD_NAMES},
    "seats": (6, dict.fromkeys(("seat", "displayed_stack", "visible_wager", "occupied", "occupant_epoch", "scene_fields")))}
ACTION_FIELD_SPEC = {**dict.fromkeys(("status", "reason", "value", "crop_bounds", "crop_sha256", "expires_at_ms")),
                     "source_capture": CAPTURE_SPEC}
VISUAL_SPEC = {**dict.fromkeys(("session_id", "source_id", "service_instance_id", "epoch", "sequence",
    "captured_at_ms", "captured_at_unix_ms", "sha256", "width", "height", "expires_at_unix_ms", "archival",
    "processing_ms", "dropped_frames", "gaps")), "capture": CAPTURE_SPEC,
    "board": dict.fromkeys(("candidate_cards", "reason", "template_artifacts", "status", "capture", "stage", "board_generation", "last_seen")),
    "board_slots": (5, {"slot": None, "card": None, "status": None, "reason": None, "capture": CAPTURE_SPEC, "bounds": None}),
    "actions": {"capture": CAPTURE_SPEC, "processing_ms": None,
        "seats": (6, {"seat": None, "badge": ACTION_FIELD_SPEC, "visible_wager": ACTION_FIELD_SPEC})}}
NUMERIC_FIELD_SPEC = {**dict.fromkeys(("literal", "value", "status", "reason", "bounds", "crop_sha256", "recognizer_version")), "capture": CAPTURE_SPEC}
NUMERIC_SPEC = {**dict.fromkeys(("source", "provisional", "quality_approved", "expires_at_unix_ms", "processing_ms", "published_at_unix_ms", "attempts", "dropped_frames")),
    "capture": CAPTURE_SPEC, "pot": NUMERIC_FIELD_SPEC,
    "seats": (6, {"seat": None, "stack": NUMERIC_FIELD_SPEC, "wager": NUMERIC_FIELD_SPEC})}
NATIVE_TIMING_KEYS = ("schema_version", "generation", "epoch", "captured_at_ms", "captured_at_unix_ms",
                      "emitted_at_unix_ms", "ingested_at_unix_ms", "api_snapshot_at_unix_ms")
NAMESPACE_SCOPE = (*CAPTURE_KEYS[:5], "width", "height")
NAMESPACE_SPEC = {**dict.fromkeys(("namespace_id", "status", "admitted_evidence", "semantics", "frozen_prefix",
    "workers_drained", "sequence", "retirement_reason")), "scope": dict.fromkeys(NAMESPACE_SCOPE),
    **{name: dict.fromkeys(("path", "bytes", "complete")) for name in ("visual_log", "context_log")},
    "archive": dict.fromkeys(("frames", "bytes", "log_bytes", "complete"))}
STATE_SPEC = {"schema_version": None, "session_id": None,
    "native_timing": dict.fromkeys(NATIVE_TIMING_KEYS),
    "server": dict.fromkeys(("instance_id", "model_state", "status")),
    "capture_session": dict.fromkeys(("session_id", "status", "activity_state", "stop_reason", "updated_at_unix_ms")),
    "capture": {**CAPTURE_SPEC, **dict.fromkeys(("state", "fresh_capture", "last_capture_at_unix_ms", "stop_reason"))},
    "partial_observation": READING_SPEC, "observation": READING_SPEC,
    "field_statuses": {name: FIELD_STATUS_SPEC for name in FIELD_NAMES},
    "visual_observation": VISUAL_SPEC, "table_context": CONTEXT_SPEC, "readout_evidence": EVIDENCE_SPEC,
    "numeric_observation": NUMERIC_SPEC, "numeric_diagnostics": dict.fromkeys(("attempts", "dropped_frames", "error")),
    "visual_diagnostics": {"schema_version": None, "namespace_overflow_count": None,
        "namespaces": (NAMESPACE_API_LIMIT, NAMESPACE_SPEC)},
    "event_evidence": EVIDENCE_SPEC, "context_diagnostics": dict.fromkeys(("log_path", "log_complete", "bytes",
        "dropped", "log_bytes", "log_dropped", "max_bytes", "error"))}


def bounded_value(value, issues, path, depth=0):
    if depth > 8 or isinstance(value, str) and len(value) > 4096:
        issues.append(path + ":value-limit")
        return None
    if isinstance(value, dict):
        if len(value) > 64:
            issues.append(path + ":object-limit")
            return None
        return {key: bounded_value(item, issues, path + "." + str(key), depth + 1)
                for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > 64:
            issues.append(path + ":array-limit")
            return None
        return [bounded_value(item, issues, path, depth + 1) for item in value]
    return value


def project_fields(value, spec, issues, path="state"):
    if spec is None:
        return bounded_value(value, issues, path)
    if isinstance(spec, tuple):
        if not isinstance(value, list):
            return bounded_value(value, issues, path)
        limit, child = spec
        if len(value) > limit:
            issues.append(path + ":array-limit")
        return [project_fields(item, child, issues, path) for item in value[:limit]]
    if not isinstance(value, dict):
        return bounded_value(value, issues, path)
    return {key: project_fields(value[key], child, issues, path + "." + key)
            for key, child in spec.items() if key in value}


class CompactProjection:
    """Bounded change journal; response hashes still identify the unprojected body."""

    def __init__(self, event_limit=EVENT_LIMIT, row_limit=EVENT_ROW_LIMIT):
        self.seen = {}
        self.event_limit, self.row_limit = event_limit, row_limit
        self.counts = collections.Counter()
        self.last_total = None
        self.namespace = None

    def changes(self, values, kind, spec, issues):
        if not isinstance(values, list):
            if values is not None or kind == "namespace":
                issues.append(kind + ":invalid-events")
            return []
        row_limit = min(self.row_limit, NAMESPACE_API_LIMIT) if kind == "namespace" else self.row_limit
        if len(values) > row_limit:
            self.counts["row_drops"] += len(values) - row_limit
            issues.append(kind + ":row-limit")
        result = []
        for value in values[:row_limit]:
            if not isinstance(value, dict):
                self.counts["invalid_events"] += 1
                issues.append(kind + ":invalid-event")
                continue
            if kind in ("context", "namespace"):
                identity = value.get("namespace_id" if kind == "namespace" else "event_id")
                if not (isinstance(identity, str) and 0 < len(identity) <= 256 or type(identity) is int and 0 < identity <= 2**53 - 1):
                    self.counts["invalid_events"] += 1
                    issues.append(kind + ":event-id-missing")
                    continue
            else:
                identity = dump({key: value.get(key) for key in
                    ("session_id", "source_id", "epoch", "sequence", "seat", "action", "captured_at_ms")})
            projected = project_fields(value, spec, issues, kind)
            digest = hashlib.sha256(json.dumps(projected, sort_keys=True, allow_nan=False,
                ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
            key = (kind, self.namespace, identity) if kind in ("context", "visual") else (kind, identity)
            if self.seen.get(key) == digest:
                self.counts["repeated_events"] += 1
                continue
            if key not in self.seen and len(self.seen) >= self.event_limit:
                self.counts["event_drops"] += 1
                issues.append(kind + ":event-limit")
                continue
            if kind == "namespace" and key not in self.seen:
                if self.counts["namespace_count"] >= NAMESPACE_LIMIT:
                    self.counts["namespace_drops"] += 1
                    issues.append("namespace:limit")
                    continue
                self.counts["namespace_count"] += 1
            self.counts["changed_events" if key in self.seen else "new_events"] += 1
            self.seen[key] = digest
            result.append(projected)
        return result

    def project(self, state, namespace_id=None):
        if namespace_id != self.namespace:
            self.last_total = None
            self.namespace = namespace_id
        issues = []
        projected = project_fields(state, STATE_SPEC, issues)
        context = state.get("table_context")
        if isinstance(context, dict):
            if namespace_id is not None:
                projected["table_context"]["diagnostic_namespace_id"] = namespace_id
            before = self.counts["new_events"]
            projected["table_context"]["events"] = self.changes(context.get("events"), "context", EVENT_SPEC, issues)
            total = context.get("events_total")
            if type(total) is int and total >= 0:
                if self.last_total is not None:
                    if total < self.last_total:
                        self.counts["cursor_regressions"] += 1
                        issues.append("context:event-total-regression")
                    missing = max(0, total - self.last_total - (self.counts["new_events"] - before))
                    if missing:
                        self.counts["cursor_drops"] += missing
                        issues.append("context:event-cursor-gap")
                self.last_total = total
            if type(context.get("events_dropped")) is int and context["events_dropped"] > 0:
                issues.append("context:producer-events-dropped")
        visual = state.get("visual_observation")
        if isinstance(visual, dict):
            spec = dict.fromkeys(("session_id", "source_id", "epoch", "sequence", "seat", "action", "captured_at_ms",
                                  "captured_at_unix_ms", "evidence_id", "capture", "status", "reason"))
            projected["visual_observation"]["sightings"] = self.changes(visual.get("sightings"), "visual", spec, issues)
        diagnostics = state.get("visual_diagnostics")
        if isinstance(diagnostics, dict) and "namespaces" in diagnostics:
            if (any(key in diagnostics and type(diagnostics[key]) is not bool
                    for key in ("namespaces_are_changes", "namespace_registry_cleared"))
                    or diagnostics.get("namespace_registry_cleared") is True and diagnostics["namespaces"]):
                issues.append("namespace:invalid-registry-flags")
            projected["visual_diagnostics"]["namespaces"] = self.changes(diagnostics["namespaces"], "namespace", NAMESPACE_SPEC, issues)
            projected["visual_diagnostics"]["namespaces_are_changes"] = True
            projected["visual_diagnostics"]["namespace_registry_cleared"] = bool(
                isinstance(diagnostics["namespaces"], list) and not diagnostics["namespaces"] and (
                    diagnostics.get("namespaces_are_changes") is not True or diagnostics.get("namespace_registry_cleared") is True))
        return projected, {"schema_version": 1, "complete": not issues,
            "histories_omitted": True, "events_are_changes": True,
            "response_sha256_scope": "unprojected-http-body", "issues": sorted(set(issues)),
            "event_counters": dict(self.counts), "last_declared_event_total": self.last_total,
            "cursor_coverage": "UNKNOWN" if self.last_total is None else "totals checked; initial prefix unknown",
            "event_limit": self.event_limit, "event_row_limit": self.row_limit}


def capture_key(capture):
    if not isinstance(capture, dict):
        raise ValueError("missing-capture")
    if capture.get("complete") is False:
        raise ValueError("capture-marked-incomplete")
    for key in CAPTURE_KEYS[:4]:
        if not isinstance(capture.get(key), str) or not 0 < len(capture[key]) <= 256:
            raise ValueError("capture-" + key)
    for key in ("epoch", "sequence", "captured_at_ms", "captured_at_unix_ms"):
        if type(capture.get(key)) is not int or capture[key] < 0:
            raise ValueError("capture-" + key)
    if not isinstance(capture.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", capture["sha256"]):
        raise ValueError("capture-sha256")
    if any(type(capture.get(key)) is not int or not 0 < capture[key] <= 16384 for key in ("width", "height")):
        raise ValueError("capture-dimensions")
    key = tuple(capture[name] for name in CAPTURE_KEYS)
    if "parent_capture" in capture:
        parent = capture["parent_capture"]
        if not isinstance(parent, dict) or "parent_capture" in parent:
            raise ValueError("popup-parent-capture")
        parent_key = capture_key(parent)
        window = capture.get("popup_window")
        binding = window.get("binding_id") if isinstance(window, dict) else None
        if (capture.get("non_atomic") is not True or type(capture.get("popup_index")) is not int
                or not 0 <= capture["popup_index"] <= 3 or not isinstance(window, dict)
                or set(window) != {"binding_id"}
                or not isinstance(binding, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,96}", binding)):
            raise ValueError("popup-receipt-proof")
        if (any(capture[name] != parent[name] for name in CAPTURE_KEYS[:5])
                or capture["captured_at_unix_ms"] < parent["captured_at_unix_ms"]
                or capture["captured_at_ms"] < parent["captured_at_ms"]):
            raise ValueError("popup-parent-scope-or-clock")
        key += (parent_key, capture["popup_index"], binding, True)
    elif capture.get("non_atomic") is True or capture.get("popup_index") is not None:
        raise ValueError("popup-parent-missing")
    return key


def sample_scope(state):
    context = state.get("table_context")
    capture = state.get("capture")
    context = context if isinstance(context, dict) else {}
    capture = capture if isinstance(capture, dict) else {}
    server, owner = state.get("server"), state.get("capture_session")
    server, owner = (value if isinstance(value, dict) else {} for value in (server, owner))
    return {"service_instance_id": server.get("instance_id"),
            "session_id": state.get("session_id"),
            "capture_session_id": owner.get("session_id"),
            "source_id": capture.get("source_id"), "epoch": capture.get("epoch"),
            "table_context_id": context.get("table_context_id"), "table_epoch": context.get("table_epoch")}


def boundary_reason(current, expected, session):
    if current["capture_session_id"] != session:
        return "capture-session-changed"
    for key in ("service_instance_id", "session_id"):
        if not isinstance(current[key], str) or not current[key]:
            return "missing-" + key
    if expected:
        for key, value in expected.items():
            if key in ("table_context_id", "table_epoch") and current.get(key) is None:
                continue  # A temporarily absent context is not a confirmed table change.
            if value is not None and current.get(key) != value:
                return "source-unavailable" if key == "source_id" and current[key] is None else key + "-changed"
    return None


def dump(value):
    return json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"))


def reject_constant(value):
    raise ValueError("nonfinite-json")


def private_path(value, base=PRIVATE):
    supplied = Path(value)
    path = (ROOT / supplied).resolve()
    if ".." in supplied.parts or not path.is_relative_to(base) or path == base:
        raise ValueError("path-must-be-private")
    return path


def utc_ms():
    return time.time_ns() // 1000000


def iso_us(text):
    stamp = dt.datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        raise ValueError("timestamp-without-zone")
    delta = stamp - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    return delta.days * 86400000000 + delta.seconds * 1000000 + delta.microseconds


def write_json(path, value):
    data = (dump(value) + "\n").encode("utf-8")
    if len(data) > OUTPUT_LIMIT:
        raise ValueError("report-byte-limit")
    with path.open("xb") as stream:
        stream.write(data)


def read_rows(path, metadata, byte_limit=INPUT_LIMIT, boundary_size=None, row_limit=None):
    info = {"path": str(path.relative_to(ROOT)), "rows": 0, "bytes": 0,
            "scanned_rows": 0, "invalid_rows": 0, "partial_tail": False, "capped": False}
    metadata.append(info)
    if not path.is_file():
        info["missing"] = True
        return []
    size = path.stat().st_size
    info["size_at_scan"] = size
    boundary = size if boundary_size is None else boundary_size
    if type(boundary) is not int or boundary < 0:
        raise ValueError("invalid-input-boundary")
    stop = min(size, byte_limit, boundary)
    info["capped"] = min(size, boundary) > stop
    if boundary_size is not None:
        info.update(size_at_collection_boundary=boundary, bytes_after_boundary=max(0, size - boundary),
                    shortened_since_boundary=size < boundary)
    rows, digest = [], hashlib.sha256()
    with path.open("rb") as stream:
        while stream.tell() < stop and info["scanned_rows"] < (ROW_LIMIT if row_limit is None else min(ROW_LIMIT, row_limit)):
            offset = stream.tell()
            raw = stream.readline(min(LINE_LIMIT + 1, stop - offset))
            digest.update(raw)
            info["bytes"] += len(raw)
            info["scanned_rows"] += 1
            if not raw.endswith(b"\n"):
                info["partial_tail"] = True
                break
            if len(raw) > LINE_LIMIT:
                info["capped"] = True
                break
            try:
                row = json.loads(raw, parse_constant=reject_constant)
                if not isinstance(row, dict):
                    raise ValueError("not-object")
                rows.append((offset, row))
            except (ValueError, UnicodeError, RecursionError):
                info["invalid_rows"] += 1
        info["capped"] |= stream.tell() < stop
    info.update(rows=len(rows), sha256_of_scanned_prefix=digest.hexdigest())
    return rows


class VisualNamespaces:
    """Bounded diagnostic namespace receipts, never a publication/admission ledger."""

    def __init__(self):
        self.entries, self.issues, self.scope = {}, collections.Counter(), None
        self.present = False
        self.overflow = 0
        self.active_paths = set()
        self._active = {}

    @staticmethod
    def integer(value):
        return type(value) is int and 0 <= value <= 2**53 - 1

    @staticmethod
    def context_path(state):
        value = state.get("context_diagnostics")
        return value.get("log_path") if isinstance(value, dict) else None

    def validate(self, value, scope):
        if (not isinstance(value, dict) or not isinstance(value.get("namespace_id"), str)
                or not re.fullmatch(r"uncommitted-[0-9a-f]{32}", value["namespace_id"])
                or value.get("status") not in ("active", "retired-uncommitted")
                or value.get("admitted_evidence") is not False
                or not isinstance(value.get("semantics"), str) or len(value["semantics"]) > 256
                or value["semantics"].split(";")[0] != "diagnostic-attempts-only"
                or type(value.get("frozen_prefix")) is not bool
                or value["frozen_prefix"] != (value["status"] == "retired-uncommitted")
                or type(value.get("workers_drained")) is not bool or not self.integer(value.get("sequence"))
                or value.get("scope") != scope or any(type(value["scope"].get(key)) is not type(scope[key]) for key in NAMESPACE_SCOPE)):
            raise ValueError("namespace-schema-or-scope")
        if value.get("retirement_reason") is not None and (not isinstance(value["retirement_reason"], str)
                or len(value["retirement_reason"]) > 256):
            raise ValueError("namespace-reason")
        result = project_fields(value, NAMESPACE_SPEC, [])
        directory = PRIVATE / "laya/events" / hashlib.sha256(scope["service_instance_id"].encode()).hexdigest()[:32] / value["namespace_id"]
        for kind in ("visual_log", "context_log"):
            log = value.get(kind)
            if (not isinstance(log, dict) or not self.integer(log.get("bytes")) or type(log.get("complete")) is not bool
                    or not isinstance(log.get("path"), str) or not 0 < len(log["path"]) <= 512
                    or Path(log["path"]).is_absolute() or Path(log["path"]).drive):
                raise ValueError("namespace-log-schema")
            path = private_path(log["path"], PRIVATE / "laya/events")
            # Exact service-hash/UUID/log binding also rejects symlink/junction substitutions.
            if path != directory / ("visual.jsonl" if kind == "visual_log" else "context.jsonl"):
                raise ValueError("namespace-log-path")
            result[kind]["path"] = str(path.relative_to(ROOT))
        archive = value.get("archive")
        if (not isinstance(archive, dict) or any(not self.integer(archive.get(key)) for key in ("frames", "bytes", "log_bytes"))
                or type(archive.get("complete")) is not bool):
            raise ValueError("namespace-archive-schema")
        return result

    def invalidate_active(self):
        self.active_paths = set()
        self._active = {}

    def observe(self, state):
        previous_active = self._active
        self.invalidate_active()
        diagnostics = state.get("visual_diagnostics")
        if not isinstance(diagnostics, dict) or "namespaces" not in diagnostics:
            if self.present:
                self.issues["registry-unavailable"] += 1
            return False
        self.present = True
        if (type(diagnostics.get("schema_version")) is not int or diagnostics["schema_version"] != 1
                or not isinstance(diagnostics.get("namespaces"), list)
                or not self.integer(diagnostics.get("namespace_overflow_count"))
                or any(key in diagnostics and type(diagnostics[key]) is not bool for key in ("namespaces_are_changes", "namespace_registry_cleared"))
                or diagnostics.get("namespace_registry_cleared") is True and diagnostics["namespaces"]):
            self.issues["registry-schema"] += 1
            return False
        capture = state.get("capture")
        current = {**sample_scope(state), **{key: capture.get(key) if isinstance(capture, dict) else None for key in ("width", "height")}}
        scope = {key: current.get(key) for key in NAMESPACE_SCOPE}
        if (any(not isinstance(scope[key], str) or not 0 < len(scope[key]) <= 256 for key in CAPTURE_KEYS[:4])
                or not self.integer(scope["epoch"]) or any(type(scope[key]) is not int or not 0 < scope[key] <= 16384 for key in ("width", "height"))
                or self.scope is not None and scope != self.scope):
            self.issues["registry-scope"] += 1
            return False
        self.scope = scope
        self.overflow = max(self.overflow, diagnostics["namespace_overflow_count"])
        if self.overflow:
            self.issues["producer-overflow"] = self.overflow
        values = diagnostics["namespaces"]
        active_paths = dict(previous_active) if diagnostics.get("namespaces_are_changes") is True and not diagnostics.get("namespace_registry_cleared") else {}
        valid, seen, active = len(values) <= NAMESPACE_API_LIMIT, set(), 0
        if not valid:
            self.issues["api-namespace-limit"] += 1
        identities = collections.Counter(value.get("namespace_id") for value in values[:NAMESPACE_API_LIMIT]
            if isinstance(value, dict) and isinstance(value.get("namespace_id"), str))
        for value in values[:NAMESPACE_API_LIMIT]:
            try:
                entry = self.validate(value, scope)
                identity = entry["namespace_id"]
                if identities[identity] > 1 or identity in seen:
                    raise ValueError("duplicate-namespace")
                seen.add(identity)
                active += entry["status"] == "active"
                if entry["status"] == "active":
                    active_paths[identity] = entry["context_log"]["path"]
                else:
                    active_paths.pop(identity, None)
                old = self.entries.get(identity)
                if old is None:
                    if len(self.entries) >= NAMESPACE_LIMIT:
                        self.issues["namespace-limit"] += 1
                        continue
                    self.entries[identity] = entry
                else:
                    if any(entry[kind]["path"] != old[kind]["path"] for kind in ("visual_log", "context_log")):
                        raise ValueError("namespace-path-change")
                    if old["frozen_prefix"]:
                        if not entry["frozen_prefix"] or any(entry[kind]["bytes"] != old[kind]["bytes"] for kind in ("visual_log", "context_log")):
                            self.issues["retired-prefix-change"] += 1
                        if not entry["frozen_prefix"]:
                            valid = False
                            active_paths.pop(identity, None)
                        old["workers_drained"] |= entry["workers_drained"]
                    else:
                        for kind in ("visual_log", "context_log"):
                            if entry[kind]["bytes"] < old[kind]["bytes"]:
                                self.issues["prefix-regression"] += 1
                                entry[kind]["bytes"] = min(entry[kind]["bytes"], old[kind]["bytes"])
                        self.entries[identity] = entry
                if any(not entry[kind]["complete"] for kind in ("visual_log", "context_log", "archive")):
                    self.issues["producer-incomplete"] += 1
            except (ValueError, TypeError, OSError) as error:
                reason = str(error)[:128] if isinstance(error, ValueError) else "namespace-path-io" if isinstance(error, OSError) else "namespace-type"
                self.issues[reason] += 1
                valid = False
        if active > 1 or len(active_paths) > 1:
            self.issues["multiple-active-namespaces"] += 1
            valid = False
        if diagnostics.get("namespaces_are_changes") is not True:
            for identity, old in self.entries.items():
                if not old["frozen_prefix"] and identity not in seen:
                    self.issues["unseen-retirement"] += 1
        if valid:
            self._active = active_paths
            self.active_paths = set(active_paths.values())
        return valid

    def snapshot(self):
        return {"schema_version": 1, "namespaces": list(self.entries.values()), "issues": dict(self.issues),
                "namespace_overflow_count": self.overflow, "complete": not self.issues,
                "limits": {"namespaces": NAMESPACE_LIMIT, "bytes": NAMESPACE_BYTES, "rows": NAMESPACE_ROWS}}

    def analyze(self, api, run, inputs):
        issues, counts, candidates = self.issues.copy(), collections.Counter(), []
        matched = set()
        for _, row in api[:ROW_LIMIT]:
            state = row.get("state")
            if not isinstance(state, dict):
                continue
            path = self.context_path(state)
            ids = [key for key, entry in self.entries.items() if entry["context_log"]["path"] == path]
            for kind, name in (("visual_log", "visual_observation"), ("context_log", "table_context")):
                reading = state.get(name)
                if isinstance(reading, dict):
                    try:
                        for identity in ids:
                            matched.add((identity, kind, capture_key(reading.get("capture"))))
                    except ValueError:
                        pass
        namespaces = []
        for identity, entry in sorted(self.entries.items()):
            public = {**entry, "inputs": {}}
            for kind in ("visual_log", "context_log"):
                # Revalidate paths at read time: a namespace can become a junction after collection.
                try:
                    self.validate(entry, self.scope)
                    path = ROOT / entry[kind]["path"]
                    boundary = min(entry[kind]["bytes"], run.get("input_sizes_at_end", {}).get(entry[kind]["path"], entry[kind]["bytes"]))
                    if not self.integer(boundary):
                        raise ValueError("namespace-input-boundary")
                    if boundary == 0:
                        info = {"path": entry[kind]["path"], "rows": 0, "bytes": 0, "scanned_rows": 0,
                            "expected_unopened": True, "size_at_collection_boundary": 0}
                        inputs.append(info)
                        rows = []
                    elif counts["scanned_bytes"] >= NAMESPACE_BYTES or counts["scanned_rows"] >= NAMESPACE_ROWS:
                        issues["aggregate-limit"] += 1
                        counts["unread_logs"] += 1
                        info, rows = {"path": entry[kind]["path"], "capped": True}, []
                        inputs.append(info)
                    else:
                        before = len(inputs)
                        try:
                            rows = read_rows(path, inputs, min(INPUT_LIMIT, NAMESPACE_BYTES - counts["scanned_bytes"]),
                                             boundary, NAMESPACE_ROWS - counts["scanned_rows"])
                        finally:
                            if len(inputs) > before:
                                counts["scanned_bytes"] += inputs[-1].get("bytes", 0)
                                counts["scanned_rows"] += inputs[-1].get("scanned_rows", 0)
                        info = inputs[-1]
                        for key, label in (("capped", "aggregate-or-input-limit"), ("partial_tail", "partial-tail"),
                                           ("missing", "missing-log"), ("invalid_rows", "invalid-json"),
                                           ("shortened_since_boundary", "shortened-log")):
                            if info.get(key):
                                issues[label] += 1
                    public["inputs"][kind] = info
                    for offset, record in rows:
                        try:
                            capture = record.get("capture")
                            key = capture_key(capture)
                            if (any(capture[name] != entry["scope"][name] for name in NAMESPACE_SCOPE)
                                    or any(not self.integer(capture[name]) for name in ("epoch", "sequence", "captured_at_ms", "captured_at_unix_ms"))
                                    or "generation" in capture and not self.integer(capture["generation"])):
                                raise ValueError("candidate-scope")
                            if not run["started_at_unix_ms"] <= capture["captured_at_unix_ms"] <= run["ended_at_unix_ms"]:
                                counts["outside_window"] += 1
                                continue
                            api_match = (identity, kind, key) in matched
                            candidates.append({"record_id": identity + ":" + kind + ":" + str(offset), "namespace_id": identity,
                                "kind": kind, "offset": offset, "capture": {name: capture[name] for name in CAPTURE_KEYS}, "api_source_match": api_match,
                                "admitted_evidence": False, "namespace_status": entry["status"]})
                            counts["api_matched_candidates"] += api_match
                        except (ValueError, TypeError, KeyError):
                            issues["invalid-candidate"] += 1
                except (ValueError, TypeError, OSError):
                    issues["invalid-read-binding"] += 1
            namespaces.append(public)
        counts.update(candidate_records=len(candidates))
        counts.setdefault("api_matched_candidates", 0)
        return {"schema_version": 1, "namespaces": namespaces, "counts": dict(counts), "issues": dict(issues),
            "candidates": candidates, "complete_coverage": False, "observed_prefixes_complete": not issues,
            "limits": self.snapshot()["limits"], "semantics": "diagnostic-attempt-candidates-only; API/DOM publication authoritative",
            "limitations": ["Namespace records are never merged into canonical current/continuity counts.",
                "Only collected prefix ceilings are scanned; retired late writes and unseen namespaces remain excluded.",
                "Archive counters are producer diagnostics; no archived image/index integrity scan is performed.",
                "API source matches are not proof of current DOM publication, numeric accuracy, or complete attempt coverage."]}


def merge_readouts(native, compact, perceptions, expected_target, expected_instance, expected_identity):
    """Prefer compact projections, keeping conflicts out of both timing series."""
    groups, errors, overlaps = {}, [], collections.Counter()
    others = [(offset, row, "native") for offset, row in native if row.get("event") != "perception_diagnostics"]
    for origin, records in (("native", native), ("compact", compact), ("perception", perceptions)):
        for offset, original in records:
            if original.get("event") != "perception_diagnostics":
                if origin == "compact":
                    errors.append({"origin": origin, "offset": offset, "reason": "unexpected-event"})
                continue
            try:
                if origin != "perception" and original.get("schema_version") != 2:
                    raise ValueError("schema-version")
                if isinstance(original.get("observation"), dict):
                    row = original
                    if expected_instance and row.get("service_instance_id") != expected_instance:
                        raise ValueError("service-instance")
                    identity = row.get("identity", row["observation"].get("identity"))
                    if expected_identity and (not isinstance(identity, dict) or any(
                            identity.get(key) != expected_identity.get(key) for key in ("exe_name", "process_id", "hwnd"))):
                        raise ValueError("native-identity")
                    if original.get("target_id") is not None and original["target_id"] != expected_target:
                        raise ValueError("target-id")
                elif isinstance(original.get("diagnostics"), dict):
                    if not expected_target or original.get("target_id") != expected_target:
                        raise ValueError("target-id")
                    if original.get("service_instance_id") is not None and original["service_instance_id"] != expected_instance:
                        raise ValueError("service-instance")
                    row = {**original["diagnostics"],
                           **{key: original.get(key) for key in ("event", "emitted_at_unix_ms", "expires_at_unix_ms", "valid_for_ms")},
                           "observation": {key: original.get(key) for key in
                                           ("generation", "epoch", "captured_at_ms", "captured_at_unix_ms")}}
                else:
                    raise ValueError("missing-source-ticket")
                ticket = row["observation"]
                if any(type(ticket.get(key)) is not int or ticket[key] < 0 for key in
                       ("generation", "epoch", "captured_at_ms", "captured_at_unix_ms")):
                    raise ValueError("source-clock-types")
                if type(row.get("emitted_at_unix_ms")) is not int or row["emitted_at_unix_ms"] < ticket["captured_at_unix_ms"]:
                    raise ValueError("emission-clock")
                if any(type(row.get(key)) is not int or not 0 < row[key] <= 16384 for key in ("frame_width", "frame_height")):
                    raise ValueError("frame-dimensions")
                passes, field_rows = row.get("passes"), row.get("fields")
                if not isinstance(passes, list) or not isinstance(field_rows, list):
                    raise ValueError("missing-passes-or-fields")
                selected = [item for item in passes if isinstance(item, dict)
                            and (item.get("pass") == "p3_pot" or re.fullmatch(r"p5_seat_[1-6]_stack", item.get("pass", "")))]
                if len({item["pass"] for item in selected}) != len(selected):
                    raise ValueError("duplicate-pass")
                pass_values = []
                for item in selected:
                    questions = item.get("questions")
                    if not isinstance(questions, list) or any(not isinstance(q, dict) or not isinstance(q.get("question"), str) for q in questions):
                        raise ValueError("question-schema")
                    if len({q["question"] for q in questions}) != len(questions):
                        raise ValueError("duplicate-question")
                    pass_values.append({"pass": item["pass"],
                        **{key: item.get(key) for key in ("segments", "crop_bounds", "crop_dimensions", "total_ms")},
                        "questions": sorted([{key: q.get(key) for key in ("question", "answer", "score")}
                                             for q in questions], key=lambda q: q["question"])})
                selected_fields = [field for field in field_rows if isinstance(field, dict) and field.get("field") == "displayed_stack"]
                projection = {"observation": {key: ticket[key] for key in
                              ("generation", "epoch", "captured_at_ms", "captured_at_unix_ms")},
                              **{key: row.get(key) for key in ("emitted_at_unix_ms", "expires_at_unix_ms", "valid_for_ms", "frame_width", "frame_height", "source_current", "admission")},
                              "passes": sorted(pass_values, key=lambda item: item["pass"]),
                              "fields": sorted([{key: field.get(key) for key in ("field", "seat", "admission_status", "admission_reason")}
                                                for field in selected_fields], key=lambda field: dump(field))}
                key = (ticket["epoch"], ticket["generation"])
                serialized = json.dumps(projection, sort_keys=True, allow_nan=False, separators=(",", ":"))
                evidence = {"origin": origin, "offset": offset, "projection_sha256": hashlib.sha256(serialized.encode()).hexdigest()}
                group = groups.setdefault(key, {"variants": {}, "origins": []})
                group["variants"].setdefault(serialized, []).append((offset, row, origin))
                group["origins"].append(evidence)
            except (ValueError, TypeError, KeyError) as exc:
                errors.append({"origin": origin, "offset": offset, "reason": str(exc)})
    chosen, conflicts, preference = [], [], {"compact": 0, "native": 1, "perception": 2}
    for key, group in groups.items():
        origins = {item["origin"] for item in group["origins"]}
        if len(group["variants"]) != 1:
            conflicts.append({"epoch": key[0], "generation": key[1], "evidence": group["origins"]})
            continue
        for left, right in (("compact", "native"), ("compact", "perception"), ("native", "perception")):
            overlaps[left + "_" + right] += left in origins and right in origins
        records = next(iter(group["variants"].values()))
        offset, row, origin = min(records, key=lambda item: preference[item[2]])
        chosen.append((offset, {**row, "measurement_evidence": group["origins"]}, origin))
    audit = {"preferred_source": "compact" if compact else "legacy-native/perception-fallback",
             "valid_unique_readouts": len(chosen), "chosen_origin_counts": dict(collections.Counter(item[2] for item in chosen)),
             "exact_projection_overlaps": dict(overlaps), "conflicting_source_tickets": conflicts,
             "validation_errors": errors, "overlap_equality": not conflicts,
             "note": "Equality covers original clocks, P3/P5 retained answers/scores/segments/crops/timing, dimensions and stack admission. Pruned question metadata is not invented. Conflicts are excluded, not resolved by proximity."}
    return others + sorted(chosen, key=lambda item: item[1]["observation"]["captured_at_ms"]), audit


def series(events, clock, start, end, monotonic=False, scale=1):
    ordered = sorted(events, key=lambda event: event[clock])
    values = [event[clock] for event in ordered]
    gaps = [(b - a) / scale for a, b in zip(values, values[1:])]
    overdue = [{"from": a, "to": b, "gap_ms": (b - a) / scale,
                "missed_10000ms_deadlines": max(0, math.ceil((b - a) / (DEADLINE * scale)) - 1)}
               for a, b in zip(values, values[1:]) if b - a > DEADLINE * scale]
    result = {"count": len(values), "clock": clock, "intervals_ms": gaps,
              "min_gap_ms": min(gaps, default=None), "median_gap_ms": statistics.median(gaps) if gaps else None,
              "max_gap_ms": max(gaps, default=None), "gaps_gt_10000ms": len(overdue),
              "missed_10000ms_deadlines": sum(item["missed_10000ms_deadlines"] for item in overdue),
              "overdue_intervals": overdue}
    if not monotonic:
        first, last = (values[0], values[-1]) if values else (None, None)
        edge_gaps = [(first - start * scale) / scale, (end * scale - last) / scale] if values else [end - start]
        result.update(leading_gap_ms=edge_gaps[0], trailing_gap_ms=edge_gaps[-1],
                       max_gap_including_edges_ms=max([*gaps, *edge_gaps]),
                       censored_edges_gt_10000ms=sum(gap > DEADLINE for gap in edge_gaps))
        result["missed_10000ms_deadlines_including_censored_edges"] = (
            result["missed_10000ms_deadlines"]
            + sum(max(0, math.ceil(gap / DEADLINE) - 1) for gap in edge_gaps))
    return result


def pass_signature(item, logged=False, include_truncated=True):
    answers = item.get("answers", {}) if logged else {
        q["question"]: {"v": q.get("answer", {}).get("value") if isinstance(q.get("answer"), dict) else None,
                        "p": q.get("score"), "truncated": q.get("truncated")}
        for q in item.get("questions", []) if q.get("answer") is not None}
    # Exact equality of the shared subset, not a guessed timestamp association.
    names = ("v", "p", "truncated") if include_truncated else ("v", "p")
    values = {key: {name: value.get(name) for name in names}
              for key, value in answers.items()}
    return json.dumps({"pass": item.get("pass"), "segments": item.get("segments"), "answers": values},
                      sort_keys=True, allow_nan=False, separators=(",", ":"))


def analyze_visual(native, api, logged, frames, start, end):
    offered, producer_index = [], collections.defaultdict(list)
    for offset, row in native:
        frame = row.get("frame")
        if row.get("event") != "visual_frame" or not isinstance(frame, dict):
            continue
        key = (frame.get("source_utc_unix_ms"), frame.get("captured_at_monotonic_ms"),
               frame.get("frame_index"), frame.get("sha256"))
        event = {"native_offset": offset, "frame": frame, "identity": row.get("identity"),
                 "capture_directory": row.get("capture_directory"), "service_instance_id": row.get("service_instance_id"),
                 "captured_at_unix_ms": key[0], "captured_at_ms": key[1]}
        producer_index[key].append(event)
        if type(key[0]) is int and type(key[1]) is int and start <= key[0] <= end:
            offered.append(event)
    scoped_api = [(offset, row) for offset, row in api if isinstance(row.get("state"), dict)]
    first_state = scoped_api[0][1]["state"] if scoped_api else {}
    api_session, instance = first_state.get("session_id"), first_state.get("server", {}).get("instance_id")
    source_id = first_state.get("capture", {}).get("source_id")
    candidates = [(offset, value, "visual-log") for offset, value in logged]
    present, absent, arrival_expired, ages, api_visual = 0, 0, 0, [], []
    for offset, row in scoped_api:
        state, sampled = row["state"], row["sampled_at_unix_ms"]
        value = state.get("visual_observation")
        if value is None:
            absent += 1
            continue
        present += 1
        if not isinstance(value, dict):
            continue
        candidates.append((offset, value, "api"))
        captured = value.get("captured_at_unix_ms")
        if type(captured) is int:
            ages.append(sampled - captured)
            arrival_expired += not 0 <= sampled - captured < 1500
        api_visual.append({"api_offset": offset, "sampled_at_unix_ms": sampled,
                           "captured_at_unix_ms": captured, "captured_at_ms": value.get("captured_at_ms"),
                           "sequence": value.get("sequence"), "sha256": value.get("sha256"),
                           "expires_at_unix_ms": value.get("expires_at_unix_ms")})
    completed, sightings, rejected = {}, {}, collections.Counter()
    for offset, value, origin in candidates:
        captured, mono = value.get("captured_at_unix_ms"), value.get("captured_at_ms")
        if type(captured) is not int or type(mono) is not int or not start <= captured <= end:
            continue
        if (value.get("session_id") != api_session or value.get("service_instance_id") != instance
                or value.get("source_id") != source_id):
            rejected["scope-mismatch"] += 1
            continue
        key = (captured, mono, value.get("sequence"), value.get("sha256"))
        source = {name: value.get(name) for name in ("session_id", "source_id", "epoch", "sequence", "captured_at_ms")}
        actions = value.get("actions") or {}
        seats = actions.get("seats")
        if (actions.get("capture") != source or not isinstance(seats, list)
                or sorted(item.get("seat", 0) for item in seats) != list(range(1, 7))
                or any(item.get(family, {}).get("source_capture") != source
                       for item in seats for family in ("badge", "visible_wager"))):
            rejected["six-crop-source-mismatch"] += 1
            continue
        matches = producer_index.get(key, [])
        source_frames = frames.get((captured, mono), [])
        manifest_matches = [frame for frame in source_frames if frame.get("sha256") == key[3]
                            and frame.get("frame_index") == key[2]
                            and [frame.get("width"), frame.get("height")] == [value.get("width"), value.get("height")]]
        seats = sorted(seats, key=lambda item: item["seat"])
        event = completed.get(key)
        if event is None:
            event = {"captured_at_unix_ms": captured, "captured_at_ms": mono, "capture": source,
                     "sha256": value.get("sha256"), "expires_at_unix_ms": value.get("expires_at_unix_ms"),
                     "archival": value.get("archival"), "processing_ms": value.get("processing_ms"),
                     "action_processing_ms": actions.get("processing_ms"), "board": value.get("board", {}).get("candidate_cards"),
                     "board_reason": value.get("board", {}).get("reason"), "native_exact_match_count": len(matches),
                     "native_frame": matches[0] if len(matches) == 1 else None,
                     "manifest_exact_match_count": len(manifest_matches),
                     "manifest_frame": manifest_matches[0] if len(manifest_matches) == 1 else None,
                     "origins": [], "dropped_frames": value.get("dropped_frames"), "gaps": value.get("gaps"),
                     "seats": [{"seat": item["seat"], **{
                         family: {name: item[family].get(name) for name in ("status", "crop_bounds", "crop_sha256", "expires_at_ms")}
                         | {"literal": (item[family].get("value") or {}).get("value" if family == "badge" else "literal")}
                         for family in ("badge", "visible_wager")}} for item in seats]}
            completed[key] = event
        event["origins"].append({"kind": origin, "offset": offset})
        for sighting in value.get("sightings", []):
            if isinstance(sighting, dict):
                sid = (source["session_id"], source["source_id"], source["epoch"], sighting.get("sequence"),
                       sighting.get("seat"), sighting.get("action"), sighting.get("captured_at_ms"))
                sightings[sid] = {**sighting, "scope": {name: source[name] for name in ("session_id", "source_id", "epoch")},
                                  "observed_in_snapshot_utc": captured}
    events = sorted(completed.values(), key=lambda item: item["captured_at_ms"])
    api_unique = {}
    for item in api_visual:
        api_unique.setdefault((item["captured_at_unix_ms"], item["sequence"], item["sha256"]), item)
    mono_index = collections.defaultdict(list)
    for sources in producer_index.values():
        for producer in sources:
            mono_index[producer["captured_at_ms"]].append(producer)
    in_window_sightings = []
    for sighting in sightings.values():
        originals = mono_index.get(sighting.get("captured_at_ms"), [])
        if len(originals) != 1 or not start <= originals[0]["captured_at_unix_ms"] <= end:
            continue
        in_window_sightings.append({**sighting, "original_source": originals[0]})
    metrics = {}
    for seat in range(1, 7):
        metrics[str(seat)] = {}
        for family in ("badge", "visible_wager"):
            results = [event for event in events if event["seats"][seat - 1][family]["status"] == "provisional"
                       and event["seats"][seat - 1][family]["literal"] is not None]
            metrics[str(seat)][family] = {
                "processed_attempts": series(events, "captured_at_ms", start, end, True),
                "provisional_literal_results": series(results, "captured_at_ms", start, end, True),
                "statuses": dict(collections.Counter(event["seats"][seat - 1][family]["status"] for event in events)),
                "literal_types": dict(collections.Counter(event["seats"][seat - 1][family]["literal"] for event in results))}
    for seat in range(1, 7):
        for family in ("badge", "visible_wager"):
            presence = collections.Counter()
            seen = {}
            for _, row in scoped_api:
                value = row["state"].get("visual_observation")
                if not isinstance(value, dict):
                    presence["visual_absent_samples"] += 1
                    continue
                key = (value.get("captured_at_unix_ms"), value.get("captured_at_ms"), value.get("sequence"), value.get("sha256"))
                event = completed.get(key)
                if event is None:
                    presence["unconfirmed_source_samples"] += 1
                    continue
                field = event["seats"][seat - 1][family]
                presence["field_present_samples"] += 1
                presence[str(field["status"]) + "_samples"] += 1
                if field["status"] == "provisional" and field["literal"] is not None:
                    presence["literal_samples"] += 1
                    seen.setdefault(key, {"sampled_at_unix_ms": row["sampled_at_unix_ms"]})
            metrics[str(seat)][family].update(api_presence=dict(presence),
                api_first_literal_result=series(list(seen.values()), "sampled_at_unix_ms", start, end))
    phases = {}
    for label, lo, hi in (("collection_first_120s", start, min(end, start + 120000)),
                          ("collection_after_120s", min(end, start + 120000), end),
                          ("collection_last_120s", max(start, end - 120000), end)):
        phase = [event for event in events if lo <= event["captured_at_unix_ms"] < hi]
        times = [event["processing_ms"] for event in phase if type(event.get("processing_ms")) in (int, float)]
        phases[label] = {"window_start_unix_ms": lo, "window_end_unix_ms": hi,
                         "confirmed_processed": series(phase, "captured_at_ms", lo, hi, True),
                         "processing_max_ms": max(times, default=None),
                         "processing_median_ms": statistics.median(times) if times else None}
    processing = [event["processing_ms"] for event in events if type(event.get("processing_ms")) in (int, float)]
    artifacts = collections.Counter(dump(value.get("board", {}).get("template_artifacts"))
                for _, value, _ in candidates if isinstance(value, dict)
                and start <= value.get("captured_at_unix_ms", 0) <= end
                and value.get("session_id") == api_session and value.get("service_instance_id") == instance)
    return {"provisional_only": True, "human_verified": False,
            "board_artifact_metadata": [{"metadata": json.loads(key), "observations": count} for key, count in artifacts.items()],
            "native_offered_frames": series(offered, "captured_at_ms", start, end, True),
            "confirmed_processed_frames": series(events, "captured_at_ms", start, end, True),
            "api_first_presence": series(list(api_unique.values()), "sampled_at_unix_ms", start, end),
            "api_presence": {"present": present, "absent": absent, "transport_errors": len(api) - len(scoped_api),
                             "expired_at_arrival": arrival_expired, "max_source_age_at_arrival_ms": max(ages, default=None)},
            "processing_max_ms": max(processing, default=None),
            "processing_median_ms": statistics.median(processing) if processing else None,
            "action_processing_max_ms": max((e["action_processing_ms"] for e in events if type(e.get("action_processing_ms")) in (int, float)), default=None),
            "exact_native_frame_matches": sum(event["native_exact_match_count"] == 1 for event in events),
            "exact_manifest_matches": sum(event["manifest_exact_match_count"] == 1 for event in events),
            "board_candidates": dict(collections.Counter(dump(event["board"]) for event in events)),
            "sighting_types": dict(collections.Counter(item.get("action") for item in in_window_sightings)),
            "sightings": in_window_sightings, "seats": metrics, "phases": phases,
            "source_events": events, "offered_events": offered, "api_events": api_visual,
            "rejected_records": dict(rejected),
            "limitations": ["Offered frames are not proof every worker crop completed.",
                            "Completed records are a deduplicated lower bound from bounded visual log and 1Hz API snapshots.",
                            "visual.jsonl is capped at 8MiB and stops with the archival prefix; API may observe later rolling frames.",
                            "Unknown and explicit clear are not literal action sightings or native field admission.",
                            "Empty candidate board is absence-only, not proof of preflop, table context, or hand boundary.",
                            "Phases isolate time windows only; CPU test contention is not attributed without separate evidence."]}


def interval_report(events, clock, start, end, monotonic=False):
    result = series(events, clock, start, end, monotonic)
    result.update(coverage="OBSERVED" if events else "NOT OBSERVED",
                  deadline_result="FAIL" if result["gaps_gt_10000ms"] else "UNKNOWN",
                  complete_attempt_coverage=False)
    return result


def identity_name(identity):
    if isinstance(identity, str):
        return identity if identity.strip() else None
    if not isinstance(identity, dict) or identity.get("status") in (
            "unknown", "uncertain", "ambiguous", "truncated", "duplicate", "unreadable", "rejected"):
        return None
    name = identity.get("name", identity.get("value"))
    return name if isinstance(name, str) and name.strip() else None


def validate_stats(stats, seat, context_capture, table_context_id=None, sampled_at_unix_ms=None):
    capture_key(stats.get("capture"))
    capture = stats["capture"]
    if any(capture[key] != context_capture[key] for key in CAPTURE_KEYS[:5]):
        raise ValueError("stats-source-scope")
    if stats.get("source") != "client_profile_tooltip":
        raise ValueError("stats-source")
    if (type(stats.get("seat")) is not int or stats["seat"] != seat["seat"]
            or type(stats.get("occupant_epoch")) is not int or stats["occupant_epoch"] < 0
            or stats["occupant_epoch"] != seat.get("occupant_epoch")
            or seat.get("occupancy") != "occupied" or identity_name(seat.get("identity")) is None
            or stats.get("owner") != identity_name(seat.get("identity"))):
        raise ValueError("stats-owner-or-occupant")
    if (stats.get("table_context_id") is not None and stats["table_context_id"] != table_context_id):
        raise ValueError("stats-table-context")
    parent = capture.get("parent_capture", capture)
    if "parent_capture" in capture and [parent["width"], parent["height"]] != [context_capture["width"], context_capture["height"]]:
        raise ValueError("stats-parent-geometry")
    if (type(stats.get("captured_at_unix_ms")) is not int
            or stats["captured_at_unix_ms"] != capture["captured_at_unix_ms"]
            or parent["captured_at_unix_ms"] > context_capture["captured_at_unix_ms"]
            or parent["captured_at_ms"] > context_capture["captured_at_ms"]
            or sampled_at_unix_ms is not None and capture["captured_at_unix_ms"] > sampled_at_unix_ms):
        raise ValueError("stats-original-clock")
    if not isinstance(stats.get("metrics"), dict):
        raise ValueError("stats-metrics")


def load_ui_receipts(path, metadata):
    if path is None:
        return [], {"requested": False, "coverage": "NOT OBSERVED"}
    info = {"path": str(path.relative_to(ROOT)), "requested": True, "read_at_unix_ms": utc_ms(),
            "rows": 0, "invalid_rows": 0, "capped": False, "partial_tail": False,
            "byte_limit": UI_RECEIPT_LIMIT, "row_limit": EVENT_LIMIT}
    metadata.append(info)
    if not path.is_file():
        info.update(missing=True, complete=False)
        return [], info
    size = path.stat().st_size
    info["size_at_scan"] = size
    if size > UI_RECEIPT_LIMIT:
        info.update(capped=True, complete=False, reason="ui-byte-limit")
        return [], info
    with path.open("rb") as stream:
        raw = stream.read(UI_RECEIPT_LIMIT + 1)
    if len(raw) > UI_RECEIPT_LIMIT:
        info.update(capped=True, complete=False, reason="ui-byte-limit-after-stat")
        return [], info
    info.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    try:
        value = json.loads(raw, parse_constant=reject_constant)
        envelope = value if isinstance(value, dict) else {}
        records = envelope.get("receipts") if envelope else value
        if not isinstance(records, list):
            raise ValueError("ui-receipts-array")
        dropped = envelope.get("dropped", 0)
        if type(dropped) is not int or dropped < 0:
            raise ValueError("ui-drop-counter")
        info.update(dropped=dropped, capacity=envelope.get("capacity"), clock_origins=envelope.get("clock_origins"),
                    exported_at_unix_ms=envelope.get("exported_at_unix_ms"),
                    capped=len(records) > EVENT_LIMIT, complete=not dropped and len(records) <= EVENT_LIMIT)
        kept = [row for row in records[:EVENT_LIMIT] if isinstance(row, dict)]
        info.update(rows=len(kept), invalid_rows=min(len(records), EVENT_LIMIT) - len(kept))
        info["complete"] &= not info["invalid_rows"]
        return kept, info
    except (ValueError, UnicodeError, RecursionError) as exc:
        info.update(complete=False, partial_tail=True, reason=str(exc))
        return [], info


def analyze_context(api, run, ui_receipts=(), ui_info=None, native_attempts=(), attempt_info=None, namespace_receipts=None):
    """Context DTO timing is independent of legacy numeric/visual admission."""
    start, end = run["started_at_unix_ms"], run["ended_at_unix_ms"]
    rejected, counters, roles = collections.Counter(), collections.Counter(), collections.Counter()
    per_seat = {seat: {"attempts": {}, "occupancy": {}, "identity": {}, "imports": {},
        "occupancy_samples": collections.Counter(), "identity_samples": collections.Counter(),
        "profile_rejections": collections.Counter(), "metric_statuses": collections.Counter(),
        "duration": {family: collections.Counter() for family in ("occupancy", "identity", "profile")}}
        for seat in range(1, 7)}
    contexts, role_readings, events, references, evidence_states, native_contexts = {}, {}, {}, {}, [], {}
    producer_states, native_profiles = [], collections.Counter()
    profile_variants, sample_classes = collections.defaultdict(set), []
    expected = {"capture_session_id": run.get("session"), "service_instance_id": run.get("service_instance"),
                "session_id": run.get("api_session"), "source_id": run.get("source_id"), "epoch": run.get("source_epoch"),
                "table_context_id": run.get("table_context_id"), "table_epoch": run.get("scope", {}).get("table_epoch")}

    def original(capture, scope, offset):
        key = capture_key(capture)
        for name in CAPTURE_KEYS[:5]:
            if scope.get(name) is None or capture[name] != scope[name]:
                raise ValueError("capture-scope-" + name)
            if expected.get(name) is not None and capture[name] != expected[name]:
                raise ValueError("run-scope-" + name)
        for name in ("table_context_id", "table_epoch"):
            if capture.get(name) is not None and expected.get(name) is not None and capture[name] != expected[name]:
                raise ValueError("run-scope-" + name)
        if start <= capture["captured_at_unix_ms"] <= end:
            references.setdefault(key, {"capture": capture, "api_offset": offset})
        return key

    for offset, row in api:
        sampled = row.get("sampled_at_unix_ms")
        if type(sampled) is not int or not start <= sampled <= end:
            continue
        classes = {seat: dict.fromkeys(("occupancy", "identity", "profile"), "unknown") for seat in per_seat}
        sample_classes.append((sampled, classes))
        state = row.get("state")
        if not isinstance(state, dict):
            counters["transport_unknown_samples"] += 1
            continue
        scope = sample_scope(state)
        if boundary_reason(scope, {key: value for key, value in expected.items() if value is not None}, run.get("session")):
            rejected["sample-scope-mismatch"] += 1
            continue
        for name, value in scope.items():
            if value is not None and expected.get(name) is None:
                expected[name] = value
        for name in ("event_evidence", "context_diagnostics"):
            if isinstance(state.get(name), dict):
                producer_states.append({"api_offset": offset, "sampled_at_unix_ms": sampled,
                                        "producer": name, "status": state[name]})
        for name in ("partial_observation", "observation", "visual_observation"):
            reading = state.get(name)
            if isinstance(reading, dict):
                possible = [reading.get("capture"), *(reading.get("field_captures") or {}).values()]
                for capture in possible:
                    if isinstance(capture, dict):
                        try:
                            original(capture, scope, offset)
                        except ValueError:
                            pass  # Incomplete legacy refs are not upgraded using a newer context.
        context = state.get("table_context")
        if not isinstance(context, dict):
            counters["context_absent_samples"] += 1
            continue
        try:
            capture = context.get("capture")
            key = original(capture, scope, offset)
            if capture["captured_at_unix_ms"] > sampled:
                raise ValueError("future-context-capture")
        except ValueError as exc:
            rejected[str(exc)] += 1
            continue
        counters["context_present_samples"] += 1
        profile = context.get("profile")
        if isinstance(profile, dict):
            counters["profile_status_" + str(profile.get("status", "unknown"))] += 1
            counters["profile_detection_unknown_samples"] += type(profile.get("detected")) is not bool
            counters["profile_detected_samples"] += profile.get("detected") is True
        else:
            counters["profile_detection_unknown_samples"] += 1
        in_source_window = start <= capture["captured_at_unix_ms"] <= end
        event = {"capture": capture, "api_offset": offset, "sampled_at_unix_ms": sampled,
                 "captured_at_unix_ms": capture["captured_at_unix_ms"], "captured_at_ms": capture["captured_at_ms"],
                 "source_to_first_api_visibility_ms": sampled - capture["captured_at_unix_ms"],
                 **{clock: context.get(clock) for clock in CLOCK_KEYS}}
        clocks = [context.get(clock) for clock in CLOCK_KEYS[:3] if context.get(clock) is not None]
        if (any(type(clock) is not int or clock < 0 for clock in clocks) or clocks != sorted(clocks)
                or type(context.get("completed_at_unix_ms")) is int and context["completed_at_unix_ms"] > sampled):
            rejected["context-work-clocks"] += 1
            for clock in CLOCK_KEYS[:3]:
                event[clock] = None
        if in_source_window:
            contexts.setdefault(key, event)
        evidence = context.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        if isinstance(evidence, dict):
            evidence_states.append({"api_offset": offset, "sampled_at_unix_ms": sampled, "evidence": evidence})
        role, hero = context.get("role"), context.get("hero_seat")
        roles[str(role)] += 1
        role_evidence = evidence.get("role", {})
        role_evidence = role_evidence if isinstance(role_evidence, dict) else {}
        role_valid = role == "observing" and hero is None and role_evidence.get("origin") == "observer_controls"
        role_valid |= (role in ("seated_waiting", "your_turn") and type(hero) is int and 1 <= hero <= 6
                       and role_evidence.get("hero_seat") == hero and role_evidence.get("origin") == (
                           "own_action_controls" if role == "your_turn" else "self_player"))
        role_valid &= role_evidence.get("status") not in ("unknown", "rejected", "expired", "occluded")
        if role == "observing" and hero is not None:
            rejected["hero-while-observing"] += 1
        if role_valid:
            try:
                role_valid = original(role_evidence.get("capture"), scope, offset) == key
            except ValueError:
                role_valid = False
        if role_valid and in_source_window:
            role_readings.setdefault(key, {**event, "role": role, "hero_seat": hero})
        elif role not in (None, "uncertain"):
            rejected["role-evidence-unknown"] += 1
        seat_rows = context.get("seats")
        if not isinstance(seat_rows, list):
            seat_rows = []
        seen_seats = collections.Counter(item.get("seat") for item in seat_rows
            if isinstance(item, dict) and type(item.get("seat")) is int and 1 <= item["seat"] <= 6)
        names = collections.Counter(identity_name(item.get("identity")) for item in seat_rows if isinstance(item, dict))
        rejected["invalid-or-duplicate-seat"] += sum(not isinstance(item, dict) or type(item.get("seat")) is not int
            or not 1 <= item["seat"] <= 6 for item in seat_rows) + sum(count - 1 for count in seen_seats.values())
        for seat in per_seat:
            data = per_seat[seat]
            item = next((item for item in seat_rows if isinstance(item, dict) and type(item.get("seat")) is int
                         and item["seat"] == seat), {}) if seen_seats[seat] == 1 else {}
            occupancy, name = item.get("occupancy", "unknown"), identity_name(item.get("identity"))
            if name and names[name] > 1:
                name = None
                data["profile_rejections"]["duplicate-identity"] += isinstance(item.get("stats"), dict)
            data["occupancy_samples"][str(occupancy)] += 1
            data["identity_samples"]["known" if name else "unknown"] += 1
            if item and in_source_window:
                data["attempts"].setdefault(key, event)
            fresh = sampled - capture["captured_at_unix_ms"] < 5000
            if type(context.get("expires_at_unix_ms")) is int:
                fresh &= sampled < context["expires_at_unix_ms"]
            if not fresh:
                classes[seat] = dict.fromkeys(classes[seat], "stale")
            elif item.get("status") == "occluded" or item.get("reason") in (
                    "occluded", "region-occluded", "current-region-occluded"):
                classes[seat] = dict.fromkeys(classes[seat], "occluded")
            confirmed = item.get("continuity") == "confirmed" and item.get("status") == "confirmed"
            if fresh and confirmed and occupancy in ("occupied", "empty"):
                classes[seat]["occupancy"] = "known"
                if in_source_window:
                    data["occupancy"].setdefault(key, {**event, "occupancy": occupancy})
            if fresh and confirmed and name and occupancy == "occupied":
                classes[seat]["identity"] = "known"
                if in_source_window:
                    data["identity"].setdefault(key, {**event, "identity": name, "occupant_epoch": item.get("occupant_epoch")})
            stats = item.get("stats")
            if not isinstance(stats, dict):
                continue
            try:
                if name is None or item.get("continuity") != "confirmed":
                    raise ValueError("stats-identity-uncertain")
                validate_stats(stats, item, capture, context.get("table_context_id"), sampled)
                stats_key = original(stats["capture"], scope, offset)
            except ValueError as exc:
                data["profile_rejections"][str(exc)] += 1
                continue
            if fresh:
                classes[seat]["profile"] = "last_observed" if stats.get("status") == "last_observed" else "known"
            import_key = (stats_key, stats["owner"], stats["occupant_epoch"])
            profile_variants[import_key].add(json.dumps(stats["metrics"], sort_keys=True, allow_nan=False,
                ensure_ascii=True, separators=(",", ":")))
            if start <= stats["capture"]["captured_at_unix_ms"] <= end and import_key not in data["imports"]:
                imported = {"capture": stats["capture"], "captured_at_unix_ms": stats["captured_at_unix_ms"],
                    "captured_at_ms": stats["capture"]["captured_at_ms"], "api_offset": offset,
                    "sampled_at_unix_ms": sampled, "stats": stats, "owner_validated": True,
                    "source_to_first_api_visibility_ms": sampled - stats["captured_at_unix_ms"]}
                data["imports"][import_key] = imported
        candidates = context.get("events")
        if candidates is not None and not isinstance(candidates, list):
            rejected["invalid-event-array"] += 1
        for candidate in candidates if isinstance(candidates, list) else []:
            if (not isinstance(candidate, dict) or not (
                    isinstance(candidate.get("event_id"), str) and 0 < len(candidate["event_id"]) <= 256
                    or type(candidate.get("event_id")) is int and 0 < candidate["event_id"] <= 2**53 - 1)
                    or not isinstance(candidate.get("kind"), str)):
                rejected["invalid-event"] += 1
                continue
            try:
                event_key = original(candidate.get("capture"), scope, offset)
            except ValueError as exc:
                rejected["event-" + str(exc)] += 1
                continue
            if not start <= candidate["capture"]["captured_at_unix_ms"] <= end:
                counters["events_original_outside_window"] += 1
                continue
            namespace_id = (namespace_receipts or {}).get(offset)
            if namespace_receipts is not None and offset in namespace_receipts and namespace_id is None:
                rejected["event-namespace-unavailable"] += 1
                continue
            scoped_id = (namespace_id, candidate["event_id"]) if namespace_id is not None else candidate["event_id"]
            previous = events.get(scoped_id)
            if previous and (capture_key(previous["capture"]) != event_key
                    or any(previous.get(field) != candidate.get(field) for field in ("kind", "seat", "owner", "occupant_epoch"))):
                rejected["event-id-conflict"] += 1
                previous["conflicting_id"] = True
                continue
            events[scoped_id] = {**candidate, "api_offset": offset, "diagnostic_namespace_id": namespace_id,
                "conflicting_id": bool(previous and previous.get("conflicting_id"))}

    reference_scope = next((sample_scope(row["state"]) for _, row in api if isinstance(row.get("state"), dict)
        and boundary_reason(sample_scope(row["state"]), {key: value for key, value in expected.items()
            if value is not None}, run.get("session")) is None), None)
    for offset, row in native_attempts:
        if row.get("event") != "context_attempt":
            rejected["native-context-unexpected-event"] += 1
            continue
        try:
            capture = row.get("capture")
            key = capture_key(capture)
            if reference_scope is None or any(capture[name] != reference_scope.get(name) for name in CAPTURE_KEYS[:5]):
                raise ValueError("native-context-scope")
            for name in ("table_context_id", "table_epoch"):
                value = row.get(name, capture.get(name))
                if value is not None and expected.get(name) is not None and value != expected[name]:
                    raise ValueError("native-context-" + name)
            if not start <= capture["captured_at_unix_ms"] <= end:
                continue
            clocks = [row.get(clock) for clock in CLOCK_KEYS[:3] if row.get(clock) is not None]
            if any(type(clock) is not int or clock < 0 for clock in clocks) or clocks != sorted(clocks):
                raise ValueError("native-context-work-clocks")
        except ValueError as exc:
            rejected[str(exc)] += 1
            continue
        attempt_key = (key, row.get("requested_at_unix_ms"), row.get("attempt_started_at_unix_ms"))
        event = {"capture": capture, "native_context_offset": offset,
            "captured_at_unix_ms": capture["captured_at_unix_ms"], "captured_at_ms": capture["captured_at_ms"],
            "error": row.get("error"), **{clock: row.get(clock) for clock in CLOCK_KEYS}}
        native_contexts.setdefault(attempt_key, event)
        counters["native_context_error_records"] += row.get("error") is not None
        profile = row.get("profile")
        if isinstance(profile, dict):
            native_profiles[str(profile.get("status", "unknown"))] += 1
        else:
            native_profiles["unknown"] += 1

    ordered_samples = sorted(sample_classes, key=lambda item: item[0])
    maximum_hold = max(1000, min(10000, 2 * run.get("poll_ms", 1000)))
    for index, (sampled, classes) in enumerate(ordered_samples):
        following = ordered_samples[index + 1][0] if index + 1 < len(ordered_samples) else end
        duration = max(0, following - sampled)
        for seat, data in per_seat.items():
            for family, status in classes[seat].items():
                data["duration"][family][status + "_ms"] += min(duration, maximum_hold)
                data["duration"][family]["unobserved_ms"] += max(0, duration - maximum_hold)
    leading = max(0, ordered_samples[0][0] - start) if ordered_samples else end - start
    for data in per_seat.values():
        for duration in data["duration"].values():
            duration["unobserved_ms"] += leading
        for import_key in list(data["imports"]):
            if len(profile_variants[import_key]) > 1:
                del data["imports"][import_key]
                data["profile_rejections"]["conflicting-metrics-same-original"] += 1
        for imported in data["imports"].values():
            stats = imported["stats"]
            for name in ("vpip", "pfr", "three_bet", "c_bet"):
                metric = stats["metrics"].get(name)
                percent = metric.get("percent") if isinstance(metric, dict) else None
                status = metric.get("status", "unknown") if isinstance(metric, dict) else "missing"
                if percent is not None and (type(percent) not in (int, float) or not math.isfinite(percent) or not 0 <= percent <= 100):
                    status = "invalid-percent"
                data["metric_statuses"][(name, str(status))] += 1

    def timing(values):
        values = list(values)
        distinct_sources = {capture_key(item["capture"]): item for item in values}
        return {"attempted_source_capture": interval_report(list(distinct_sources.values()), "captured_at_ms", start, end, True),
                "attempted_source_wall": interval_report(list(distinct_sources.values()), "captured_at_unix_ms", start, end),
                **{label: interval_report([item for item in values if type(item.get(clock)) is int
                    and start <= item[clock] <= end], clock, start, end) for label, clock in
                    (("requested", "requested_at_unix_ms"), ("attempt_starts", "attempt_started_at_unix_ms"),
                     ("completions", "completed_at_unix_ms"))}}

    seats = {}
    for seat, data in per_seat.items():
        seats[str(seat)] = {"context": timing(data["attempts"].values()),
            "native_context_attempts": timing(native_contexts.values()),
            "occupancy": {"accepted_source": interval_report(list(data["occupancy"].values()), "captured_at_unix_ms", start, end),
                          "samples": dict(data["occupancy_samples"])},
            "identity": {"accepted_source": interval_report(list(data["identity"].values()), "captured_at_unix_ms", start, end),
                         "samples": dict(data["identity_samples"])},
            "profile": {"imports": interval_report(list(data["imports"].values()), "captured_at_unix_ms", start, end),
                "first_api_visibility": interval_report(list(data["imports"].values()), "sampled_at_unix_ms", start, end),
                "import_events": list(data["imports"].values()), "rejected_samples": dict(data["profile_rejections"]),
                "unknown_scope_imports": sum(item["stats"].get("scope") is None for item in data["imports"].values()),
                "unknown_sample_size_imports": sum(item["stats"].get("sample_size") is None for item in data["imports"].values()),
                "metric_statuses": [{"metric": key[0], "status": key[1], "count": count}
                                    for key, count in data["metric_statuses"].items()]},
            "poll_bounded_duration": {family: dict(duration) for family, duration in data["duration"].items()}}
        seats[str(seat)]["poll_status_counts"] = {family: dict(collections.Counter(classes[seat][family]
            for _, classes in sample_classes)) for family in ("occupancy", "identity", "profile")}
    event_counts = collections.Counter(item.get("kind") for item in events.values() if not item["conflicting_id"])
    change_counts = collections.Counter()
    for item in events.values():
        changes = item.get("changes")
        if not item["conflicting_id"] and isinstance(changes, list):
            for change in changes:
                if not isinstance(change, dict) or not isinstance(change.get("kind"), str):
                    continue
                if change.get("capture") is not None:
                    try:
                        original(change["capture"], item["capture"], item["api_offset"])
                        if not start <= change["capture"]["captured_at_unix_ms"] <= end:
                            counters["event_changes_original_outside_window"] += 1
                            continue
                    except ValueError as exc:
                        rejected["event-change-" + str(exc)] += 1
                        item["invalid_change_refs"] = item.get("invalid_change_refs", 0) + 1
                        continue
                change_counts[change["kind"]] += 1
    evidence_counts = collections.Counter()
    for item in events.values():
        evidence = item.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        complete = item.get("evidence_complete", evidence.get("complete"))
        refs = item.get("evidence_id") or item.get("refs") or item.get("references") or evidence.get("refs") or evidence.get("references")
        label = "INCOMPLETE" if complete is False or item["conflicting_id"] or item.get("invalid_change_refs") else (
            "COMPLETE_REPORTED_NOT_CONTENT_AUDITED" if complete is True and refs else "UNKNOWN")
        evidence_counts[label] += 1
        item["measurement_evidence_status"] = label
        if complete is True and not refs:
            rejected["event-complete-without-reference"] += 1
    ui = analyze_ui_receipts(ui_receipts, references, run, ui_info)
    counter_changes, last_counters = [], {}
    for item in producer_states:
        for name in ("count", "bytes", "log_bytes", "dropped", "log_dropped", "dropped_frames",
                     "queue_drops", "events_dropped", "closure_count"):
            value = item["status"].get(name)
            if type(value) is not int or value < 0:
                continue
            key = (item["producer"], name)
            if key in last_counters and value < last_counters[key]:
                counter_changes.append({"producer": key[0], "counter": name, "from": last_counters[key],
                    "to": value, "api_offset": item["api_offset"], "sampled_at_unix_ms": item["sampled_at_unix_ms"]})
            last_counters[key] = value
    return {"source_exact": bool(contexts or native_contexts), "human_verified": False, "native_attempts_separate": True,
        "coverage": "OBSERVED" if contexts else "NOT OBSERVED", "test_result": "UNKNOWN",
        "clock_origins": {"captured_at_ms": "producer capture monotonic; not browser or collector monotonic",
            "captured_at_unix_ms": "original capture UTC", "work_clocks": "explicit producer UTC only",
            "sampled_at_unix_ms": "collector UTC; first API visibility is poll-bounded"},
        "contexts": timing(contexts.values()), "native_context_attempts": timing(native_contexts.values()),
        "native_context_events": list(native_contexts.values()), "native_context_input": attempt_info,
        "seats": seats, "role": {"samples": dict(roles),
            "accepted_source": interval_report(list(role_readings.values()), "captured_at_unix_ms", start, end),
            "events": list(role_readings.values())}, "sample_counts": dict(counters), "rejected_records": dict(rejected),
        "events": list(events.values()), "event_kind_counts": dict(event_counts),
        "event_change_kind_counts": dict(change_counts), "native_profile_status_counts": dict(native_profiles),
        "case_coverage": {kind: {"observed_changes": change_counts[kind],
            "coverage": "OBSERVED" if change_counts[kind] else "NOT OBSERVED", "test_result": "UNKNOWN"}
            for kind in ("source_boundary", "geometry_change", "capture_gap", "table_context_confirmed",
                "table_context_change", "occupant_confirmed", "occupant_replaced", "seat_empty", "role_change",
                "profile_import", "profile_rejected", "profile_closed")},
        "producer_evidence": {"latest_collected": {name: next((item for item in reversed(producer_states)
            if item["producer"] == name), None) for name in ("event_evidence", "context_diagnostics")},
            "counter_regressions": counter_changes,
            "incomplete_reported": any(item["status"].get("complete") is False
                or item["status"].get("log_complete") is False for item in producer_states)},
        "event_evidence": {"statuses": dict(evidence_counts), "latest_collected": evidence_states[-1] if evidence_states else None,
            "incomplete_reported": any(item["evidence"].get("complete") is False for item in evidence_states),
            "content_hash_audit": "UNKNOWN; references retained, image bytes not re-read"}, "ui": ui,
        "limitations": ["API context sightings are a deduplicated lower bound, not complete native attempt telemetry.",
            "Missing explicit request/start/completion clocks are not inferred from processing time or poll time.",
            "Native context attempts identify whole-frame requests, not successful completion of every physical-seat crop.",
            "Retained profile values count once at their original capture; closure/polling never renews them.",
            "Poll durations hold a sample for at most twice the poll interval; larger gaps are unobserved.",
            "Not observed cases and unknown evidence are not successful recognition or deadline tests.",
            "Event completeness is producer-reported; exact PNG/crop content audits remain separate."]}


def analyze_ui_receipts(receipts, references, run, info=None):
    start, end = run["started_at_unix_ms"], run["ended_at_unix_ms"]
    rejected, counts, fields = collections.Counter(), collections.Counter(), collections.defaultdict(dict)
    seen, unchanged, accepted = set(), {}, []
    for row in receipts[:EVENT_LIMIT]:
        try:
            key = capture_key(row.get("capture"))
            field, seat, published = row.get("field"), row.get("seat"), row.get("published_at_unix_ms")
            if (not isinstance(field, str) or not 0 < len(field) <= 256 or type(published) is not int
                    or seat is not None and (type(seat) is not int or not 1 <= seat <= 6)):
                raise ValueError("ui-field-or-publication-clock")
            if not start <= row["capture"]["captured_at_unix_ms"] <= end:
                counts["original_outside_window"] += 1
                continue
            if key not in references:
                raise ValueError("ui-original-not-in-collected-window")
            if not start <= published <= end:
                counts["publication_outside_window"] += 1
                continue
            if published < row["capture"]["captured_at_unix_ms"]:
                raise ValueError("ui-publication-before-capture")
            signature = (field, seat, key, dump(row.get("value")), dump(row.get("status")))
            identity = (*signature, published)
            if identity in seen:
                counts["duplicate_export_records"] += 1
                continue
            seen.add(identity)
            if signature in unchanged:
                counts["unchanged_original_republished"] += 1
                continue
            unchanged[signature] = published
            event = {**row, "api_original_reference": references[key],
                "source_to_dom_publication_ms": published - row["capture"]["captured_at_unix_ms"],
                "captured_at_unix_ms": row["capture"]["captured_at_unix_ms"]}
            accepted.append(event)
            fields[(field, seat)].setdefault(key, event)
        except (ValueError, TypeError) as exc:
            rejected[str(exc)] += 1
    counts["accepted_publications"] = len(accepted)
    return {"coverage": "OBSERVED" if accepted else "NOT OBSERVED", "test_result": "UNKNOWN", "input": info,
        "counts": dict(counts), "rejected_records": dict(rejected), "publications": accepted,
        "fields": [{"field": field, "seat": seat,
            "distinct_original_captures": interval_report(list(items.values()), "captured_at_unix_ms", start, end),
            "dom_publication": interval_report(list(items.values()), "published_at_unix_ms", start, end),
            "source_to_dom_publication_max_ms": max(item["source_to_dom_publication_ms"] for item in items.values())}
            for (field, seat), items in fields.items()],
        "limitations": ["Publication UTC is frontend DOM-update time, not paint time or API admission time.",
            "Browser/native monotonic clocks are never subtracted or joined by proximity.",
            "A later UI export cannot supply an original missing from raw-window API receipts.",
            "Repeated original receipts and expiry/status changes do not create fresh source observations."]}


def analyze_native_timing(api, run, receipts=(), info=None):
    """Bounded native numeric first-DOM stages; telemetry never qualifies a reading."""
    start, end = run["started_at_unix_ms"], run["ended_at_unix_ms"]
    counts, rejected, unknown = collections.Counter(), collections.Counter(), collections.Counter()
    references, first, observed, samples = collections.defaultdict(set), set(), set(), []
    ticket_bindings = collections.defaultdict(set)
    expected = {"service_instance_id": run.get("service_instance"), "session_id": run.get("api_session"),
                "capture_session_id": run.get("session"), "source_id": run.get("source_id"), "epoch": run.get("source_epoch")}
    counts.update(api_rows_over_limit=max(0, len(api) - ROW_LIMIT), ui_rows_over_limit=max(0, len(receipts) - EVENT_LIMIT))

    def clock(value):
        return type(value) is int and 0 <= value <= 2**53 - 1

    def bind_capture(capture, key, generation):
        if "generation" in capture and (not clock(capture["generation"]) or capture["generation"] != generation):
            raise ValueError("capture-generation-identity")
        ticket = (*key[:5], generation, capture["captured_at_ms"], capture["captured_at_unix_ms"])
        ticket_bindings[ticket].add((key, capture.get("native_source_id")))

    def timing_key(timing, capture, generation, upper):
        if (not isinstance(timing, dict) or any(not clock(timing.get(key)) for key in NATIVE_TIMING_KEYS)
                or not clock(generation) or timing["schema_version"] != 1 or timing["generation"] != generation
                or timing["epoch"] != capture["epoch"]
                or any(timing[key] != capture[key] for key in ("captured_at_ms", "captured_at_unix_ms"))
                or "generation" in capture and not clock(capture["generation"])
                or capture.get("generation", generation) != generation):
            raise ValueError("native-timing-ticket-or-clock")
        times = [timing[key] for key in ("captured_at_unix_ms", "emitted_at_unix_ms", "ingested_at_unix_ms", "api_snapshot_at_unix_ms")]
        if times != sorted(times) or times[-1] > upper:
            raise ValueError("native-timing-clock-order")
        return tuple(timing[key] for key in NATIVE_TIMING_KEYS[:-1])

    for _, row in api[:ROW_LIMIT]:
        sampled, state = row.get("sampled_at_unix_ms"), row.get("state")
        if not clock(sampled) or not start <= sampled <= end or not isinstance(state, dict):
            continue
        try:
            scope = sample_scope(state)
            if not clock(scope.get("epoch")) or any(scope.get(key) != value for key, value in expected.items() if value is not None):
                raise ValueError("api-source-scope")
            partial = state.get("partial_observation")
            if not isinstance(partial, dict):
                continue
            capture = partial.get("capture")
            key = capture_key(capture)
            if (capture.get("parent_capture") is not None or any(capture[name] != scope.get(name) for name in CAPTURE_KEYS[:5])
                    or any(capture[name] != state.get("capture", {}).get(name) for name in ("width", "height"))
                    or not all(clock(capture[name]) for name in ("epoch", "sequence", "captured_at_ms", "captured_at_unix_ms"))
                    or not clock(partial.get("generation")) or not clock(partial.get("epoch")) or partial["epoch"] != capture["epoch"]
                    or not clock(partial.get("captured_at_unix_ms"))
                    or partial.get("captured_at_unix_ms") != capture["captured_at_unix_ms"]
                    or not clock(partial.get("captured_at_ms", capture["captured_at_ms"]))
                    or partial.get("captured_at_ms", capture["captured_at_ms"]) != capture["captured_at_ms"]
                    or not clock(partial.get("expires_at_unix_ms")) or sampled >= partial["expires_at_unix_ms"]):
                raise ValueError("api-partial-source-or-clock")
            for name in expected:
                if expected[name] is None:
                    expected[name] = scope.get(name)
            bind_capture(capture, key, partial["generation"])
            timing, transport = state.get("native_timing"), None
            if timing is not None:
                try:
                    transport = timing_key(timing, capture, partial["generation"], sampled)
                except (ValueError, TypeError, KeyError) as exc:
                    rejected["api:" + str(exc)] += 1
            fields = [("pot_size", partial.get("pot_size"))]
            fields += [(f"seats.{seat['seat']}.displayed_stack", seat.get("displayed_stack"))
                       for seat in partial.get("seats", [])[:6] if isinstance(seat, dict) and type(seat.get("seat")) is int and 1 <= seat["seat"] <= 6]
            for field, amount in fields:
                field_capture = partial.get("field_captures", {}).get(field, capture)
                if not clock(amount) or partial.get("field_statuses", {}).get(field, {}).get("status") != "accepted":
                    continue
                field_key = capture_key(field_capture)
                if (field_capture.get("parent_capture") is not None
                        or any(field_capture[name] != capture[name] for name in (*CAPTURE_KEYS[:5], "width", "height"))
                        or not all(clock(field_capture[name]) for name in ("epoch", "sequence", "captured_at_ms", "captured_at_unix_ms"))
                        or "generation" in field_capture and not clock(field_capture["generation"])
                        or field_capture["captured_at_unix_ms"] > capture["captured_at_unix_ms"]
                        or field_capture["captured_at_ms"] > capture["captured_at_ms"]):
                    continue
                exact = field_key == key and all(field_capture.get(name) == capture.get(name) for name in ("generation", "native_source_id"))
                if "generation" in field_capture:
                    bind_capture(field_capture, field_key, field_capture["generation"])
                references[(field_key, field)].add((amount, transport if exact else None,
                    field_capture.get("generation"), field_capture.get("native_source_id"), partial["expires_at_unix_ms"]))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            rejected["api:" + str(exc)] += 1

    # Scan every bounded API binding before choosing receipts: an ambiguous replay has no first winner.
    ambiguous = [bindings for bindings in ticket_bindings.values() if len(bindings) > 1]
    ambiguous_bindings = {binding for bindings in ambiguous for binding in bindings}
    ambiguous_captures = {key for key, _ in ambiguous_bindings}
    counts.update(ambiguous_native_tickets=len(ambiguous), ambiguous_original_captures=len(ambiguous_bindings))
    if ambiguous:
        rejected["api:ambiguous-ticket-binding"] += len(ambiguous)
    # Export order is not evidence of first publication. Missing first timing must never be retrofilled.
    ordered = sorted(receipts[:EVENT_LIMIT], key=lambda row: row.get("published_at_unix_ms")
                     if isinstance(row, dict) and clock(row.get("published_at_unix_ms")) else -1)
    for row in ordered:
        try:
            if not isinstance(row, dict):
                raise ValueError("ui-record")
            field = row.get("field")
            if not isinstance(field, str) or not re.fullmatch(r"pot_size|seats\.[1-6]\.displayed_stack", field):
                counts["excluded_non_numeric"] += 1
                continue
            if row.get("status") != "current":
                counts["excluded_non_current"] += 1
                continue
            seat = None if field == "pot_size" else int(field.split(".")[1])
            if row.get("seat") != seat or seat is not None and type(row.get("seat")) is not int:
                raise ValueError("ui-field-seat")
            capture, published = row.get("capture"), row.get("published_at_unix_ms")
            key = capture_key(capture)
            if "generation" in capture and not clock(capture["generation"]):
                raise ValueError("ui-capture-generation-identity")
            if not clock(published) or not all(clock(capture[name]) for name in ("epoch", "sequence", "captured_at_ms", "captured_at_unix_ms")):
                raise ValueError("ui-publication-clock")
            if not start <= capture["captured_at_unix_ms"] <= end or not start <= published <= end:
                counts["outside_window"] += 1
                continue
            if published < capture["captured_at_unix_ms"]:
                raise ValueError("ui-publication-before-capture")
            identity = (key, field)
            if identity in first:
                counts["duplicate_publications"] += 1
                continue
            first.add(identity)
            if key in ambiguous_captures:
                raise ValueError("ui-ambiguous-ticket-binding")
            matches = references.get(identity)
            if not matches:
                raise ValueError("ui-original-field-not-collected")
            literal = row.get("value")
            match = re.fullmatch(r"(\d+|\d{1,3}(?:,\d{3})+)(?:\.(\d{1,2}))?(?: chips)?", literal) if isinstance(literal, str) and len(literal) <= 64 else None
            if not match:
                raise ValueError("ui-numeric-literal")
            amount = int(match[1].replace(",", "")) * 100 + int((match[2] or "").ljust(2, "0"))
            matches = {item for item in matches if item[2:4] == (capture.get("generation"), capture.get("native_source_id"))}
            if not matches or {item[0] for item in matches} != {amount}:
                raise ValueError("ui-native-value-or-source-mismatch")
            if published >= min(item[4] for item in matches):
                raise ValueError("ui-publication-outside-collected-lease")
            observed.add(identity)
            stages_for_field = [None] * 4 + [published - capture["captured_at_unix_ms"]]
            samples.append((field, stages_for_field))
            timing = row.get("native_timing")
            if timing is None:
                unknown["missing-native-timing"] += 1
                continue
            transport = timing_key(timing, capture, timing.get("generation") if isinstance(timing, dict) else None, published)
            transports = {item[1] for item in matches if item[1] is not None}
            if not transports:
                unknown["api-native-timing-unavailable"] += 1
                continue
            if transports != {transport}:
                raise ValueError("ui-native-transport-mismatch")
            times = [timing[name] for name in ("captured_at_unix_ms", "emitted_at_unix_ms", "ingested_at_unix_ms", "api_snapshot_at_unix_ms")] + [published]
            stages_for_field[:4] = [b - a for a, b in zip(times, times[1:])]
        except (ValueError, TypeError, KeyError) as exc:
            rejected[str(exc)] += 1

    def stages(rows):
        result = {}
        for index, name in enumerate(("capture_to_emit", "emit_to_ingest", "ingest_to_api", "api_to_dom", "capture_to_dom")):
            values = sorted(row[1][index] for row in rows if row[1][index] is not None)
            result[name] = {"count": len(values), "min": min(values, default=None), "max": max(values, default=None),
                            "p95": values[(95 * len(values) + 99) // 100 - 1] if values else None}
        return result

    summary = stages(samples)
    counts.update(collected_native_fields=len(references), collected_fields_without_valid_dom_receipt=len(references.keys() - observed))
    return {"schema_version": 1, "sample_count": len(samples),
        "complete_stage_sample_count": summary["api_to_dom"]["count"], "stages_ms": summary,
        "quantile_method": "nearest-rank ceil(0.95*n)", "complete_coverage": False, "input": info,
        "observed_p95_below_3000_ms": summary["capture_to_dom"]["p95"] < 3000 if samples else None,
        "counts": dict(counts), "rejected_records": dict(rejected), "unknown_records": dict(unknown),
        "fields": [{"field": field, "stages_ms": stages([row for row in samples if row[0] == field])}
                   for field in sorted({row[0] for row in samples})],
        "limitations": ["Bounded collected current native pot/stack first publications only; incomplete coverage is not a live acceptance verdict.",
            "API-to-DOM is API snapshot completion to first DOM publication, including serialization/network/parse; not wire-send or paint time.",
            "Independent API polls validate source/field and capture/emit/ingest ticket clocks, not equality of per-request API completion stamps.",
            "Valid source/field first publications retain total latency even when component telemetry is missing, contradictory or belongs to a newer bundle.",
            "CPU provisional, last-read and repeated polls/publications are not native latency samples; missing/contradictory component clocks remain unknown or rejected.",
            "Browser and producer monotonic clocks are never subtracted; UTC ordering cannot prove clock synchronization or numeric accuracy."]}


def analyze(out, report_name="timing.json", run=None, context=None, ui_receipts=None):
    run = run if run is not None else json.loads((out / "run.json").read_bytes())
    start, end = run["started_at_unix_ms"], run["ended_at_unix_ms"]
    session = private_path(run["session_dir"])
    inputs = []
    boundaries = run.get("input_sizes_at_end", {})

    def input_rows(path, byte_limit=INPUT_LIMIT):
        return read_rows(path, inputs, byte_limit, boundaries.get(str(path.relative_to(ROOT))))

    api_rows = input_rows(out / "api.jsonl")
    api = [(offset, row) for offset, row in api_rows
            if start <= row.get("sampled_at_unix_ms", 0) <= end]
    namespaces, namespace_receipts = VisualNamespaces(), {}
    for offset, row in api[:ROW_LIMIT]:
        state = row.get("state")
        if isinstance(state, dict):
            if namespaces.present:
                namespace_receipts[offset] = None
            if boundary_reason(sample_scope(state), run.get("scope", {}), run.get("session")):
                namespaces.issues["sample-run-scope"] += 1
                namespaces.invalidate_active()
                continue
            valid_registry = namespaces.observe(state)
            if namespaces.present:
                namespace_receipts[offset] = None
            audit = row.get("projection")
            if namespaces.present and isinstance(audit, dict) and isinstance(audit.get("issues"), list) and any(
                    isinstance(issue, str) and "namespace" in issue for issue in audit["issues"][:64]):
                namespaces.issues["projection-namespace-loss"] += 1
                valid_registry = False
                namespaces.invalidate_active()
            path = VisualNamespaces.context_path(state)
            if valid_registry and isinstance(path, str) and any(Path(path) == Path(value) for value in namespaces.active_paths):
                namespace_receipts[offset] = Path(path).parent.name
    collected_registry = run.get("visual_namespaces")
    if isinstance(collected_registry, dict) and isinstance(collected_registry.get("issues"), dict):
        for name, count in list(collected_registry["issues"].items())[:64]:
            if isinstance(name, str) and len(name) <= 128 and VisualNamespaces.integer(count):
                namespaces.issues[name] = max(namespaces.issues[name], count)
    native = input_rows(session / "stdout.jsonl")
    ledger = input_rows(session / "ledger.jsonl")
    answers = input_rows(private_path(run["answers_log"]))
    perceptions = input_rows(session / "perception.jsonl")
    compact = input_rows(session / "readouts.jsonl", READOUT_LIMIT)
    compact_info = inputs[-1]
    manifest = input_rows(private_path(run["manifest"]))
    visual_rows = [] if namespaces.present else input_rows(private_path(run["manifest"]).with_name("visual.jsonl"))
    ui_rows, ui_info = load_ui_receipts(ui_receipts, inputs)
    context_log = run.get("context_log") or next((row["state"].get("context_diagnostics", {}).get("log_path")
        for _, row in api if isinstance(row.get("state"), dict)
        and isinstance(row["state"].get("context_diagnostics"), dict)
        and row["state"]["context_diagnostics"].get("log_path")), None)
    context_attempts, context_input = [], {"missing": True, "complete": False}
    if namespaces.present:
        context_log = None
        context_input = {"complete": False, "diagnostic_namespace_logs": True,
                         "reason": "namespace candidates are separate from canonical context counts"}
    if context_log:
        try:
            log_path = private_path(context_log, PRIVATE / "laya/events")
        except (ValueError, TypeError) as exc:
            log_path = None
            context_input = {"path": context_log, "complete": False, "rejection": str(exc)}
    else:
        log_path = None
    if log_path is not None:
        # A later growing file cannot supply records beyond the collected producer counter.
        status_rows = [row["state"]["context_diagnostics"] for _, row in api
            if isinstance(row.get("state"), dict) and isinstance(row["state"].get("context_diagnostics"), dict)
            and row["state"]["context_diagnostics"].get("log_path") == context_log]
        boundary = boundaries.get(str(log_path.relative_to(ROOT)))
        if boundary is None and status_rows:
            boundary = status_rows[-1].get("bytes", status_rows[-1].get("log_bytes"))
        if type(boundary) is int and boundary >= 0:
            context_attempts = read_rows(log_path, inputs, min(INPUT_LIMIT, 8 * 1024 * 1024), boundary)
            context_input = {**inputs[-1], "producer_status_at_last_sample": status_rows[-1] if status_rows else None,
                "complete": bool(status_rows and status_rows[-1].get("log_complete") is True
                    and not status_rows[-1].get("dropped", status_rows[-1].get("log_dropped", 0))
                    and not any(inputs[-1].get(key) for key in ("capped", "partial_tail", "invalid_rows", "missing", "shortened_since_boundary")))}
        else:
            context_input = {"path": context_log, "complete": False,
                "missing_boundary": boundary is None, "invalid_boundary": boundary is not None}
    receipt_path = session / "approval.json"
    receipt = json.loads(receipt_path.read_bytes()) if receipt_path.is_file() and receipt_path.stat().st_size <= 16384 else {}
    frames = collections.defaultdict(list)
    frames_by_utc = collections.defaultdict(list)
    for offset, row in manifest:
        if row.get("event") == "frame":
            frames[(row.get("source_utc_unix_ms"), row.get("captured_at_monotonic_ms"))].append(
                {**row, "manifest_offset": offset})
            frames_by_utc[row.get("source_utc_unix_ms")].append({**row, "manifest_offset": offset})
    answer_index = collections.defaultdict(list)
    answer_events = {seat: [] for seat in range(1, 7)}
    answer_pass_counts = collections.Counter()
    for offset, row in answers:
        try:
            stamp = iso_us(row["utc"]) // 1000
        except (ValueError, KeyError, TypeError):
            continue
        for signature in {pass_signature(row, logged=True, include_truncated=flag) for flag in (True, False)}:
            answer_index[signature].append(
                {"answers_offset": offset, "completion_utc": row["utc"], "completion_at_unix_ms": stamp,
                 "timing_ms": row.get("timing_ms"), "timing_shared_batch": row.get("timing_shared_batch")})
        if start <= stamp <= end:
            answer_pass_counts[row.get("pass")] += 1
            match = SEAT_PASS.fullmatch(row.get("pass", ""))
            if match and match[3] == "stack":
                answer_events[int(match[2])].append({"answers_offset": offset, "completion_utc": row["utc"],
                                                   "completion_at_unix_ms": stamp, "pass": row["pass"],
                                                   "timing_ms": row.get("timing_ms"), "capture_identity": None,
                                                   "score_only_not_admission": True})
    expected_target = next((row["state"].get("capture", {}).get("source_id") for _, row in api if "state" in row), None)
    diagnostic_rows, readout_audit = merge_readouts(native, compact, perceptions, expected_target,
        run.get("service_instance") or receipt.get("service_instance_id"), receipt.get("source"))
    readout_audit["compact_file"] = {**compact_info, "configured_producer_limit_bytes": READOUT_LIMIT,
        "at_configured_limit": compact_info.get("size_at_scan", 0) >= READOUT_LIMIT,
        "producer_completeness": "unknown; file size below cap is not proof no records were dropped"}
    compact_selected = readout_audit["chosen_origin_counts"].get("compact", 0)
    readout_audit["compact_selection_available"] = compact_selected > 0
    readout_audit["fallback_explicit"] = compact_selected == 0
    if not compact_info.get("missing") and compact_selected == 0:
        readout_audit["preferred_source"] = ("compact-unusable-native/perception-fallback"
            if readout_audit["valid_unique_readouts"] else "compact-unusable-no-valid-readouts")
    producer_statuses = [{"api_offset": offset, "sampled_at_unix_ms": row["sampled_at_unix_ms"],
                          "status": row["state"]["readout_evidence"]} for offset, row in api_rows
                         if row.get("state", {}).get("capture_session", {}).get("session_id") == run["session"]
                         and isinstance(row["state"].get("readout_evidence"), dict)]
    readout_audit["producer_status"] = {"observed_samples": len(producer_statuses),
        "incomplete_reported": any(item["status"].get("complete") is False for item in producer_statuses),
        "disabled_reported": any(item["status"].get("enabled") is False for item in producer_statuses),
        "latest_collected": producer_statuses[-1] if producer_statuses else None,
        "event_limit": 4000, "byte_limit": READOUT_LIMIT,
        "note": "Counters are original collected API values. No status is fetched after the collection boundary; absent metadata remains unknown."}
    attempts = {seat: [] for seat in range(1, 7)}
    admitted = {seat: [] for seat in range(1, 7)}
    dashboard = {seat: [] for seat in range(1, 7)}
    visible = {seat: [] for seat in range(1, 7)}
    dedup = set()
    counts, reasons, fields = collections.Counter(), collections.Counter(), collections.Counter()
    for _, row in native:
        emitted = row.get("emitted_at_unix_ms", row.get("updated_at_unix_ms"))
        if type(emitted) is int and start <= emitted <= end:
            counts[row.get("event")] += 1
            reasons[row.get("reason", row.get("admission"))] += 1
    for offset, row, origin in diagnostic_rows:
        emitted = row.get("emitted_at_unix_ms", row.get("updated_at_unix_ms"))
        if row.get("event") != "perception_diagnostics":
            continue
        ticket = row.get("observation", {})
        captured, mono = ticket.get("captured_at_unix_ms"), ticket.get("captured_at_ms")
        if (type(captured) is not int or type(mono) is not int or type(emitted) is not int
                or not (start <= emitted <= end or start <= captured <= end)):
            continue
        for item in row.get("passes", []):
            match = SEAT_PASS.fullmatch(item.get("pass", ""))
            if match is None:
                continue
            seat = int(match[2])
            family = {"stack": "displayed_stack", "wager": "visible_wager", "scene": "scene"}[match[3]]
            confirmed = (item.get("segments") is not None or item.get("total_ms") is not None
                         or any(q.get("score") is not None for q in item.get("questions", [])))
            if not confirmed:
                continue  # Current diagnostics also list unscheduled/unsupported passes.
            key = (seat, item["pass"], ticket.get("epoch"), ticket.get("generation"), mono, captured)
            if key in dedup:
                continue
            dedup.add(key)
            timestamp_matches = frames.get((captured, mono), [])
            frame_matches = [frame for frame in timestamp_matches
                             if (frame.get("width"), frame.get("height")) == (row.get("frame_width"), row.get("frame_height"))]
            retained_truncation = all("truncated" in q for q in item.get("questions", []) if q.get("answer") is not None)
            answer_matches = [entry for entry in answer_index[pass_signature(item, include_truncated=retained_truncation)]
                              if captured <= entry["completion_at_unix_ms"] <= emitted]
            field_rows = [field for field in row.get("fields", []) if field.get("seat") == seat
                          and (field.get("field") == family or family == "scene" and field.get("field")
                               in ("occupied", "status", "badge", "dealer", "small_blind", "big_blind", "acting"))]
            for field in field_rows:
                fields[(seat, field.get("field"), field.get("admission_status"), field.get("admission_reason"))] += 1
            event = {"pass": item["pass"], "family": family, "native_offset": offset if origin == "native" else None,
                     "perception_offset": offset if origin == "perception" else None, "evidence_origin": origin,
                     "compact_offset": offset if origin == "compact" else None,
                     "readout_evidence": row.get("measurement_evidence", []),
                     "answer_correlation_retained_truncated": retained_truncation,
                     "capture_ticket": ticket, "captured_at_unix_ms": captured, "captured_at_ms": mono,
                     "emitted_at_unix_ms": emitted, "source_age_ms": row.get("source_age_ms"),
                     "expires_at_unix_ms": row.get("expires_at_unix_ms"), "valid_for_ms": row.get("valid_for_ms"),
                     "source_current": row.get("source_current"), "admission": row.get("admission"),
                     "field_admission": field_rows, "manifest_exact_match_count": len(frame_matches),
                     "manifest_timestamp_match_count": len(timestamp_matches),
                     "manifest_match_scope": "exact UTC, monotonic clock and dimensions; SHA retained from original manifest",
                     "manifest_frame": frame_matches[0] if len(frame_matches) == 1 else None,
                     "answer_exact_signature_candidates": answer_matches,
                     "answer_correlation": "unique-shared-signature-and-time-bracket" if len(answer_matches) == 1
                         else "ambiguous" if answer_matches else "unmatched"}
            attempts[seat].append(event)
            if (row.get("source_current") is True and row.get("admission") == "source_current"
                    and any(f.get("admission_status") == "accepted" for f in field_rows)):
                admitted[seat].append(event)
    for offset, row in ledger:
        reading = row.get("partial_observation") or row.get("observation")
        if not isinstance(reading, dict):
            continue
        try:
            stamp = iso_us(row["recorded_utc"])
        except (ValueError, KeyError, TypeError):
            continue
        if not start * 1000 <= stamp <= end * 1000:
            continue
        for item in reading.get("seats", []):
            seat = item.get("seat")
            if seat in dashboard and item.get("displayed_stack") is not None:
                matched = frames_by_utc.get(reading.get("captured_at_unix_ms"), [])
                dashboard[seat].append({"ledger_offset": offset, "recorded_utc": row["recorded_utc"],
                                        "recorded_at_unix_us": stamp, "displayed_stack": item["displayed_stack"],
                                        "manifest_exact_utc_match_count": len(matched),
                                        "manifest_frame": matched[0] if len(matched) == 1 else None,
                                        **{key: reading.get(key) for key in ("generation", "epoch", "captured_at_unix_ms", "expires_at_unix_ms")}})
    api_seen = set()
    states, sessions, instances = collections.Counter(), set(), set()
    for offset, row in api:
        state = row.get("state")
        if not isinstance(state, dict):
            continue
        sessions.add(state.get("capture_session", {}).get("session_id"))
        instances.add(state.get("server", {}).get("instance_id"))
        states[(state.get("capture_session", {}).get("status"), state.get("capture_session", {}).get("activity_state"))] += 1
        if state.get("capture_session", {}).get("session_id") != run["session"]:
            continue
        reading = state.get("partial_observation") or state.get("observation")
        if not isinstance(reading, dict):
            continue
        for item in reading.get("seats", []):
            seat = item.get("seat")
            key = (seat, reading.get("epoch"), reading.get("generation"), reading.get("captured_at_unix_ms"))
            statuses = reading.get("field_statuses", state.get("field_statuses", {}))
            if (seat not in visible or item.get("displayed_stack") is None or key in api_seen
                    or statuses.get(f"seats.{seat}.displayed_stack", {}).get("status") != "accepted"):
                continue
            api_seen.add(key)
            visible[seat].append({"api_offset": offset, "sampled_at_unix_ms": row["sampled_at_unix_ms"],
                                  "epoch": reading.get("epoch"), "generation": reading.get("generation"),
                                  "captured_at_unix_ms": reading.get("captured_at_unix_ms"),
                                  "expires_at_unix_ms": reading.get("expires_at_unix_ms"),
                                  "displayed_stack": item["displayed_stack"]})
    seats = {}
    for seat in range(1, 7):
        selected = [event for event in attempts[seat] if event["family"] == "displayed_stack"]
        accepted = [event for event in admitted[seat] if event["family"] == "displayed_stack"]
        captured_selected = [event for event in selected if start <= event["captured_at_unix_ms"] <= end]
        captured_accepted = [event for event in accepted if start <= event["captured_at_unix_ms"] <= end]
        seats[str(seat)] = {
            "answers_completion": series(answer_events[seat], "completion_at_unix_ms", start, end),
            "answers_completion_events": answer_events[seat],
            "attempted_source_capture": series(captured_selected, "captured_at_ms", start, end, True),
            "attempted_source_wall": series(captured_selected, "captured_at_unix_ms", start, end),
            "attempted_completion": series([event for event in selected if start <= event["emitted_at_unix_ms"] <= end], "emitted_at_unix_ms", start, end),
            "admitted_source_capture": series(captured_accepted, "captured_at_ms", start, end, True),
            "admitted_native_emission": series([event for event in accepted if start <= event["emitted_at_unix_ms"] <= end], "emitted_at_unix_ms", start, end),
            "dashboard_admission": series(dashboard[seat], "recorded_at_unix_us", start, end, scale=1000),
            "dashboard_admitted_source_wall": series([event for event in dashboard[seat]
                                                       if start <= event["captured_at_unix_ms"] <= end],
                                                      "captured_at_unix_ms", start, end),
            "dashboard_admitted_source_monotonic": series([
                {"captured_at_ms": event["manifest_frame"]["captured_at_monotonic_ms"]}
                for event in dashboard[seat] if event["manifest_frame"] is not None
                and start <= event["captured_at_unix_ms"] <= end], "captured_at_ms", start, end, True),
            "api_first_observed_admission": series(visible[seat], "sampled_at_unix_ms", start, end),
            "attempt_events": attempts[seat], "api_admitted_events": visible[seat],
            "dashboard_admitted_events": dashboard[seat]}
    saved = [row for _, row in manifest if start <= row.get("source_utc_unix_ms", 0) <= end]
    report = {"format": 1, "run": run, "inputs": inputs, "seats": seats,
              "reported_test_context": context,
              "readout_integrity": readout_audit,
              "table_context": analyze_context(api, run, ui_rows, ui_info, context_attempts, context_input, namespace_receipts),
              "native_numeric_timing": analyze_native_timing(api, run, ui_rows, ui_info),
              "diagnostic_namespaces": namespaces.analyze(api, run, inputs) if namespaces.present else None,
              "collection_integrity": {"projected_samples": sum(row.get("projected") is True for _, row in api),
                  "projection_incomplete_samples": sum(row.get("projection", {}).get("complete") is False for _, row in api),
                  "latest_projection": next((row["projection"] for _, row in reversed(api) if "projection" in row), None),
                  "collection_complete": run.get("collection_complete"), "no_later_state_fetched": True},
              "visual": analyze_visual(native, [(offset, row) for offset, row in api
                         if row.get("state", {}).get("capture_session", {}).get("session_id") == run["session"] or "error" in row],
                         visual_rows, frames, start, end),
              "analysis_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "answer_pass_counts": dict(answer_pass_counts),
              "p2_answer_calls": sum(count for name, count in answer_pass_counts.items() if isinstance(name, str) and name.startswith("p2_")),
              "receipt_configuration": {key: receipt.get(key) for key in ("version", "mode", "source_policy", "cpu_visual_board", "source", "service_instance_id")},
              "native_events_in_window": dict(counts), "native_reasons_in_window": {str(k): v for k, v in reasons.items()},
              "field_admission_counts": [{"seat": k[0], "field": k[1], "status": k[2], "reason": k[3], "count": v}
                                         for k, v in fields.items()],
              "api": {"rows": len(api), "sessions": sorted(str(x) for x in sessions),
                      "first_sampled_at_unix_ms": api[0][1]["sampled_at_unix_ms"] if api else None,
                      "last_sampled_at_unix_ms": api[-1][1]["sampled_at_unix_ms"] if api else None,
                      "service_instances": sorted(str(x) for x in instances),
                      "session_states": [{"status": k[0], "activity": k[1], "samples": v} for k, v in states.items()]},
              "recording": {"frames_in_measurement_window": len(saved),
                            "estimated_missed_samples": sum(row.get("estimated_missed_samples", 0) for row in saved),
                            "max_saved_gap_ms": max((row.get("previous_saved_gap_ms") or 0 for row in saved), default=None),
                            "timestamp_basis": sorted({row.get("timestamp_basis", "missing") for row in saved}),
                            "last_saved_source_utc_unix_ms": max((row.get("source_utc_unix_ms", 0) for _, row in manifest), default=None)},
              "accuracy": {"human_verified_ground_truth": False, "accuracy_rate": None,
                           "note": "Timing and native admission are not recognition accuracy or complete action history."},
              "limitations": ["Source capture means original caller capture_call_start, not a WGC driver timestamp.",
                              "Confirmed attempted passes require response diagnostics; failed unlogged requests cannot be recovered.",
                              "Compact readouts are preferred only after exact overlap validation; conflicts are excluded and reported.",
                              "Capture and emission windows are separate; observed late completions retain their original capture clocks.",
                              "AnswersLog has no capture ID. Unique shared signature within source/emission bracket is correlation, not identity proof.",
                              "API first visibility is poll-bounded, not exact native or dashboard admission time.",
                              "No intervals are manufactured from repeated API samples or from retained values.",
                              "Native admission may carry repeated values from the same source; only distinct source tickets count.",
                              "Censored measurement edges are separate from complete >10000ms intervals.",
                              "Input hashes cover the scanned prefixes only; a capped or partial tail is not complete evidence.",
                              "Answers completion UTC proves completed calls, not source capture IDs or field admission.",
                              "Later admission monotonic clocks require one exact manifest UTC match; absent matches remain unknown.",
                              "PNG hashes are original manifest references, not an all-image content audit."]}
    if Path(report_name).name != report_name or not report_name.endswith(".json"):
        raise ValueError("invalid-report-name")
    write_json(out / report_name, report)
    summarize(report)


def summarize(report):
    keys = ("count", "min_gap_ms", "median_gap_ms", "max_gap_ms", "gaps_gt_10000ms",
            "missed_10000ms_deadlines", "max_gap_including_edges_ms")
    provenance = {seat: {"attempts": len(data["attempt_events"]),
                         "exact_manifest_match": sum(event["manifest_exact_match_count"] == 1 for event in data["attempt_events"]),
                         "answer_correlations": dict(collections.Counter(event["answer_correlation"] for event in data["attempt_events"]))}
                  for seat, data in report["seats"].items()}
    visual = report.get("visual", {})
    visual_summary = {name: {k: value[k] for k in keys if k in value} if "count" in value else value
                      for name, value in visual.items()
                      if name in ("native_offered_frames", "confirmed_processed_frames", "api_first_presence", "api_presence",
                                  "processing_max_ms", "processing_median_ms", "action_processing_max_ms", "exact_native_frame_matches",
                                  "exact_manifest_matches", "board_candidates", "sighting_types", "rejected_records", "phases")
                      and isinstance(value, dict)}
    visual_summary.update({name: visual.get(name) for name in ("processing_max_ms", "processing_median_ms", "action_processing_max_ms",
                                                              "exact_native_frame_matches", "exact_manifest_matches")})
    visual_summary["board_artifact_metadata"] = visual.get("board_artifact_metadata", [])
    visual_summary["seats"] = {seat: {family: {"processed_attempts": {k: data["processed_attempts"][k] for k in keys if k in data["processed_attempts"]},
                                             "provisional_literal_results": {k: data["provisional_literal_results"][k] for k in keys if k in data["provisional_literal_results"]},
                                             "statuses": data["statuses"], "literal_types": data["literal_types"], "api_presence": data.get("api_presence", {})}
                                      for family, data in seat_data.items()} for seat, seat_data in visual.get("seats", {}).items()}
    visual_summary["phases"] = {label: {**{k: value for k, value in data.items() if k != "confirmed_processed"},
                                       "confirmed_processed": {k: data["confirmed_processed"][k] for k in keys if k in data["confirmed_processed"]}}
                                for label, data in visual.get("phases", {}).items()}
    print(dump({"duration_ms": report["run"]["elapsed_ms"], "api": report["api"],
                "answer_pass_counts": report.get("answer_pass_counts"), "p2_answer_calls": report.get("p2_answer_calls"),
                "receipt_configuration": report.get("receipt_configuration"),
                "reported_test_context": report.get("reported_test_context"),
                "readout_integrity": report.get("readout_integrity"),
                "stop_reason": report["run"]["stop_reason"], "recording": report["recording"],
                "visual": visual_summary,
                "native_numeric_timing": {key: report.get("native_numeric_timing", {}).get(key) for key in
                    ("schema_version", "sample_count", "complete_stage_sample_count", "stages_ms", "quantile_method",
                     "complete_coverage", "observed_p95_below_3000_ms", "counts", "rejected_records", "unknown_records",
                     "fields", "input", "limitations")},
                "diagnostic_namespaces": {key: (report.get("diagnostic_namespaces") or {}).get(key) for key in
                    ("schema_version", "counts", "issues", "limits", "observed_prefixes_complete", "complete_coverage", "semantics", "limitations")},
                "context": {key: report.get("table_context", {}).get(key) for key in
                    ("coverage", "test_result", "contexts", "native_context_attempts", "sample_counts",
                     "rejected_records", "event_kind_counts", "event_evidence")},
                "collection_integrity": report.get("collection_integrity"),
                "provenance": provenance,
                "input_integrity": [{k: item.get(k) for k in ("path", "rows", "bytes", "invalid_rows", "capped", "partial_tail", "missing")}
                                    for item in report["inputs"]],
                "seats": {seat: {name: {k: value[k] for k in keys if k in value}
                                 for name, value in data.items() if not name.endswith("events")}
                          for seat, data in report["seats"].items()}}), flush=True)


def collect(args, out):
    if not 1 <= args.seconds <= 600 or not 500 <= args.poll_ms <= 5000:
        raise ValueError("duration-1-to-600s-poll-500-to-5000ms")
    if not re.fullmatch(r"[0-9a-f]{32}", args.session):
        raise ValueError("invalid-session")
    session = PRIVATE / "laya/manual-capture" / args.session
    if not session.is_dir():
        raise ValueError("session-missing")
    answers, manifest = private_path(args.answers), private_path(args.manifest)
    if not answers.is_file() or not manifest.is_file():
        raise ValueError("evidence-path-missing")
    if not out.parent.is_dir():
        raise ValueError("output-parent-missing")
    out.mkdir()
    started, wall = time.monotonic(), utc_ms()
    deadline, next_poll = started + args.seconds, started
    count, bytes_written, api_bytes, failures, projection_failures = 0, 0, 0, 0, 0
    reason, expected_scope = "duration-limit", {}
    projection = CompactProjection()
    namespaces, last_context_path = VisualNamespaces(), None
    evidence_paths = [answers, manifest, manifest.with_name("visual.jsonl"), *(
        session / name for name in ("stdout.jsonl", "ledger.jsonl", "readouts.jsonl", "perception.jsonl"))]
    run = {"format": 1, "session": args.session, "session_dir": str(session.relative_to(ROOT)),
           "answers_log": str(answers.relative_to(ROOT)), "manifest": str(manifest.relative_to(ROOT)),
           "started_at_unix_ms": wall, "requested_seconds": args.seconds, "poll_ms": args.poll_ms,
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "limits": {"api_response_bytes": API_LIMIT, "api_output_bytes": OUTPUT_LIMIT,
                       "max_samples": 1201, "input_bytes_per_file": INPUT_LIMIT, "rows_per_file": ROW_LIMIT,
                       "api_row_bytes": LINE_LIMIT, "projected_events": EVENT_LIMIT,
                       "projected_events_per_sample": EVENT_ROW_LIMIT, "ui_receipt_bytes": UI_RECEIPT_LIMIT,
                        "ui_receipt_rows": EVENT_LIMIT, "context_log_bytes": 8 * 1024 * 1024,
                        "diagnostic_namespaces": NAMESPACE_LIMIT, "namespace_log_bytes": NAMESPACE_BYTES,
                        "namespace_log_rows": NAMESPACE_ROWS},
            "api_samples_projected": True, "response_hash_basis": "unprojected-http-body",
           "input_sizes_at_start": {str(path.relative_to(ROOT)): path.stat().st_size
                                    for path in (answers, manifest, session / "stdout.jsonl", session / "ledger.jsonl", session / "readouts.jsonl")
                                    if path.is_file()}}
    print(dump({"event": "measurement-start", **run}), flush=True)
    try:
        with (out / "api.jsonl").open("xb") as stream:
            while time.monotonic() < deadline and count < 1201:
                request_started = time.monotonic()
                entry = {"request_started_at_unix_ms": utc_ms(), "observer_elapsed_ms": round((request_started - started) * 1000, 3)}
                connection = http.client.HTTPConnection("127.0.0.1", 18090,
                                                       timeout=max(.001, min(2, deadline - request_started)))
                try:
                    connection.request("GET", "/api/state", headers={"Connection": "close", "Accept": "application/json"})
                    socket = connection.sock
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("measurement-deadline")
                    socket.settimeout(min(2, remaining))
                    response = connection.getresponse()
                    raw = bytearray()
                    while len(raw) <= API_LIMIT:
                        if response.isclosed():
                            break
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("measurement-deadline")
                        socket.settimeout(min(2, remaining))
                        block = response.read1(min(16384, API_LIMIT + 1 - len(raw)))
                        if not block:
                            break
                        raw.extend(block)
                    api_bytes += len(raw)
                    if response.status != 200 or len(raw) > API_LIMIT:
                        raise ValueError("api-status-or-byte-limit")
                    state = json.loads(raw, parse_constant=reject_constant)
                    if not isinstance(state, dict) or type(state.get("schema_version")) is not int or state["schema_version"] != 1:
                        raise ValueError("api-schema-mismatch")
                    if any(not isinstance(state.get(key), dict) for key in ("server", "capture_session", "capture")):
                        raise ValueError("api-scope-schema")
                    scope = sample_scope(state)
                    changed = boundary_reason(scope, expected_scope, args.session)
                    if changed:
                        reason = changed
                    elif not isinstance(scope["source_id"], str) or not scope["source_id"]:
                        reason = "source-unavailable"
                    elif type(scope["epoch"]) is not int or scope["epoch"] < 0:
                        reason = "source-epoch-unknown"
                    else:
                        for key, value in scope.items():
                            if value is not None:
                                expected_scope.setdefault(key, value)
                    registry_valid = namespaces.observe(state) if reason == "duration-limit" else False
                    context_path = VisualNamespaces.context_path(state)
                    namespace_id = (Path(context_path).parent.name if registry_valid and isinstance(context_path, str)
                        and any(Path(context_path) == Path(path) for path in namespaces.active_paths) else None)
                    projected, audit = projection.project(state, namespace_id)
                    projection_failures += not audit["complete"]
                    entry.update(state=projected, projected=True, projection=audit,
                                 response_sha256=hashlib.sha256(raw).hexdigest(), response_bytes=len(raw))
                    diagnostics = projected.get("context_diagnostics")
                    if isinstance(diagnostics, dict) and diagnostics.get("log_path"):
                        if namespaces.present:
                            supplied = diagnostics["log_path"]
                            if registry_valid and isinstance(supplied, str) and any(Path(supplied) == Path(path) for path in namespaces.active_paths):
                                last_context_path = supplied
                            else:
                                namespaces.issues["active-log-unvalidated"] += 1
                                if last_context_path is not None and (not isinstance(supplied, str) or Path(last_context_path) != Path(supplied)) and reason == "duration-limit":
                                    reason = "context-log-changed"
                                if last_context_path is None and isinstance(supplied, str):
                                    last_context_path = supplied
                        else:
                            path = private_path(diagnostics["log_path"], PRIVATE / "laya/events")
                            if last_context_path is not None and Path(last_context_path) != path.relative_to(ROOT):
                                if reason == "duration-limit":
                                    reason = "context-log-changed"
                            else:
                                run["context_log"] = str(path.relative_to(ROOT))
                                last_context_path = run["context_log"]
                                if path not in evidence_paths:
                                    evidence_paths.append(path)
                    if isinstance(projected.get("capture_session"), dict) and projected["capture_session"].get("status") in (
                            "failed", "stopped", "complete", "completed") and reason == "duration-limit":
                        reason = "capture-interrupted"
                except (OSError, ValueError, http.client.HTTPException) as exc:
                    failures += 1
                    entry["error"] = type(exc).__name__
                    entry["error_reason"] = str(exc)[:256]
                finally:
                    connection.close()
                entry.update(sampled_at_unix_ms=utc_ms(), request_latency_ms=round((time.monotonic() - request_started) * 1000, 3))
                raw = (dump(entry) + "\n").encode("utf-8")
                if len(raw) > LINE_LIMIT or bytes_written + len(raw) > OUTPUT_LIMIT:
                    reason = "api-row-byte-limit" if len(raw) > LINE_LIMIT else "api-output-byte-limit"
                    break
                stream.write(raw)
                stream.flush()
                bytes_written += len(raw)
                count += 1
                if reason != "duration-limit":
                    break
                next_poll += args.poll_ms / 1000
                now = time.monotonic()
                if next_poll < now:
                    next_poll = now  # No catch-up burst after a delayed request.
                time.sleep(max(0, min(next_poll, deadline) - now))
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        run.update(ended_at_unix_ms=utc_ms(), elapsed_ms=round((time.monotonic() - started) * 1000, 3),
                    samples=count, api_output_bytes=bytes_written, api_response_bytes=api_bytes,
                    api_failures=failures, stop_reason=reason, service_instance=expected_scope.get("service_instance_id"),
                    api_session=expected_scope.get("session_id"), source_id=expected_scope.get("source_id"),
                    source_epoch=expected_scope.get("epoch"), table_context_id=expected_scope.get("table_context_id"),
                    scope=expected_scope, projection_counters=dict(projection.counts),
                    projection_incomplete_samples=projection_failures,
                    collection_complete=reason == "duration-limit" and failures == 0 and projection_failures == 0 and count > 0
                        and not any(projection.counts[key] for key in ("event_drops", "row_drops", "invalid_events")),
                    input_sizes_at_end={str(path.relative_to(ROOT)): path.stat().st_size
                                        for path in evidence_paths if path.is_file()})
        run["input_sizes_at_end"][str((out / "api.jsonl").relative_to(ROOT))] = bytes_written
        if namespaces.present:
            run["visual_namespaces"] = namespaces.snapshot()
            run["collection_complete"] &= not namespaces.issues
            for namespace in namespaces.entries.values():
                for kind in ("visual_log", "context_log"):
                    run["input_sizes_at_end"][namespace[kind]["path"]] = namespace[kind]["bytes"]
        write_json(out / "run.json", run)
    analyze(out, ui_receipts=getattr(args, "ui_receipts_path", None))


def measurement_self_test():
    edges = series([{"t": 10000}, {"t": 20000}], "t", 0, 30000)
    assert edges["gaps_gt_10000ms"] == edges["censored_edges_gt_10000ms"] == 0
    edges = series([{"t": 10001}, {"t": 20002}], "t", 0, 30003)
    assert edges["gaps_gt_10000ms"] == 1 and edges["censored_edges_gt_10000ms"] == 2
    capture = dict(zip(CAPTURE_KEYS, ("service", "feed", "owner", "source", 1, 1, 100, 1000, "f" * 64, 939, 714)))
    value = {"schema_version": 1, "session_id": "feed", "server": {"instance_id": "service"},
        "capture_session": {"session_id": "owner"}, "capture": {"source_id": "source", "epoch": 1},
        "table_context": {"capture": capture, "seats": [], "events": [
            {"event_id": str(index), "capture": capture} for index in range(4)]},
        "history": {"events": ["not-copied"] * 100}, "event_evidence": {"closure_count": 1}}
    projected, audit = CompactProjection(event_limit=1, row_limit=2).project(value)
    assert "history" not in projected and len(projected["table_context"]["events"]) == 1
    assert audit["complete"] is False and audit["event_counters"]["row_drops"] == 2
    assert capture_key(projected["table_context"]["capture"]) == capture_key(capture)
    seat = {"seat": 1, "occupancy": "occupied", "identity": "Player", "occupant_epoch": 1}
    stats = {"source": "client_profile_tooltip", "seat": 1, "owner": "Player", "occupant_epoch": 1,
             "capture": capture, "captured_at_unix_ms": 1000, "metrics": {}}
    validate_stats(stats, seat, {**capture, "sequence": 2, "captured_at_ms": 200, "captured_at_unix_ms": 2000})
    try:
        validate_stats(stats, {**seat, "identity": "Replacement", "occupant_epoch": 2}, capture)
        raise AssertionError("owner-replacement-accepted")
    except ValueError:
        pass
    run = {"session": "owner", "started_at_unix_ms": 1000, "ended_at_unix_ms": 2000}
    ui = {"field": "identity", "seat": 1, "capture": capture, "published_at_unix_ms": 1500}
    later = {**value, "event_evidence": {"closure_count": 99}}
    report = analyze_context([(0, {"state": value, "sampled_at_unix_ms": 1100}),
        (1, {"state": later, "sampled_at_unix_ms": 3000})], run, [ui, {**ui, "capture": {**capture, "sequence": 2}}])
    assert report["producer_evidence"]["latest_collected"]["event_evidence"]["status"]["closure_count"] == 1
    assert report["ui"]["counts"]["accepted_publications"] == 1
    assert report["ui"]["rejected_records"]["ui-original-not-in-collected-window"] == 1
    assert report["seats"]["1"]["context"]["attempt_starts"]["count"] == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "analyze", "preview", "source", "summary", "self-test"))
    parser.add_argument("--out")
    parser.add_argument("--report", default="timing.json")
    parser.add_argument("--session")
    parser.add_argument("--answers")
    parser.add_argument("--manifest")
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--poll-ms", type=int, default=1000)
    parser.add_argument("--start-unix-ms", type=int)
    parser.add_argument("--end-unix-ms", type=int)
    parser.add_argument("--context")
    parser.add_argument("--ui-receipts", help="Private bounded frontend receipt JSON exported after the window; no source backfill")
    args = parser.parse_args()
    if args.mode == "self-test":
        exact = series([{"t": 0}, {"t": 10000}, {"t": 30001}], "t", 0, 40000)
        assert exact["intervals_ms"] == [10000, 20001]
        assert exact["gaps_gt_10000ms"] == 1 and exact["missed_10000ms_deadlines"] == 2
        assert series([], "t", 0, 600000)["max_gap_including_edges_ms"] == 600000
        assert iso_us("1970-01-01T00:00:00.123456+00:00") == 123456
        assert series([{"t": 1791930000000001}, {"t": 1791930000000003}], "t", 1791930000000,
                      1791930000001, scale=1000)["intervals_ms"] == [.002]
        assert pass_signature({"pass": "p", "questions": [{"question": "g1", "answer": {"value": "1"}, "score": .9, "truncated": False}]}) == pass_signature({"pass": "p", "answers": {"g1": {"v": "1", "p": .9, "truncated": False}}}, True)
        scope = {"session_id": "a", "source_id": "s", "epoch": 1, "sequence": 9, "captured_at_ms": 100}
        frame = {"source_utc_unix_ms": 1000, "captured_at_monotonic_ms": 100, "frame_index": 9,
                 "sha256": "f" * 64, "width": 939, "height": 714, "filename": "frame-0000000009.png"}
        value = {**scope, "service_instance_id": "i", "captured_at_unix_ms": 1000, "sha256": "f" * 64,
                 "width": 939, "height": 714, "board": {"candidate_cards": []}, "processing_ms": 2,
                 "actions": {"capture": scope, "seats": [{"seat": seat, **{family: {"source_capture": scope,
                     "status": "provisional" if family == "badge" else "unknown", "value": {"value": "fold"} if family == "badge" else None}
                     for family in ("badge", "visible_wager")}} for seat in range(6, 0, -1)]},
                 "sightings": [{"sequence": 1, "seat": 2, "action": "fold", "captured_at_ms": 100}]}
        state = {"session_id": "a", "server": {"instance_id": "i"}, "capture": {"source_id": "s"}, "visual_observation": value}
        visual = analyze_visual([(1, {"event": "visual_frame", "frame": frame})],
                  [(2, {"sampled_at_unix_ms": 1500, "state": state}), (3, {"sampled_at_unix_ms": 1600, "state": state})],
                  [(4, value)], {(1000, 100): [frame]}, 1000, 2000)
        assert visual["confirmed_processed_frames"]["count"] == visual["api_first_presence"]["count"] == 1
        assert visual["exact_native_frame_matches"] == visual["exact_manifest_matches"] == 1
        assert visual["source_events"][0]["captured_at_unix_ms"] == 1000
        assert visual["seats"]["2"]["badge"]["api_presence"]["literal_samples"] == 2
        assert "sequence" not in visual["sightings"][0]["scope"]
        measurement_self_test()
        print("self-test: passed (strict deadlines/edges, bounded projection, ownership/closure counters, UI no-backfill, historical visual/numeric helpers)")
        return
    if not args.out or args.mode in ("collect", "preview", "source") and not all((args.session, args.answers, args.manifest)):
        parser.error("--out required; collect/preview/source also require --session, --answers, --manifest")
    if Path(args.report).name != args.report or not args.report.endswith(".json"):
        parser.error("--report must be a JSON basename")
    out = private_path(args.out, TRAIN)
    context = None
    args.ui_receipts_path = private_path(args.ui_receipts, TRAIN) if args.ui_receipts else None
    if args.context:
        path = private_path(args.context, TRAIN)
        if path.stat().st_size > 16384:
            parser.error("context byte limit")
        context = json.loads(path.read_bytes(), parse_constant=reject_constant)
    if args.mode == "collect":
        collect(args, out)
    elif args.mode == "analyze":
        analyze(out, args.report, context=context, ui_receipts=args.ui_receipts_path)
    elif args.mode in ("preview", "source"):
        rows = read_rows(out / "api.jsonl", [])
        if not rows:
            raise ValueError("no-api-evidence")
        first, last = rows[0][1], rows[-1][1]
        state = first.get("state", {})
        if state.get("capture_session", {}).get("session_id") != args.session:
            raise ValueError("preview-session-mismatch")
        start, end = first["request_started_at_unix_ms"], last["sampled_at_unix_ms"]
        reason = "interim-prefix-not-a-complete-600s-run"
        if args.mode == "source":
            start, end = args.start_unix_ms, args.end_unix_ms
            if (start is None or end is None or not 0 < end - start <= 600000 or end > utc_ms()):
                parser.error("source requires an elapsed --start-unix-ms/--end-unix-ms window <=600000ms")
            reason = "source-window-analysis-api-coverage-is-subset"
        run = {"session": args.session, "session_dir": f".local/laya/manual-capture/{args.session}",
               "answers_log": str(private_path(args.answers).relative_to(ROOT)),
               "manifest": str(private_path(args.manifest).relative_to(ROOT)),
               "started_at_unix_ms": start, "ended_at_unix_ms": end,
               "elapsed_ms": end - start, "stop_reason": reason}
        analyze(out, args.report, run, context, args.ui_receipts_path)
    else:
        summarize(json.loads((out / args.report).read_bytes()))


if __name__ == "__main__":
    main()
