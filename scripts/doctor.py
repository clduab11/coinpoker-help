#!/usr/bin/env python3
"""Windows diagnostics for the Laya Vision runtime. Only generated color PNGs go to loopback.

--list-windows reads metadata only. Local SHA256 checks need no network.
--offline skips HTTP; no image or report is saved by default.
"""

import argparse
import base64
import ctypes
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib

PINS_PATH = Path(__file__).with_name("laya-pins.json")
DEFAULT_ENDPOINT = "http://127.0.0.1:18090/v1/laya/predict"
LIMIT = 1024 * 1024
PROBE_TIMEOUT_SECS = 120
PROBE_QUESTION = {"type": "choice", "instructions": "What is the dominant colour of the image?",
                  "criteria": {"red": "mostly red", "blue": "mostly blue"}}


def load_pins(path=PINS_PATH):
    """Pins are read lazily so a missing or broken pin file is a failed check, not an import crash."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def loopback_endpoint(endpoint):
    url = urllib.parse.urlsplit(endpoint)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("invalid endpoint")
    try:
        loopback = ipaddress.ip_address(url.hostname).is_loopback
    except ValueError:
        loopback = url.hostname.lower() == "localhost"
    if not loopback:
        raise ValueError("doctor refuses remote endpoints")
    if url.port != 18090:
        raise ValueError("Laya service requires port 18090; retired or alternate product ports are refused")
    if not url.path.endswith("/v1/laya/predict"):
        raise ValueError("endpoint must end with /v1/laya/predict")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, body=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=PROBE_TIMEOUT_SECS) as response:
        data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("oversized response")
        return json.loads(data)


def color_png(rgb):
    """64x64 synthetic image; no screenshot or filesystem input."""
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    raw = (b"\0" + bytes(rgb) * 64) * 64
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def probe_body(model, rgb):
    return {"model": model, "pass": "doctor_probe", "note": "Generated colour test image.", "layout": "full",
            "images_png_b64": [base64.b64encode(color_png(rgb)).decode("ascii")],
            "questions": {"dominant_color": PROBE_QUESTION}}


def model_available(response, model):
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        return False
    return any(isinstance(entry, dict) and entry.get("id") == model for entry in response["data"])


def verify_probe(response, expected):
    try:
        answer = response["answers"]["dominant_color"]
        return answer["type"] == "choice" and answer["choice"] == expected and answer.get("truncated") is False
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_files(root, files, what, allowed_root=None):
    root = root.resolve()
    allowed_root = (allowed_root or root).resolve()
    if not files:
        raise ValueError("no pinned %s files" % what)
    for artifact in files:
        relative = Path(artifact["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("escaping %s artifact path" % what)
        path = (root / relative).resolve()
        if not path.is_relative_to(allowed_root) or not path.is_file() or path.stat().st_size != artifact["size"]:
            raise ValueError("missing, wrong-sized, or escaping %s artifact" % what)
        if sha256_file(path) != artifact["sha256"]:
            raise ValueError("%s artifact SHA256 mismatch" % what)


def check_model_files(repo, pins):
    """Base checkpoint snapshot (HF revision) and the local fine-tuned checkpoint, by size and SHA-256."""
    model = pins["model"]
    hf_home = repo / model["hf_home"]
    hub = hf_home / "hub"
    cache = hub / ("models--" + model["repository"].replace("/", "--"))
    snap = cache / "snapshots" / model["revision"]
    # HF uses both repository-local blobs and a shared hub/blobs content store.
    _check_files(snap, model["files"], "base model", allowed_root=hub)
    ft = model.get("finetuned")
    if not ft:
        raise ValueError("no fine-tuned checkpoint pinned")
    _check_files(repo / ft["path"], ft["files"], "fine-tuned model")


def runtime_python(root, pins):
    exe = root / pins["runtime"]["env_prefix"] / ("python.exe" if os.name == "nt" else "bin/python")
    if not exe.is_file():
        raise ValueError("Laya runtime environment missing")
    return exe


RUNTIME_PROBE = (
    "import json, importlib.metadata as m\n"
    "out = {}\n"
    "for p in %r:\n"
    "    try: out[p] = m.version(p)\n"
    "    except m.PackageNotFoundError: out[p] = None\n"
    "try:\n"
    "    out['laya_commit'] = json.loads(m.distribution('laya').read_text('direct_url.json') or '{}').get('vcs_info', {}).get('commit_id')\n"
    "except Exception: out['laya_commit'] = None\n"
    "print(json.dumps(out))\n"
)

CUDA_PROBE = ("import json, torch\n"
              "ok = torch.cuda.is_available()\n"
              "print(json.dumps({'cuda': ok, 'name': torch.cuda.get_device_name(0) if ok else None}))\n")


def check_runtime(root, pins):
    exe = runtime_python(root, pins)
    packages = pins["runtime"]["packages"]
    result = run_command([str(exe), "-c", RUNTIME_PROBE % (list(packages),)], timeout=120)
    if result.returncode != 0:
        raise ValueError("runtime probe failed")
    found = json.loads(result.stdout.strip().splitlines()[-1])
    if any(found.get(p) != v for p, v in packages.items()):
        raise ValueError("runtime package versions differ from pins")
    if found.get("laya_commit") != pins["runtime"]["laya"]["commit"]:
        raise ValueError("laya commit differs from pin")
    return exe


def run_command(args, timeout=30, cwd=None):
    result = subprocess.run(args, capture_output=True, timeout=timeout, cwd=cwd, check=False)
    try:
        result.stdout = result.stdout.decode("utf-8", errors="strict")
        result.stderr = result.stderr.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("subprocess output is not UTF-8") from exc
    return result


def windows_build():
    return sys.getwindowsversion().build if platform.system() == "Windows" else None


def resource_detail(root):
    free_gib = shutil.disk_usage(root).free / (1024 ** 3)
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended", ctypes.c_ulonglong)]
    memory = MemoryStatus()
    memory.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise OSError("memory information unavailable")
    return f"{memory.total_phys / (1024 ** 3):.1f} GiB RAM; {free_gib:.1f} GiB free disk; informational only"


def metadata_records(output):
    apps, windows = [], []
    for line in output.splitlines():
        record = json.loads(line)
        if not isinstance(record, dict) or record.get("schema_version") != 2:
            raise ValueError("invalid metadata record")
        if record.get("event") == "application":
            item = record.get("application")
            if not isinstance(item, dict) or not isinstance(item.get("exe_name"), str) or not isinstance(item.get("process_id"), int):
                raise ValueError("invalid application metadata")
            apps.append(item)
        elif record.get("event") == "window":
            item = record.get("window")
            if not isinstance(item, dict) or not isinstance(item.get("exe_name"), str) or not isinstance(item.get("process_id"), int):
                raise ValueError("invalid window metadata")
            if not isinstance(item.get("hwnd"), str) or not re.fullmatch(r"0x[0-9a-fA-F]+", item["hwnd"]):
                raise ValueError("invalid HWND encoding")
            windows.append(item)
        else:
            raise ValueError("unexpected metadata event")
    return apps, windows


def matching_metadata(apps, windows, environ):
    exe = environ.get("COINPOKER_EXE_NAME")
    if not exe:
        return None, []
    pid = environ.get("COINPOKER_PID")
    hwnd = environ.get("COINPOKER_WINDOW_HWND")
    if pid is not None and (not pid.isdecimal() or not 0 < int(pid) <= 0xffffffff):
        raise ValueError("invalid configured PID")
    try:
        hwnd_number = (int(hwnd, 16) if hwnd.lower().startswith("0x") else int(hwnd, 10)) if hwnd is not None else None
    except ValueError as exc:
        raise ValueError("invalid configured HWND") from exc
    if hwnd_number is not None and hwnd_number <= 0:
        raise ValueError("invalid configured HWND")
    def owner(item):
        return item["exe_name"].casefold() == exe.casefold() and (pid is None or item["process_id"] == int(pid))
    present = any(owner(item) for item in apps + windows)
    candidates = [item for item in windows if owner(item) and
                  (hwnd_number is None or int(item["hwnd"], 16) == hwnd_number) and
                  item.get("on_screen") is True and item.get("width", 0) > 0 and item.get("height", 0) > 0]
    return present, candidates


def collect(root, binary, offline=False):
    checks = []
    def record(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})
    def outcome(name, ok, detail):
        record(name, "pass" if ok else "fail", detail)

    build = windows_build()
    supported = build is not None and build >= 18362
    outcome("windows_capture_os", supported, f"requires Windows 10 build 18362+; observed {platform.system()} build {build}")
    outcome("windows_x64", build is not None and platform.machine().lower() in ("amd64", "x86_64"),
            "pinned CUDA PyTorch wheels require Windows x64")
    if build is not None:
        try:
            record("host_resources", "pass", resource_detail(root))
        except OSError:
            record("host_resources", "blocked", "RAM/disk information unavailable")
    if (root / "Cargo.toml").is_file():
        try:
            rust = run_command(["rustc", "+1.95.0", "--version"], cwd=root)
            outcome("rust_toolchain", rust.returncode == 0 and rust.stdout.startswith("rustc 1.95.0 "), "expected Rust 1.95.0 for source checkout")
        except (OSError, subprocess.SubprocessError):
            record("rust_toolchain", "fail", "install rustup/Rust 1.95.0 to build from source")
    else:
        record("rust_toolchain", "info", "source-free candidate bundle uses its prebuilt executable; Rust is not required")

    try:
        pins = load_pins()
        alias = pins["server"]["alias"]
    except (OSError, ValueError, KeyError):
        pins, alias = None, "coinpoker-laya-vision"
        record("laya_pins", "fail", "scripts/laya-pins.json missing or invalid")
    if pins is not None:
        try:
            exe = check_runtime(root, pins)
            record("runtime_asset", "pass", "Laya Python environment matches pinned packages and laya commit")
            try:
                cuda = run_command([str(exe), "-c", CUDA_PROBE], timeout=120)
                info = json.loads(cuda.stdout.strip().splitlines()[-1]) if cuda.returncode == 0 else {}
                outcome("cuda_device", info.get("cuda") is True, "CUDA GPU visible to the pinned torch build; performance unmeasured")
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                record("cuda_device", "fail", "CUDA probe failed")
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
            record("runtime_asset", "fail", "Laya environment absent/invalid; run scripts/setup-windows.ps1")
            record("cuda_device", "blocked", "runtime unavailable")
        try:
            check_model_files(root, pins)
            record("model_files_sha256", "pass", "base and fine-tuned Laya checkpoints match pinned sizes/SHA256")
        except (OSError, ValueError, KeyError):
            record("model_files_sha256", "fail", "pinned artifacts absent or invalid; inspect pins/local checkpoint without automatic redownload or retraining")

    endpoint = os.environ.get("COINPOKER_VLM_ENDPOINT") or DEFAULT_ENDPOINT
    model = os.environ.get("COINPOKER_VLM_MODEL") or alias
    try:
        url = loopback_endpoint(endpoint)
        if offline:
            record("vlm_models", "blocked", "offline: no HTTP requests made")
            record("multimodal_api", "blocked", "offline: no synthetic-image requests made")
        else:
            models_url = urllib.parse.urlunsplit((url.scheme, url.netloc, url.path.removesuffix("laya/predict") + "models", "", ""))
            models = request_json(models_url)
            available = model_available(models, model)
            outcome("vlm_models", available, "GET /v1/models must list the exact configured local alias")
            if available:
                passed = all(verify_probe(request_json(endpoint, probe_body(model, rgb)), color)
                             for rgb, color in [((255, 0, 0), "red"), ((0, 0, 255), "blue")])
                outcome("multimodal_api", passed, "generated color PNGs only; API smoke check, not poker accuracy")
            else:
                record("multimodal_api", "blocked", "configured model unavailable")
    except (ValueError, KeyError, IndexError, TypeError, OSError, urllib.error.URLError):
        record("vlm_endpoint_or_api", "fail", "local endpoint unreachable, redirected, or invalid; response omitted for privacy")

    if not supported:
        record("capture_metadata", "blocked", "requires supported Windows capture OS")
        record("coinpoker_discovery", "blocked", "window metadata unavailable")
        return checks
    try:
        listing = run_command([str(binary), "--list-windows"], timeout=30, cwd=root)
        if listing.returncode != 0:
            raise ValueError("window enumeration failed")
        apps, windows = metadata_records(listing.stdout)
        record("capture_metadata", "pass", "process/window enumeration succeeded; pixel capture remains a physical gate")
        present, candidates = matching_metadata(apps, windows, os.environ)
        if present is None:
            record("coinpoker_discovery", "blocked", "calibrate COINPOKER_EXE_NAME from --list-windows")
        else:
            record("coinpoker_discovery", "pass" if present else "blocked",
                   "configured executable/process present" if present else "configured executable/process absent")
            for key, label in [("COINPOKER_LOBBY_TITLE", "lobby_metadata"),
                               ("COINPOKER_WINDOW_TITLE", "table_metadata")]:
                title = os.environ.get(key)
                matches = [item for item in candidates if title and title in (item.get("title") or "")]
                if label == "table_metadata":
                    lobby = os.environ.get("COINPOKER_LOBBY_TITLE")
                    matches = [item for item in matches if not lobby or lobby not in (item.get("title") or "")]
                record(label, "pass" if len(matches) == 1 else "blocked",
                       "one calibrated title match; no pixel classification" if len(matches) == 1 else
                       "calibrate title/open window; zero or multiple matches")
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        record("capture_metadata", "fail", "binary metadata enumeration failed or returned invalid schema")
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--offline", action="store_true", help="skip HTTP probes; local file hashes still run")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    binary = args.binary or root / "target/release/coinpoker.exe"
    checks = collect(root, binary, args.offline)
    report = {"format": 2, "event": "doctor", "perception": "laya-vision", "checks": checks,
              "screenshots_captured": False, "screenshots_saved": False, "physical_acceptance": False}
    print(json.dumps(report, indent=2))
    expected_offline_skips = {"vlm_models", "multimodal_api"} if args.offline else set()
    return 0 if all(c["status"] in ("pass", "info") or
                    (c["check"] in expected_offline_skips and c["status"] == "blocked")
                    for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
