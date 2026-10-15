"""Metadata-only attachment to the user's declared CoinPoker NLH game window.

The built-in rule declares a six-seat layout; titles do not prove game type,
seating, six seats, or calibrated perception. No lobby image, pixel
classification, fixed resolution, or ROI is used. Capture owns current bounds.
An explicitly confirmed private profile can select the exact OS title CoinPoker
when the visible NLH caption is drawn inside that game window. This is not a
default lobby fallback. This module never captures or performs game actions.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ".local/practice-table.json"
USER_SCOPE = "six-max-table"
SELECTOR_EXE = "CoinPoker.exe"
SELECTOR_TITLE_REGEX = r"^NLH\s*[0-9]+"
_NLH_TITLE = re.compile(SELECTOR_TITLE_REGEX)
CONFIRMED_GAME_TITLE_REGEX = r"^CoinPoker$"
_TITLE_RULES = {SELECTOR_TITLE_REGEX: _NLH_TITLE,
                CONFIRMED_GAME_TITLE_REGEX: re.compile(CONFIRMED_GAME_TITLE_REGEX)}
MAX_PROFILE_BYTES = 16 * 1024
MAX_LIST_BYTES = 1024 * 1024
MAX_LIST_RECORD_BYTES = 16 * 1024
MAX_LIST_RECORDS = 10_000
LIST_TIMEOUT_SECONDS = 5
MAX_DIAGNOSTIC_CANDIDATES = 32
RECORDING = {"record_dir": ".local/captures", "record_max_frames": 7200,
             "record_max_bytes": 1073741824, "record_interval_ms": 500}
MESSAGES = {
    "ready": "Game window selected using the user-declared source rule; recognition is evaluated separately.",
    "practice-profile-invalid": "Automatic attachment is blocked: the optional private selector rule is invalid.",
    "practice-profile-confirmation-required": "Saving an optional selector rule requires explicit operator confirmation.",
    "practice-profile-mismatch": "The optional selector rule does not identify one visible game window.",
    "practice-profile-exists": "The optional selector rule already exists; it was not overwritten.",
    "native-binary-missing": "Automatic attachment is blocked: no built checkout binary is available.",
    "native-binary-unsafe": "Automatic attachment is blocked: the checkout binary path is unsafe.",
    "window-list-failed": "Automatic attachment is blocked: metadata discovery failed.",
    "window-list-timeout": "Automatic attachment is blocked: metadata discovery timed out.",
    "window-list-too-large": "Automatic attachment is blocked: metadata discovery exceeded its bound.",
    "window-list-invalid": "Automatic attachment is blocked: window metadata is invalid.",
    "window-list-unavailable": "Automatic attachment is blocked: window metadata is unavailable.",
    "practice-target-absent": "Waiting for one visible game window matching the user-declared selector.",
    "practice-target-ambiguous": "Automatic attachment is blocked: more than one visible game window matches the user-declared selector.",
}
_EXE_CASE = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


class AttachError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def _text(value, maximum=512):
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and value == value.strip() and not value.startswith("--")
            and all(ord(c) >= 32 and ord(c) != 127 and not 0xd800 <= ord(c) <= 0xdfff for c in value))


def _exe(value):
    return (_text(value, 256) and not any(c in value for c in '\\/:*?"<>|')
            and not value.endswith((".", " ")))


def _title(value):
    # Preserve whitespace for the exact authorized regex, including its \s*.
    return (isinstance(value, str) and len(value) <= 4096
            and all(ord(c) != 0 and not 0xd800 <= ord(c) <= 0xdfff for c in value))


def _integer(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def _json(raw, code):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AttachError(code)
            result[key] = value
        return result

    def constant(_):
        raise AttachError(code)

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise AttachError(code) from None


def _private_path(value, root):
    if not isinstance(value, (str, Path)):
        raise AttachError("practice-profile-invalid")
    raw = str(value)
    windows = PureWindowsPath(raw)
    reserved = {"CON", "PRN", "AUX", "NUL", *("COM" + str(i) for i in range(1, 10)),
                *("LPT" + str(i) for i in range(1, 10))}
    if (not _text(raw, 4096) or ".." in windows.parts or ":" in raw[len(windows.drive):]
            or raw.startswith(("\\\\?\\", "\\\\.\\"))
            or any(part.rstrip(". ").split(".", 1)[0].upper() in reserved for part in windows.parts)
            or windows.drive and not windows.is_absolute()):
        raise AttachError("practice-profile-invalid")
    try:
        root = Path(root).resolve()
        base = root / ".local"
        path = (root / value).resolve()
        if (base.resolve() != base or not path.is_relative_to(base)
                or path == base or path.suffix.lower() != ".json"):
            raise AttachError("practice-profile-invalid")
    except (OSError, ValueError, RuntimeError):
        raise AttachError("practice-profile-invalid") from None
    return path


def resolve_binary(root=ROOT):
    """Only fixed built paths, debug first; never search PATH or accept profile argv."""
    root = Path(root).resolve()
    for build in ("debug", "release"):
        path = root / "target" / build / "coinpoker.exe"
        resolved = path.resolve()
        # Refuse redirected targets, including junctions to other checkout files.
        if resolved != path or not resolved.is_relative_to(root):
            raise AttachError("native-binary-unsafe")
        if path.is_file():
            return path
    raise AttachError("native-binary-missing")


@dataclass(frozen=True)
class AttachmentRule:
    user_scope: str
    selector_exe: str
    selector_title_regex: str

    def document(self):
        return {"format": 1, "version": 1, "user_scope": self.user_scope,
                "selector_exe": self.selector_exe, "selector_title_regex": self.selector_title_regex}

    def matches(self, window):
        title_rule = _TITLE_RULES.get(self.selector_title_regex)
        return (window.exe_name.translate(_EXE_CASE) == self.selector_exe.translate(_EXE_CASE)
                and title_rule is not None and isinstance(window.title, str)
                and title_rule.match(window.title) is not None
                and window.on_screen is True and window.width > 0 and window.height > 0)


BUILTIN_RULE = AttachmentRule(USER_SCOPE, SELECTOR_EXE, SELECTOR_TITLE_REGEX)
CONFIRMED_GAME_WINDOW_RULE = AttachmentRule(USER_SCOPE, SELECTOR_EXE, CONFIRMED_GAME_TITLE_REGEX)


def validate_profile(value):
    """Accept only the default or explicitly persisted, user-confirmed OS rule."""
    expected = BUILTIN_RULE.document()
    if (not isinstance(value, dict) or set(value) != set(expected)
            or type(value["format"]) is not int or value["format"] != 1
            or type(value["version"]) is not int or value["version"] != 1):
        raise AttachError("practice-profile-invalid")
    # Existing private selectors retain their exact matching behavior.
    if value.get("user_scope") == "practice-six-max":
        value = {**value, "user_scope": USER_SCOPE}
    for rule in (BUILTIN_RULE, CONFIRMED_GAME_WINDOW_RULE):
        if value == rule.document():
            return rule
    raise AttachError("practice-profile-invalid")


def load_profile(path=DEFAULT_PROFILE, *, root=ROOT, required=False):
    """Missing optional file uses the user-provided built-in rule, without writes."""
    path = _private_path(path, root)
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_PROFILE_BYTES + 1)
    except FileNotFoundError:
        if required:
            raise AttachError("practice-profile-invalid") from None
        return BUILTIN_RULE
    except OSError:
        raise AttachError("practice-profile-invalid") from None
    if len(raw) > MAX_PROFILE_BYTES:
        raise AttachError("practice-profile-invalid")
    return validate_profile(_json(raw, "practice-profile-invalid"))


@dataclass(frozen=True)
class WindowMetadata:
    process_id: int
    hwnd: str
    exe_name: str = field(repr=False)
    title: str | None = field(repr=False)
    on_screen: bool
    width: int
    height: int

    def private_record(self):
        return dict(vars(self))


@dataclass(frozen=True)
class WindowListing:
    applications: tuple = field(default=(), repr=False)
    windows: tuple = field(default=(), repr=False)


def select_exact(listing, pid, hwnd):
    """Manual selection only; a saved broad rule is not session approval."""
    if (not isinstance(listing, WindowListing) or type(pid) is not int or pid <= 0
            or not isinstance(hwnd, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", hwnd)):
        raise AttachError("practice-profile-mismatch")
    matches = [window for window in listing.windows
               if window.process_id == pid and int(window.hwnd, 16) == int(hwnd, 16)
               and window.exe_name.translate(_EXE_CASE) == SELECTOR_EXE.translate(_EXE_CASE)
               and window.on_screen and window.width > 0 and window.height > 0
               and isinstance(window.title, str) and window.title]
    if len(matches) != 1:
        raise AttachError("practice-profile-mismatch")
    return matches[0]


def same_exact_source(before, after):
    return (before.process_id == after.process_id and before.hwnd == after.hwnd
            and before.exe_name.translate(_EXE_CASE) == after.exe_name.translate(_EXE_CASE)
            and before.title == after.title)


def parse_window_listing(raw):
    """Parse complete schema 1/2 JSONL; unknown fields/events never become selectors."""
    if isinstance(raw, str):
        if len(raw) > MAX_LIST_BYTES:
            raise AttachError("window-list-too-large")
        try:
            raw = raw.encode("utf-8")
        except UnicodeError:
            raise AttachError("window-list-invalid") from None
    if not isinstance(raw, bytes):
        raise AttachError("window-list-invalid")
    if len(raw) > MAX_LIST_BYTES:
        raise AttachError("window-list-too-large")
    lines = raw.splitlines(keepends=True)
    if len(lines) > MAX_LIST_RECORDS:
        raise AttachError("window-list-too-large")
    applications, windows, handles = {}, [], set()
    for line in lines:
        if len(line) > MAX_LIST_RECORD_BYTES:
            raise AttachError("window-list-too-large")
        if not line.endswith(b"\n") or not line.strip():
            raise AttachError("window-list-invalid")
        record = _json(line, "window-list-invalid")
        if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
                or record["schema_version"] not in (1, 2)):
            raise AttachError("window-list-invalid")
        event = record.get("event")
        if event == "status" and set(record) == {"schema_version", "event", "state", "reason"}:
            raise AttachError("window-list-unavailable")
        if event not in ("application", "window") or set(record) != {"schema_version", "event", event}:
            raise AttachError("window-list-invalid")
        item = record[event]
        expected = ({"process_id", "exe_name"} if event == "application" else
                    {"process_id", "exe_name", "hwnd", "title", "on_screen", "width", "height"})
        if (not isinstance(item, dict) or set(item) != expected
                or not _integer(item["process_id"], 0xffffffff) or not item["process_id"]
                or not _exe(item["exe_name"])):
            raise AttachError("window-list-invalid")
        pid, exe = item["process_id"], item["exe_name"].translate(_EXE_CASE)
        if event == "application":
            if pid in applications:
                raise AttachError("window-list-invalid")
            applications[pid] = exe
            continue
        hwnd = item["hwnd"]
        if record["schema_version"] == 1 and _integer(hwnd, 0xffffffffffffffff):
            hwnd = hex(hwnd)
        if (not isinstance(hwnd, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", hwnd)
                or int(hwnd, 16) == 0 or int(hwnd, 16) in handles
                or item["title"] is not None and not _title(item["title"])
                or type(item["on_screen"]) is not bool
                or not _integer(item["width"], 0xffffffff) or not _integer(item["height"], 0xffffffff)):
            raise AttachError("window-list-invalid")
        handles.add(int(hwnd, 16))
        windows.append(WindowMetadata(pid, hex(int(hwnd, 16)), item["exe_name"],
                                      item["title"], item["on_screen"], item["width"], item["height"]))
    if any(applications.get(window.process_id) != window.exe_name.translate(_EXE_CASE) for window in windows):
        raise AttachError("window-list-invalid")
    return WindowListing(tuple(sorted(applications.items())), tuple(windows))


def list_windows(*, root=ROOT):
    """Bounded metadata subprocess, no pixels/model/endpoint and no inherited overrides."""
    binary = resolve_binary(root)
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("COINPOKER_")}
    try:
        process = subprocess.Popen([str(binary), "--list-windows"], cwd=Path(root).resolve(),
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, shell=False)
    except OSError:
        raise AttachError("window-list-failed") from None
    output = bytearray()
    finished, failed = threading.Event(), threading.Event()
    deadline = time.monotonic() + LIST_TIMEOUT_SECONDS

    def read():
        try:
            while len(output) <= MAX_LIST_BYTES:
                chunk = process.stdout.read(min(8192, MAX_LIST_BYTES + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
        except (OSError, ValueError, TypeError):
            failed.set()
        finally:
            finished.set()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        if not finished.wait(LIST_TIMEOUT_SECONDS):
            raise AttachError("window-list-timeout")
        if len(output) > MAX_LIST_BYTES:
            raise AttachError("window-list-too-large")
        if failed.is_set():
            raise AttachError("window-list-failed")
        try:
            status = process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise AttachError("window-list-timeout") from None
        if status != 0:
            raise AttachError("window-list-failed")
        return parse_window_listing(bytes(output))
    finally:
        # Only this short-lived listing child is owned here, never a listener/feed.
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass
        reader.join(timeout=1)
        if not reader.is_alive():
            process.stdout.close()


@dataclass(frozen=True)
class AttachResult:
    code: str
    _config: tuple = field(default=(), repr=False)
    key: tuple | None = field(default=None, repr=False)
    _candidates: tuple = field(default=(), repr=False)

    @property
    def ok(self):
        return self.code == "ready"

    @property
    def message(self):
        return MESSAGES[self.code]

    @property
    def config(self):
        return dict(self._config) if self.ok else None

    @property
    def private_diagnostics(self):
        return {"candidates": [window.private_record() for window in self._candidates]}

    def public_status(self):
        return {"code": self.code, "message": self.message}


class PracticeAttachment:
    """Selection only; a supervisor owns the sole LiveFeed and retry/backoff policy."""

    def __init__(self, path=DEFAULT_PROFILE, *, root=ROOT, require_profile=False):
        self.path, self.root = path, Path(root).resolve()
        self.require_profile = require_profile

    def select(self, listing=None):
        candidates = listing.windows[:MAX_DIAGNOSTIC_CANDIDATES] if isinstance(listing, WindowListing) else ()
        try:
            # Revalidate the rule and current metadata, never pixels or seating.
            rule = load_profile(self.path, root=self.root, required=self.require_profile)
            binary = resolve_binary(self.root)
            if listing is None:
                listing = list_windows(root=self.root)
            if not isinstance(listing, WindowListing):
                raise AttachError("window-list-invalid")
            relevant = tuple(window for window in listing.windows
                             if window.exe_name.translate(_EXE_CASE) == rule.selector_exe.translate(_EXE_CASE)
                             or isinstance(window.title, str) and _NLH_TITLE.match(window.title) is not None)
            candidates = (relevant or listing.windows)[:MAX_DIAGNOSTIC_CANDIDATES]
            matches = [window for window in listing.windows if rule.matches(window)]
            if not matches:
                raise AttachError("practice-target-absent")
            if len(matches) != 1:
                raise AttachError("practice-target-ambiguous")
            window = matches[0]
            # Native title matching is substring-only. Metadata enforces the
            # anchored digit rule; PID/HWND isolate the window without a size pin.
            config = {"binary": binary.relative_to(self.root).as_posix(), "exe_name": window.exe_name,
                      "pid": window.process_id, "window_hwnd": window.hwnd,
                       "window_title": "NLH" if rule == BUILTIN_RULE else "CoinPoker", **RECORDING}
            key = (window.exe_name.translate(_EXE_CASE), window.process_id, window.hwnd)
            return AttachResult("ready", tuple(config.items()), key, candidates)
        except AttachError as error:
            return AttachResult(error.code, _candidates=candidates)
        except OSError:
            return AttachResult("window-list-failed", _candidates=candidates)


def persist_profile(value, listing, path=DEFAULT_PROFILE, *, confirmed=False, root=ROOT):
    """Save an optional receipt of the user-declared rule; never called by select().

    No ephemeral identity, title, size, ROI, argv, or perception calibration is
    saved. No lobby/cash distinction is claimed. The rule cannot be overwritten.
    """
    if confirmed is not True:
        raise AttachError("practice-profile-confirmation-required")
    rule = validate_profile(value)
    path = _private_path(path, root)
    if not isinstance(listing, WindowListing):
        raise AttachError("window-list-invalid")
    if sum(rule.matches(window) for window in listing.windows) != 1:
        raise AttachError("practice-profile-mismatch")
    document = json.dumps(rule.document(), sort_keys=True, separators=(",", ":")) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(document.encode("utf-8"))
    except FileExistsError:
        raise AttachError("practice-profile-exists") from None
    except OSError:
        raise AttachError("practice-profile-invalid") from None
    return rule
