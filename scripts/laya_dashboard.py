"""Private, bounded Rust-feed snapshots for the read-only loopback dashboard."""

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
PORT = 18090
MAX_RECORD = 256 * 1024
MAX_EVENTS = 10_000
MAX_LEDGER_BYTES = 25 * 1024 * 1024
HEARTBEAT_MS = 2_500
ACTIONS = ("fold", "check", "call", "bet", "raise", "all_in")
ROLES = ("observing", "seated_waiting", "your_turn", "uncertain")
VERIFIED_FIELDS = ("hero_seated", "action_required", "controls", "pot_size", "to_call",
                   "hero_chips", "min_raise_to", "max_raise_to", "acting_seat",
                   "acting_to_call", "wagers")
CODE = re.compile(r"^[a-z0-9_-]{1,80}$")
RANKS = dict(zip(("two", "three", "four", "five", "six", "seven", "eight", "nine",
                  "ten", "jack", "queen", "king", "ace"),
                 ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")))
SUITS = ("spades", "hearts", "diamonds", "clubs")


def integer(value, maximum=9_007_199_254_740_991):
    return value if type(value) is int and 0 <= value <= maximum else None


def code(value, fallback="source-status"):
    return value if isinstance(value, str) and CODE.fullmatch(value) else fallback


def local_path(value, directory=".local"):
    base = (ROOT / directory).resolve()
    path = (ROOT / value).resolve()
    if not path.is_relative_to(base):
        raise ValueError("private path must remain under " + directory)
    return path


def cards(values, maximum):
    if not isinstance(values, list) or len(values) > maximum:
        raise ValueError("invalid cards")
    result = []
    for card in values:
        if not isinstance(card, dict):
            raise ValueError("invalid card")
        rank = card.get("rank")
        if not isinstance(rank, str):
            raise ValueError("invalid card")
        rank = RANKS.get(rank, rank)
        if rank == "T":
            rank = "10"
        suit = card.get("suit")
        if rank not in RANKS.values() or suit not in SUITS:
            raise ValueError("invalid card")
        result.append({"rank": rank, "suit": suit})
    return result


def unknown_controls():
    return [{"action": action, "presence": "unknown", "enabled": "unknown"} for action in ACTIONS]


class PrivateLedger:
    def __init__(self, path=None, max_events=MAX_EVENTS, max_bytes=MAX_LEDGER_BYTES):
        self.path = path
        self.max_events, self.max_bytes = max_events, max_bytes
        self.count = self.bytes = 0
        self.complete = True
        self.stream = None

    def append(self, record):
        if self.path is None or not self.complete:
            return
        data = (json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        if self.count >= self.max_events or self.bytes + len(data) > self.max_bytes:
            self.complete = False
            return
        try:
            if self.stream is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.stream = self.path.open("xb")
            self.stream.write(data)
            self.stream.flush()
            self.count += 1
            self.bytes += len(data)
        except OSError:
            self.complete = False

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class DashboardState:
    def __init__(self, alias, checkpoint=None, *, monotonic=time.monotonic, wall=time.time):
        self.lock = threading.RLock()
        self.monotonic, self.wall = monotonic, wall
        self.session_id = uuid.uuid4().hex
        self.event_seq = 0
        self.source = "idle"
        self.model = {"model_state": "disabled", "model_error": None, "alias": alias,
                      "checkpoint": checkpoint, "temperature_calibration_loaded": False,
                      "quality_gate": "failed", "advice_ready": False, "inference_busy": False}
        self.capture = {"state": "idle", "fresh_capture": False, "frames": 0,
                        "recorded_frames": 0, "recording_enabled": False,
                        "width": None, "height": None, "last_heartbeat_unix_ms": None}
        self.observation = None
        self.deadline = self.last_heartbeat = None
        self.version = (0, 0)
        self.invalidated_version = None
        self.target = None
        self.identity_configured = False
        self.message = "Start with references/replay. Capture requires an explicit operator launch."
        self.history = {"state": "unavailable", "events": [], "counts": {}, "gaps": 0,
                        "ledger": {"enabled": False, "complete": True}}
        self.ledger = PrivateLedger()

    def set_model(self, state, error=None, calibrated=False):
        with self.lock:
            self.model.update(model_state=state, model_error=error,
                              temperature_calibration_loaded=bool(calibrated))
            self.event_seq += 1

    def set_busy(self, value):
        with self.lock:
            self.model["inference_busy"] = bool(value)

    def begin_stream(self, ledger_path=None):
        with self.lock:
            self.ledger.close()
            self.session_id = uuid.uuid4().hex
            self.event_seq = 0
            self.source = "live"
            self.target = None
            self.version = (0, 0)
            self.invalidated_version = None
            self.last_heartbeat = None
            self.identity_configured = False
            self.capture.update(state="starting", fresh_capture=False, frames=0, recorded_frames=0,
                                recording_enabled=False, last_heartbeat_unix_ms=None)
            self.history = {"state": "unavailable", "events": [], "counts": {}, "gaps": 0,
                            "ledger": {"enabled": ledger_path is not None, "complete": True}}
            if ledger_path is True:
                ledger_path = local_path(".local/history/" + self.session_id + "/ledger.jsonl")
            self.ledger = PrivateLedger(ledger_path)
            self._invalidate("stream-started")

    def end_stream(self, reason="feed-eof"):
        with self.lock:
            self.capture.update(state="disconnected", fresh_capture=False)
            self._invalidate(reason)
            self.ledger.close()

    def _invalidate(self, reason):
        self.invalidated_version = self.version
        self.observation = self.deadline = None
        self.message = reason
        self.history["state"] = "partial" if self.source == "live" else "unavailable"

    def _target(self, value):
        if not isinstance(value, dict):
            return None
        pid = integer(value.get("process_id"), 0xffffffff)
        encoded = value.get("hwnd")
        hwnd = (int(encoded, 16) if isinstance(encoded, str)
                and re.fullmatch(r"0x[0-9a-fA-F]{1,16}", encoded) else None)
        exe = value.get("exe_name")
        if pid is None or hwnd is None or not isinstance(exe, str) or len(exe) > 256:
            return None
        text = json.dumps([self.session_id, pid, hwnd, exe], separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def ingest(self, record):
        with self.lock:
            self.event_seq += 1
            if not isinstance(record, dict) or record.get("schema_version") != 2:
                self._invalidate("invalid-feed-record")
                return
            event = record.get("event")
            saved = {"event": code(event), "sequence": self.event_seq,
                     "recorded_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            if event == "configuration":
                self.identity_configured = record.get("identity_configured") is True
                self.message = "Awaiting capture heartbeat; model quality remains unapproved."
                saved["identity_configured"] = self.identity_configured
            elif event == "capture_health":
                gen, epoch = integer(record.get("generation")), integer(record.get("epoch"))
                target = self._target(record.get("identity"))
                emitted = integer(record.get("emitted_at_unix_ms"))
                captured = integer(record.get("captured_at_unix_ms"))
                now = int(self.wall() * 1000)
                if (gen is None or epoch is None or gen < self.version[0] or epoch < self.version[1]
                        or emitted is None or emitted > now or now - emitted >= HEARTBEAT_MS):
                    self._invalidate("obsolete-health-record")
                    return
                if target != self.target or epoch != self.version[1]:
                    self._invalidate("capture-identity-or-epoch-changed")
                self.target = target
                self.version = (gen, epoch)
                fresh = (record.get("fresh_capture") is True and target is not None
                         and captured is not None and captured <= emitted and now - captured < 1000)
                self.last_heartbeat = self.monotonic()
                self.capture.update(state="active" if fresh else "unavailable", fresh_capture=fresh,
                                    frames=integer(record.get("frame_count")) or 0,
                                    recorded_frames=0, recording_enabled=False,
                                    width=integer(record.get("frame_width"), 16384),
                                    height=integer(record.get("frame_height"), 16384),
                                    last_heartbeat_unix_ms=int(self.wall() * 1000))
                if not fresh:
                    self._invalidate("capture-not-fresh")
                saved.update(self.capture)
                saved["target_id"] = target
            elif event == "observation":
                ticket = record.get("observation")
                if not isinstance(ticket, dict):
                    self._invalidate("invalid-observation")
                    return
                gen, epoch = integer(ticket.get("generation")), integer(ticket.get("epoch"))
                target = self._target(ticket.get("identity"))
                valid = integer(record.get("valid_for_ms"), 5000)
                emitted = integer(record.get("emitted_at_unix_ms"))
                expires = integer(record.get("expires_at_unix_ms"))
                now = int(self.wall() * 1000)
                if (gen is None or epoch is None or gen < self.version[0] or epoch < self.version[1]
                        or self.invalidated_version is not None and (gen, epoch) <= self.invalidated_version
                        or target is None or target != self.target or not self.capture["fresh_capture"]
                        or self.last_heartbeat is None or (self.monotonic() - self.last_heartbeat) * 1000 >= HEARTBEAT_MS
                        or not valid or emitted is None or expires is None or emitted > now
                        or expires <= now or expires > emitted + valid):
                    self._invalidate("obsolete-or-expired-observation")
                    return
                try:
                    hero = cards(record.get("hero_cards"), 2)
                    board = cards(record.get("board"), 5)
                    pairs = [(c["rank"], c["suit"]) for c in hero + board]
                    if len(set(pairs)) != len(pairs):
                        raise ValueError("duplicate cards")
                except ValueError:
                    self._invalidate("invalid-observation-cards")
                    return
                if (self.observation is not None and (gen, epoch) ==
                        (self.observation["generation"], self.observation["epoch"])):
                    return
                phase = record.get("game_phase")
                captured = integer(record.get("captured_at_unix_ms"))
                if phase not in ("preflop", "flop", "turn", "river", "showdown"):
                    self._invalidate("unknown-observation-phase")
                    return
                if len(hero) not in (0, 2) or len(board) != {"preflop": 0, "flop": 3, "turn": 4,
                                                          "river": 5, "showdown": 5}[phase]:
                    self._invalidate("invalid-observation-cards")
                    return
                if captured is None or captured > emitted or expires > captured + 5000:
                    self._invalidate("invalid-observation-age")
                    return
                # Per-field admission is not model quality approval. Legacy placeholders
                # and an empty hero-card list cannot establish seating or a turn.
                verified = record.get("verified_fields")
                verified = (set(verified) if isinstance(verified, list) and len(verified) <= len(VERIFIED_FIELDS)
                            and all(isinstance(v, str) and v in VERIFIED_FIELDS for v in verified) else set())
                seated = record.get("hero_seated") if "hero_seated" in verified else None
                seated = seated if type(seated) is bool else None
                required = record.get("action_required") if "action_required" in verified else None
                required = required if type(required) is bool else None
                amounts = {field: integer(record.get(field)) if field in verified else None
                           for field in ("pot_size", "to_call", "hero_chips", "min_raise_to",
                                         "max_raise_to", "acting_to_call")}
                acting = integer(record.get("acting_seat"), 6) if "acting_seat" in verified else None
                acting = acting if acting else None
                if acting is None:
                    amounts["acting_to_call"] = None
                controls, controls_valid = unknown_controls(), False
                raw_controls = record.get("controls")
                if "controls" in verified and isinstance(raw_controls, list) and len(raw_controls) <= len(ACTIONS):
                    known = {}
                    for item in raw_controls:
                        if (not isinstance(item, dict) or item.get("action") not in ACTIONS
                                or item["action"] in known or item.get("presence") not in ("present", "absent", "unknown")
                                or item.get("enabled") not in ("enabled", "disabled", "unknown")
                                or item["presence"] != "present" and item["enabled"] != "unknown"):
                            break
                        known[item["action"]] = {k: item[k] for k in ("action", "presence", "enabled")}
                    else:
                        controls = [known.get(item["action"], item) for item in controls]
                        controls_valid = True
                enabled = [item["action"] for item in controls if item["enabled"] == "enabled"]
                present = any(item["presence"] == "present" for item in controls)
                contradiction = ("controls" in verified and not controls_valid
                                 or seated is False and (bool(hero) or required is True or present)
                                 or required is False and bool(enabled)
                                 or "check" in enabled and ("call" in enabled or "fold" in enabled)
                                 or amounts["to_call"] == 0 and ("call" in enabled or "fold" in enabled)
                                 or amounts["to_call"] is not None and amounts["to_call"] > 0 and "check" in enabled
                                 or amounts["min_raise_to"] is not None and amounts["max_raise_to"] is not None
                                 and amounts["min_raise_to"] > amounts["max_raise_to"])
                role = "uncertain"
                if not contradiction:
                    if seated is False and required is False and not hero:
                        role = "observing"
                    elif seated is True and required is False:
                        role = "seated_waiting"
                    elif (seated is True and required is True and len(hero) == 2 and controls_valid
                          and enabled and phase != "showdown"):
                        role = "your_turn"
                if record.get("role") not in ROLES or record["role"] != role:
                    role = "uncertain"
                if role == "uncertain":
                    required = None
                    controls = unknown_controls()
                    if contradiction:
                        seated = None
                if role not in ("seated_waiting", "your_turn"):
                    amounts["hero_chips"] = None
                if role != "your_turn":
                    for field in ("to_call", "min_raise_to", "max_raise_to"):
                        amounts[field] = None
                wagers = []
                raw_wagers = record.get("wagers")
                if "wagers" in verified and isinstance(raw_wagers, list) and len(raw_wagers) <= 6:
                    seen = set()
                    for item in raw_wagers:
                        seat = integer(item.get("seat"), 6) if isinstance(item, dict) else None
                        if not seat or seat in seen:
                            wagers = []
                            break
                        seen.add(seat)
                        wagers.append({"seat": seat, "amount": integer(item.get("amount"))})
                # Metrics need a separately approved capability, even with verified
                # inputs or asserted feed quality. Never calculate hero/observer odds here.
                metrics = {"hand_rank": None, "pot_odds": None, "draw": None, "equity_pct": None}
                remaining = min(valid, expires - now)
                previous_version = self.version
                self.version = (gen, epoch)
                deadline = self.monotonic() + remaining / 1000
                if (gen, epoch) == previous_version and self.deadline is not None:
                    deadline = min(deadline, self.deadline)
                self.deadline = deadline
                self.observation = {"generation": gen, "epoch": epoch, "game_phase": phase,
                                    "captured_at_unix_ms": captured,
                                    "hero_cards": hero, "board": board,
                                    "role": role, "hero_seated": seated, "acting_seat": acting,
                                    "amounts": amounts, "wagers": wagers, "metrics": metrics,
                                    "available_actions": enabled if role == "your_turn" else None,
                                    "controls": controls, "action_required": required,
                                    "experimental": True, "quality_approved": False,
                                    "expires_at_unix_ms": expires, "remaining_ms": remaining}
                self.message = "Experimental observation only; positive seated data and quality gates are pending."
                saved["observation"] = self.observation
            elif event in ("observation_invalidated", "clear", "discarded"):
                gen, epoch = integer(record.get("generation")), integer(record.get("epoch"))
                if gen is not None:
                    self.version = (max(gen, self.version[0]), max(epoch or 0, self.version[1]))
                self._invalidate(code(record.get("reason"), "observation-invalidated"))
                self.history["gaps"] += 1
                saved["reason"] = self.message
            elif event == "status":
                state = code(record.get("state"), "unavailable")
                if state not in ("analyzing", "capturing_table", "candidate_table"):
                    self.capture.update(state="unavailable", fresh_capture=False)
                    self._invalidate(code(record.get("reason"), state))
                saved["state"] = state
            elif event == "history":
                summary = record.get("summary", {})
                if not isinstance(summary, dict):
                    self._invalidate("invalid-history-record")
                    return
                events = summary.get("events", [])
                sanitized = []
                if isinstance(events, list):
                    for item in events[-200:]:
                        if isinstance(item, dict):
                            kind = item.get("event")
                            kind = kind if isinstance(kind, str) else None
                            detail = item.get("action") if isinstance(item.get("action"), dict) else item
                            action = detail.get("kind") if kind == "action" else None
                            seat = integer(detail.get("seat"), 5)
                            ordinal = integer(detail.get("preflop_raise_ordinal"), MAX_EVENTS)
                            if (ordinal is None or ordinal < 2 or action not in ("bet", "raise")
                                    or item.get("street") != "preflop" or detail.get("trusted") is not True
                                    or detail.get("full_raise") is not True or detail.get("forced") is not None):
                                ordinal = None
                            sanitized.append({"kind": {"action": "action", "hand_started": "boundary",
                                                       "movement": "boundary", "hand_outcome": "hand"}.get(kind, "gap"),
                                              "reason": code(item.get("reason"), "unknown-evidence"),
                                              "sequence": integer(item.get("event_sequence")),
                                              "seat": seat + 1 if seat is not None else None,
                                               "amount": integer(detail.get("amount")),
                                               "all_in": detail.get("all_in") if type(detail.get("all_in")) is bool else None,
                                               "preflop_raise_ordinal": ordinal,
                                               "action": action if action in ACTIONS else None})
                counts = summary.get("counts", {})
                if not isinstance(counts, dict):
                    counts = {}
                fields = ("folds", "checks", "calls", "bets", "raises")
                values = [integer(counts.get(field), MAX_EVENTS) for field in fields]
                normalized_counts = {"observed_actions": sum(values) if all(v is not None for v in values) else None,
                                      "eligible_hands": None}
                normalized_counts.update(zip(fields, values))
                occupants = summary.get("occupants", [])
                if isinstance(occupants, list) and len(occupants) <= 6:
                    hands = [integer(o.get("eligible_hands"), MAX_EVENTS) for o in occupants if isinstance(o, dict)]
                    if len(hands) == len(occupants) and all(h is not None for h in hands):
                        normalized_counts["eligible_hands"] = sum(hands)
                for field in ("three_bets", "four_bets", "incomplete_raises"):
                    normalized_counts[field] = integer(counts.get(field), MAX_EVENTS)
                self.history.update(state="partial", events=sanitized,
                                    counts=normalized_counts,
                                    gaps=max(self.history["gaps"], integer(summary.get("gaps")) or 0))
                saved["history"] = {"state": "partial", "events": sanitized,
                                    "counts": normalized_counts,
                                    "gaps": self.history["gaps"]}
            elif event == "decision":
                self._invalidate("advice-capability-not-approved")
                saved["reason"] = self.message
            else:
                # Bare replay decisions and weaker table readings never enter this stream.
                return
            self.ledger.append(saved)

    def snapshot(self):
        with self.lock:
            now = self.monotonic()
            if self.last_heartbeat is not None and (now - self.last_heartbeat) * 1000 >= HEARTBEAT_MS:
                self.capture.update(state="unavailable", fresh_capture=False)
                self._invalidate("capture-heartbeat-expired")
            if self.deadline is not None:
                remaining = int((self.deadline - now) * 1000)
                if remaining <= 0 or self.observation["expires_at_unix_ms"] <= int(self.wall() * 1000):
                    self._invalidate("observation-expired")
                else:
                    self.observation["remaining_ms"] = remaining
            self.history["ledger"]["complete"] = self.ledger.complete
            return copy.deepcopy({"schema_version": 1, "session_id": self.session_id,
                                  "event_seq": self.event_seq, "source": self.source,
                                  "server": self.model, "capture": self.capture,
                                  "observation": self.observation, "advice": None,
                                  "history": self.history,
                                  "readiness": "UI_READY",
                                  "message": self.message})


def _reject_constant(_):
    raise ValueError("nonfinite JSON")


def drain_feed(stream, state):
    try:
        while True:
            raw = stream.readline(MAX_RECORD + 1)
            if not raw:
                break
            if len(raw) > MAX_RECORD or not raw.endswith(b"\n"):
                state.end_stream("invalid-feed-size")
                return
            try:
                record = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
            except (ValueError, UnicodeDecodeError):
                state.end_stream("invalid-feed-json")
                return
            state.ingest(record)
    except (OSError, ValueError):
        state.end_stream("feed-read-failed")
        return
    state.end_stream()


def capture_argv(config):
    if not isinstance(config, dict):
        raise ValueError("invalid live config")
    allowed = {"binary", "exe_name", "pid", "window_hwnd", "window_title", "lobby_title", "lobby_size"}
    if (set(config) - allowed or not isinstance(config.get("exe_name"), str)
            or not config["exe_name"] or len(config["exe_name"]) > 256):
        raise ValueError("live config needs an explicit executable identity")
    name = config.get("binary", "target/release/coinpoker.exe")
    if not isinstance(name, str):
        raise ValueError("invalid native binary")
    binary = (ROOT / name).resolve()
    if not binary.is_relative_to(ROOT) or binary.stem != "coinpoker" or not binary.is_file():
        raise ValueError("native binary must be a built coinpoker binary inside the checkout")
    argv = [str(binary)]
    flags = {"exe_name": "--exe-name", "pid": "--pid", "window_hwnd": "--window-hwnd",
             "window_title": "--table-title", "lobby_title": "--lobby-title", "lobby_size": "--lobby-size"}
    for field, flag in flags.items():
        if field not in config:
            continue
        value = config[field]
        if type(value) not in (str, int) or not str(value) or len(str(value)) > 512:
            raise ValueError("invalid live config value")
        if field == "pid" and (type(value) is not int or not 0 < value <= 0xffffffff):
            raise ValueError("invalid process identity")
        if field == "lobby_size" and (not isinstance(value, str) or not re.fullmatch(r"[1-9]\d{0,4}x[1-9]\d{0,4}", value)):
            raise ValueError("invalid lobby size")
        argv.extend((flag, str(value)))
    return argv


class LiveFeed:
    def __init__(self, config_path, state):
        path = local_path(config_path)
        if not path.is_file() or path.stat().st_size > MAX_RECORD:
            raise ValueError("invalid live config size")
        config = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        argv = capture_argv(config)
        env = {k: v for k, v in os.environ.items() if not k.startswith("COINPOKER_")}
        env.update(COINPOKER_VLM_ENDPOINT="http://127.0.0.1:18090/v1/laya/predict",
                   COINPOKER_VLM_MODEL=state.model["alias"])
        state.begin_stream(True)
        error_path = local_path(".local/history/" + state.session_id + "/feed.stderr.txt")
        error_path.parent.mkdir(parents=True, exist_ok=True)
        self.error = error_path.open("xb")
        try:
            self.process = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=self.error, shell=False)
        except OSError:
            self.error.close()
            state.end_stream("feed-start-failed")
            raise
        self.state = state
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _terminate(self):
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            except OSError:
                pass

    def _read(self):
        drain_feed(self.process.stdout, self.state)
        # A malformed/closed feed must not leave an invisible capture child running.
        self._terminate()

    def stop(self):
        self._terminate()
        self.thread.join(timeout=3)
        self.process.stdout.close()
        self.error.close()
        self.state.end_stream("feed-stopped")


def references():
    path = ROOT / "scripts/dashboard/reference.json"
    if path.stat().st_size > MAX_RECORD:
        raise ValueError("reference exceeds response bound")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid reference schema")
    return value


def replay():
    frames = []
    for step, title in enumerate(("Waiting: no offered controls", "Hero turn: several buttons coexist",
                                  "Turn changed: controls and advice cleared")):
        state = DashboardState("coinpoker-laya-vision").snapshot()
        state.update(source="demo", session_id="demo-buttons", event_seq=step, message=title)
        if step == 1:
            controls = unknown_controls()
            for item in controls:
                if item["action"] in ("fold", "call", "raise"):
                    item.update(presence="present", enabled="enabled")
            state["observation"] = {"generation": 1, "epoch": 1, "game_phase": "flop",
                                    "hero_cards": [{"rank": "A", "suit": "hearts"}, {"rank": "K", "suit": "hearts"}],
                                    "board": [{"rank": "Q", "suit": "hearts"}, {"rank": "J", "suit": "hearts"},
                                              {"rank": "2", "suit": "clubs"}],
                                    "amounts": {"pot_size": 300, "to_call": 100, "hero_chips": 1000,
                                                "min_raise_to": 200, "max_raise_to": 1000},
                                    "available_actions": ["fold", "call", "raise"], "controls": controls,
                                    "action_required": True, "experimental": True,
                                    "expires_at_unix_ms": None, "remaining_ms": None}
        frames.append(state)
    return {"source": "demo", "scenarios": [{"id": "multi-label-controls", "title": "Controls versus advice",
                                                "description": "Synthetic presentation fixture, not model accuracy or live guidance.",
                                                "frames": frames}]}
