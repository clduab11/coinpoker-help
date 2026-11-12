"""Bounded immutable event originals; storage failure never stops acquisition."""

from collections import deque
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import threading


class EventEvidence:
    def __init__(self, root, instance_id, *, max_bytes=256 * 1024 * 1024,
                 max_frames=512, max_log_bytes=16 * 1024 * 1024):
        self.root = Path(root).resolve()
        self.directory = self.root / ".local/laya/events" / hashlib.sha256(instance_id.encode()).hexdigest()[:32]
        self.max_bytes, self.max_frames, self.max_log_bytes = max_bytes, max_frames, max_log_bytes
        self.lock = threading.RLock()
        self.paths, self.receipts = {}, set()
        self.events = deque(maxlen=200)
        self.bytes = self.log_bytes = self.count = 0
        self.complete, self.reason = True, None
        self.log = None
        self.public_events = ()
        self.public_summaries = ()
        self._cache_status()

    def _cache_status(self):
        self.public = {"enabled": True, "complete": self.complete, "reason": self.reason,
            "count": self.count, "frames": len(self.receipts), "bytes": self.bytes,
            "log_bytes": self.log_bytes, "max_bytes": self.max_bytes,
            "max_frames": self.max_frames, "max_log_bytes": self.max_log_bytes}

    def _private(self, path):
        from laya_capture import private_path
        return private_path(path, root=self.root)

    def _image(self, png, *, original=None):
        digest = hashlib.sha256(png).hexdigest()
        if digest in self.paths:
            return digest
        if original is not None:
            path = self._private(original)
            if path.read_bytes() != png:
                raise ValueError("archival-original-changed")
        else:
            if self.bytes + len(png) > self.max_bytes:
                raise ValueError("image-byte-limit")
            path = self._private(self.directory / (digest + ".png"))
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_bytes() != png:
                    raise ValueError("immutable-evidence-changed")
            else:
                with path.open("xb") as stream:
                    stream.write(png)
            self.bytes += len(png)
        self.paths[digest] = path
        return digest

    def record(self, png, capture, kind, changes, *, original=None, crops=()):
        """Record one selected occurrence with its original, never a mailbox path."""
        with self.lock:
            try:
                if hashlib.sha256(png).hexdigest() != capture["sha256"]:
                    raise ValueError("original-hash-mismatch")
                receipt = tuple(capture.get(k) for k in (
                    "service_instance_id", "session_id", "source_id", "epoch", "sequence",
                    "sha256", "captured_at_ms", "popup_index"))
                if receipt not in self.receipts and len(self.receipts) >= self.max_frames:
                    raise ValueError("frame-limit")
                if not self.complete:
                    return None
                evidence_id = self._image(png, original=original)
                crop_refs = []
                if crops:
                    from PIL import Image
                    with Image.open(io.BytesIO(png)) as image:
                        for bounds in crops:
                            if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
                                    or any(type(x) is not int for x in bounds)
                                    or not 0 <= bounds[0] < bounds[2] <= image.width
                                    or not 0 <= bounds[1] < bounds[3] <= image.height):
                                raise ValueError("invalid-crop-bounds")
                            buffer = io.BytesIO()
                            image.crop(bounds).save(buffer, format="PNG")
                            crop_refs.append({"bounds": list(bounds), "sha256": self._image(buffer.getvalue()),
                                              "original_sha256": evidence_id})
                event = {"schema_version": 1, "event_id": self.count + 1, "kind": kind,
                         "capture": copy.deepcopy(capture), "changes": copy.deepcopy(changes),
                         "evidence_id": evidence_id, "crops": crop_refs,
                         "original_path": str(self.paths[evidence_id].relative_to(self.root)),
                         "order_status": "capture-order-not-gameplay-order"}
                line = json.dumps(event, allow_nan=False, separators=(",", ":")).encode() + b"\n"
                if len(line) > 64 * 1024 or self.log_bytes + len(line) > self.max_log_bytes:
                    raise ValueError("event-log-byte-limit")
                if self.log is None:
                    path = self._private(self.directory / "events.jsonl")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    self.log = path.open("xb")
                self.log.write(line)
                self.log.flush()
                self.log_bytes += len(line)
                self.count += 1
                self.receipts.add(receipt)
                self.events.append(event)
                self.public_events = tuple(self.events)
                summary = {key: copy.deepcopy(event[key]) for key in
                    ("schema_version", "event_id", "kind", "capture", "evidence_id", "crops", "order_status")}
                changes = event["changes"]
                if event["kind"] == "visible-numeric-change":
                    summary["changes"] = [{"kind": family + "_change", "seat": seat,
                        **{key: reading[key] for key in ("literal", "value", "status", "bounds", "crop_sha256", "reason")
                           if key in reading and reading[key] is not None}}
                        for family, seat, reading in [("pot", None, changes["pot"]),
                            *[(family, row["seat"], row[family]) for row in changes["seats"] for family in ("stack", "wager")]]]
                elif isinstance(changes, list):
                    summary["changes"] = [{key: copy.deepcopy(change[key]) for key in
                        ("kind", "type", "seat", "status", "reason", "identity", "occupant_epoch", "table_context_id", "role", "hero_seat", "owner", "capture")
                        if key in change} for change in changes if isinstance(change, dict)]
                else:
                    summary["changes"] = {key: copy.deepcopy(changes[key]) for key in ("owner", "metrics", "phase") if key in changes}
                self.public_summaries = (*self.public_summaries[-199:], summary)
                return copy.deepcopy(event)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.complete, self.reason = False, str(error)[:120]
                return None
            finally:
                self._cache_status()

    def snapshot(self):
        return dict(self.public)

    def event_snapshot(self):
        return copy.deepcopy(list(self.public_events))

    def public_event_snapshot(self, session_id, limit=20):
        return copy.deepcopy([event for event in self.public_summaries
                              if event["capture"].get("session_id") == session_id][-limit:])

    def read(self, evidence_id):
        if not re.fullmatch(r"[0-9a-f]{64}", evidence_id):
            return None
        path = self.paths.get(evidence_id)
        if path is None:
            return None
        try:
            path = self._private(path)
            with path.open("rb") as stream:
                png = stream.read(8 * 1024 * 1024 + 1)
            if not 0 < len(png) <= 8 * 1024 * 1024 or hashlib.sha256(png).hexdigest() != evidence_id:
                return None
            return png
        except (OSError, ValueError):
            return None

    def close(self):
        with self.lock:
            if self.log is not None:
                self.log.close()
                self.log = None
