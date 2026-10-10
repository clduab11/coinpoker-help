#!/usr/bin/env python3
"""Loopback Laya Vision server for coinpoker-help (the sole live perception backend).

Subcommands:
  serve  (default)  serve the dashboard, then verify/load the pinned model asynchronously
  fetch             download the pinned base checkpoint (HF revision) into HF_HOME, then verify
  verify            check runtime package versions, laya commit and every pinned file's SHA-256

API (loopback only, concurrent HTTP with one GPU admission slot):
  GET  /                 read-only local dashboard
  GET  /api/state        bounded sanitized Rust-feed/model status snapshot
  GET  /api/reference    locally bundled researched study reference, not live recommendations
  GET  /v1/models        -> {"object":"list","data":[{"id": alias, "object":"model", "meta":{...}}]}
  POST /v1/laya/predict  -> body {model, pass, note, layout, glyph_style?, images_png_b64:[...],
                                  questions:{qid:{type, instructions, criteria?}}}
       layout "full"/"slots": every image goes into one Laya state (one 64-token tile each).
       layout "glyphs": exactly one amount crop; scripts/laya_prep.segment_glyphs splits it into
       n <= 8 glyph images; only g1..gn are answered; the response carries segments {n, overflow}.
       response {model, pass, answers:{qid:{type, choice?, probabilities?, noul?, confidence,
                 truncated}}, segments?, timing_ms:{decode, prep, predict}}

Hygiene: never logs or echoes request content; errors are {"error": "<code>"}; bounded body,
image and question limits; images are never written to disk. torch / laya / PIL / numpy are
imported lazily so the request validation stays stdlib-only and testable.
"""

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
import re
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import laya_dashboard as dashboard

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
PINS_PATH = os.path.join(SCRIPTS, "laya-pins.json")

HOST = "127.0.0.1"
MAX_BODY = 8 * 1024 * 1024
MAX_QUESTIONS = 64
MAX_OPTIONS = 64
MAX_IMAGES = 8
MAX_INSTRUCTIONS = 2000
MAX_OPTION_TEXT = 200
MAX_NOTE = 500
MAX_IMAGE_PIXELS = 4096 * 4096
MAX_GLYPHS = 8
ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
LAYOUTS = ("full", "slots", "glyphs")
GLYPH_STYLES = ("white", "gold")
PNG_SIG = b"\x89PNG\r\n\x1a\n"
SOCKET_TIMEOUT = 10
PORT = 18090
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")


class RequestError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def load_pins(path=PINS_PATH):
    with open(path, encoding="utf-8") as f:
        pins = json.load(f)
    if pins.get("format") != 1:
        raise ValueError("unsupported laya-pins format")
    return pins


def png_size(data):
    """(width, height) from a PNG header without decoding; raises RequestError for anything else."""
    if len(data) < 24 or data[:8] != PNG_SIG or data[12:16] != b"IHDR":
        raise RequestError(400, "invalid-image")
    w, h = struct.unpack(">II", data[16:24])
    if w == 0 or h == 0 or w * h > MAX_IMAGE_PIXELS:
        raise RequestError(400, "image-too-large" if w * h > MAX_IMAGE_PIXELS else "invalid-image")
    return w, h


def validate_request(body, alias):
    """Validate a decoded JSON body. Returns (pass_id, note, layout, style, [png bytes], questions)."""
    if not isinstance(body, dict):
        raise RequestError(400, "malformed")
    if body.get("model") != alias:
        raise RequestError(404, "unknown-model")
    pid = body.get("pass")
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise RequestError(400, "malformed")
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise RequestError(400, "malformed")
    layout = body.get("layout")
    if layout not in LAYOUTS:
        raise RequestError(400, "malformed")
    style = body.get("glyph_style")
    if layout == "glyphs" and style not in GLYPH_STYLES:
        raise RequestError(400, "malformed")
    imgs = body.get("images_png_b64")
    if not isinstance(imgs, list) or not 1 <= len(imgs) <= MAX_IMAGES:
        raise RequestError(400, "malformed")
    if layout in ("full", "glyphs") and len(imgs) != 1:
        raise RequestError(400, "malformed")
    raw = []
    for s in imgs:
        if not isinstance(s, str):
            raise RequestError(400, "malformed")
        try:
            data = base64.b64decode(s.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError, ValueError):
            raise RequestError(400, "invalid-image")
        png_size(data)
        raw.append(data)
    qs = body.get("questions")
    if not isinstance(qs, dict) or not 1 <= len(qs) <= MAX_QUESTIONS:
        raise RequestError(400, "malformed")
    out = {}
    for qid, q in qs.items():
        if not isinstance(qid, str) or not ID_RE.match(qid) or not isinstance(q, dict):
            raise RequestError(400, "malformed")
        typ = q.get("type")
        ins = q.get("instructions")
        if typ not in ("choice", "noul") or not isinstance(ins, str) or not 0 < len(ins) <= MAX_INSTRUCTIONS:
            raise RequestError(400, "malformed")
        d = {"type": typ, "instructions": ins}
        if typ == "choice":
            crit = q.get("criteria")
            if (isinstance(crit, list) and crit and all(isinstance(x, list) and len(x) == 2 for x in crit)):
                # ordered [label, description] pairs: the option order is part of Laya's input
                labels = [x[0] for x in crit]
                if len(set(map(str, labels))) != len(labels):
                    raise RequestError(400, "malformed")
                crit = {x[0]: x[1] for x in crit}
            if isinstance(crit, dict):
                items = list(crit.items())
                ok = all(isinstance(k, str) and isinstance(v, str) and 0 < len(k) <= MAX_OPTION_TEXT
                         and len(v) <= MAX_OPTION_TEXT for k, v in items)
            elif isinstance(crit, list):
                items = crit
                ok = all(isinstance(k, str) and 0 < len(k) <= MAX_OPTION_TEXT for k in items)
            else:
                ok, items = False, []
            if not ok or not 2 <= len(items) <= MAX_OPTIONS:
                raise RequestError(400, "malformed")
            d["criteria"] = crit
        out[qid] = d
    if layout == "glyphs" and set(out) - {"g%d" % k for k in range(1, MAX_GLYPHS + 1)}:
        raise RequestError(400, "malformed")
    return pid, note, layout, style, raw, out


def shape_answers(result, questions):
    """Reduce laya answers to the wire format (no provenance, no action block)."""
    out = {}
    for qid in questions:
        a = result["answers"][qid]
        r = {"type": a["type"], "confidence": a.get("confidence"), "truncated": bool(a.get("truncated"))}
        if a["type"] == "choice":
            r["choice"] = a["choice"]
            r["probabilities"] = a["probabilities"]
        else:
            r["noul"] = a["noul"]
        out[qid] = r
    return out


class Engine:
    """Lazy GPU side: decode, prepare, predict. Replaced by a fake in tests."""

    def __init__(self, pins, batch_size=32):
        self.pins = pins
        self.batch_size = batch_size
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        import warnings

        warnings.filterwarnings("ignore")
        sys.path.insert(0, SCRIPTS)
        import laya  # noqa: F401
        from laya.calibration import Calibration
        import laya_prep

        self.prep = laya_prep
        ft = pins["model"]["finetuned"]
        path = os.path.join(REPO, ft["path"])
        self.agent = laya.load_vlm(path, device="cuda", dtype=pins["server"].get("dtype", "bf16"))
        cal = ft.get("calibration_file")
        self.calibration = Calibration.load(os.path.join(path, cal)) if cal else None

    def decode(self, raw):
        import io
        from PIL import Image

        out = []
        for data in raw:
            im = Image.open(io.BytesIO(data))
            im.load()
            out.append(im.convert("RGB"))
        return out

    def predict(self, images, note, questions):
        import torch

        res = self.agent.predict({"images": images, "note": note}, questions, n_permutations=1,
                                 batch_size=self.batch_size, calibration=self.calibration)
        torch.cuda.synchronize()
        return res


def handle_predict(engine, alias, body_bytes, log_fn=None):
    """Pure request handling (testable with a fake engine). Returns (status, payload dict)."""
    try:
        body = json.loads(body_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return 400, {"error": "malformed"}
    try:
        pid, note, layout, style, raw, questions = validate_request(body, alias)
    except RequestError as e:
        return e.status, {"error": e.code}
    t0 = time.perf_counter()
    try:
        images = engine.decode(raw)
    except Exception:
        return 400, {"error": "invalid-image"}
    t1 = time.perf_counter()
    segments = None
    if layout == "glyphs":
        glyphs, info = engine.prep.segment_glyphs(images[0], style, MAX_GLYPHS)
        segments = {"n": int(info["n"]), "overflow": bool(info["overflow"])}
        images = glyphs
        questions = {q: d for q, d in questions.items() if int(q[1:]) <= len(glyphs)}
    t2 = time.perf_counter()
    answers = {}
    if images and questions:
        try:
            result = engine.predict(images, note, questions)
        except Exception:
            return 500, {"error": "predict-failed"}
        answers = shape_answers(result, questions)
    t3 = time.perf_counter()
    timing = {"decode": round((t1 - t0) * 1000, 1), "prep": round((t2 - t1) * 1000, 1),
              "predict": round((t3 - t2) * 1000, 1)}
    payload = {"model": alias, "pass": pid, "answers": answers, "timing_ms": timing}
    if segments is not None:
        payload["segments"] = segments
    if log_fn:
        log_fn({"utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"), "pass": pid,
                "timing_ms": timing, "segments": segments,
                "answers": {q: {"v": a.get("choice", a.get("noul")),
                                "p": (a["probabilities"][a["choice"]] if a["type"] == "choice" else a["noul"]),
                                "truncated": a["truncated"]} for q, a in answers.items()}})
    return 200, payload


class Service:
    def __init__(self, alias, meta=None, engine=None, log_fn=None):
        self.alias, self.meta, self.engine, self.log_fn = alias, meta or {}, engine, log_fn
        self.inference = threading.Lock()
        self.state = dashboard.DashboardState(alias, self.meta.get("checkpoint"))
        if engine is not None:
            self.state.set_model("ready", calibrated=self.meta.get("calibrated", False))

    def predict(self, body):
        if self.engine is None:
            return 503, {"error": "model-not-ready"}
        if not self.inference.acquire(blocking=False):
            return 503, {"error": "inference-busy"}
        self.state.set_busy(True)
        try:
            return handle_predict(self.engine, self.alias, body, self.log_fn)
        except Exception:
            return 500, {"error": "predict-failed"}
        finally:
            self.state.set_busy(False)
            self.inference.release()


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, address, handler, max_requests=16):
        self.requests = threading.BoundedSemaphore(max_requests)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.requests.acquire(blocking=False):
            try:
                request.settimeout(SOCKET_TIMEOUT)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.requests.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.requests.release()

    def handle_error(self, request, client_address):
        # Client disconnects must not dump request details or backend exceptions.
        return


def make_handler(engine, alias, meta, log_fn, service=None):
    service = service or Service(alias, meta, engine, log_fn)

    class Handler(BaseHTTPRequestHandler):
        server_version = "laya-server"
        sys_version = ""
        timeout = SOCKET_TIMEOUT

        def log_message(self, *args):  # never log requests
            return

        def _send_bytes(self, status, data, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass

        def _send(self, status, payload):
            self._send_bytes(status, json.dumps(payload, allow_nan=False).encode("utf-8"), "application/json")

        def _discard_body(self):
            if self.headers.get("Transfer-Encoding"):
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return
            if 0 < n <= MAX_BODY:
                self.rfile.read(n)

        def _local_request(self):
            port = self.server.server_address[1]
            hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
            supplied = self.headers.get_all("Host", [])
            origins = self.headers.get_all("Origin", [])
            if (len(supplied) != 1 or supplied[0].lower() not in hosts or len(origins) > 1
                    or origins and origins[0].lower() not in {"http://" + h for h in hosts}):
                if self.command == "POST":
                    self._discard_body()
                self._send(403, {"error": "local-origin-required"})
                return False
            return True

        def do_GET(self):
            if not self._local_request():
                return
            if self.path == "/v1/models":
                if service.engine is None:
                    self._send(503, {"error": "model-not-ready"})
                else:
                    self._send(200, {"object": "list", "data": [{"id": alias, "object": "model", "meta": service.meta}]})
            elif self.path == "/api/state":
                self._send(200, service.state.snapshot())
            elif self.path == "/api/reference":
                try:
                    reference = dashboard.references()
                except (OSError, ValueError):
                    self._send(503, {"error": "reference-unavailable"})
                    return
                self._send(200, reference)
            elif self.path == "/favicon.ico":
                self._send_bytes(204, b"", "image/x-icon")
            elif self.path in ASSETS:
                filename, content_type = ASSETS[self.path]
                try:
                    data = (Path(SCRIPTS) / "dashboard" / filename).read_bytes()
                except OSError:
                    self._send(503, {"error": "dashboard-assets-unavailable"})
                    return
                self._send_bytes(200, data, content_type)
            else:
                self._send(404, {"error": "not-found"})

        def do_POST(self):
            if not self._local_request():
                return
            if self.path != "/v1/laya/predict":
                self._discard_body()
                self._send(404, {"error": "not-found"})
                return
            try:
                n = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                n = -1
            if n < 0:
                self._send(411, {"error": "length-required"})
                return
            if n > MAX_BODY:
                self._send(413, {"error": "body-too-large"})
                return
            if self.headers.get("Transfer-Encoding"):
                self._send(400, {"error": "malformed"})
                return
            body = self.rfile.read(n)
            if len(body) != n:
                self._send(400, {"error": "malformed"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                self._send(415, {"error": "json-required"})
                return
            status, payload = service.predict(body)
            self._send(status, payload)

    return Handler


# ------------------------------------------------------------------------------------------------
# verify / fetch
# ------------------------------------------------------------------------------------------------


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_dir(pins):
    m = pins["model"]
    hf_home = os.environ.get("HF_HOME") or os.path.join(REPO, m["hf_home"])
    return os.path.join(hf_home, "hub", "models--" + m["repository"].replace("/", "--"), "snapshots", m["revision"])


def verify(pins, check_runtime=True):
    problems = []
    if check_runtime:
        from importlib import metadata

        for pkg, ver in pins["runtime"]["packages"].items():
            try:
                got = metadata.version(pkg)
            except metadata.PackageNotFoundError:
                got = None
            if got != ver:
                problems.append("package %s: %s != %s" % (pkg, got, ver))
        try:
            durl = json.loads(metadata.distribution("laya").read_text("direct_url.json") or "{}")
            commit = (durl.get("vcs_info") or {}).get("commit_id")
        except Exception:
            commit = None
        if commit != pins["runtime"]["laya"]["commit"]:
            problems.append("laya commit %s != %s" % (commit, pins["runtime"]["laya"]["commit"]))
    snap = snapshot_dir(pins)
    for f in pins["model"]["files"]:
        p = os.path.join(snap, f["path"])
        if not os.path.exists(p):
            problems.append("missing base file %s" % f["path"])
        elif os.path.getsize(p) != f["size"] or sha256_file(p) != f["sha256"]:
            problems.append("hash mismatch base %s" % f["path"])
    ft = pins["model"].get("finetuned")
    if not ft:
        problems.append("no fine-tuned checkpoint pinned")
    else:
        d = os.path.join(REPO, ft["path"])
        for f in ft["files"]:
            p = os.path.join(d, f["path"])
            if not os.path.exists(p):
                problems.append("missing fine-tuned file %s" % f["path"])
            elif os.path.getsize(p) != f["size"] or sha256_file(p) != f["sha256"]:
                problems.append("hash mismatch fine-tuned %s" % f["path"])
    return problems


def cmd_fetch(pins):
    from huggingface_hub import snapshot_download

    m = pins["model"]
    os.environ.setdefault("HF_HOME", os.path.join(REPO, m["hf_home"]))
    snapshot_download(m["repository"], revision=m["revision"])
    return cmd_verify(pins)


def cmd_verify(pins):
    problems = verify(pins)
    print(json.dumps({"event": "laya-verify", "ok": not problems, "problems": problems}))
    return 0 if not problems else 2


def cmd_serve(pins, answers_log, batch_size, dashboard_only=False, live_config=None):
    srv = pins["server"]
    if int(srv["port"]) != PORT:
        raise ValueError("Laya dashboard/model service requires port 18090; no alternate-port fallback")
    log_fn = None
    fh = None
    if answers_log:
        path = dashboard.local_path(answers_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = path.open("a", encoding="utf-8")
        log_lock = threading.Lock()

        def log_fn(rec):
            with log_lock:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
    ft = pins["model"].get("finetuned") or {}
    meta = {"checkpoint": ft.get("path"), "base_revision": pins["model"]["revision"],
            "calibrated": bool(ft.get("calibration_file")),
            "quality_gate": "failed", "seated_advice_supported": False}
    service = Service(srv["alias"], meta, log_fn=log_fn)
    httpd = BoundedHTTPServer((HOST, PORT), make_handler(None, srv["alias"], meta, log_fn, service))
    feed = None

    def initialize():
        service.state.set_model("loading")
        try:
            problems = verify(pins)
            if problems:
                service.state.set_model("failed", "verification-failed")
                print(json.dumps({"event": "laya-verify", "ok": False, "problems": problems}), flush=True)
                return
            engine = Engine(pins, batch_size=batch_size or srv.get("batch_size", 32))
            from PIL import Image

            warm = Image.new("RGB", (64, 64), (200, 30, 30))
            t0 = time.perf_counter()
            engine.predict([warm], "warm-up", {"c": {"type": "choice", "instructions": "What colour is the image?",
                                                      "criteria": ["red", "blue", "green"]}})
            warm_ms = round((time.perf_counter() - t0) * 1000, 1)
            service.engine = engine
            service.state.set_model("ready", calibrated=meta["calibrated"])
            print(json.dumps({"event": "model-ready", "alias": srv["alias"], "warmup_ms": warm_ms,
                              "quality_gate": "failed", "advice_ready": False}), flush=True)
        except Exception:
            service.engine = None
            service.state.set_model("failed", "model-initialization-failed")
            print(json.dumps({"event": "model-failed", "error": "model-initialization-failed"}), flush=True)

    print(json.dumps({"event": "ready", "host": HOST, "port": PORT, "alias": srv["alias"],
                      "dashboard": True, "advice_ready": False}), flush=True)
    if not dashboard_only:
        threading.Thread(target=initialize, daemon=True).start()
    if live_config:
        try:
            feed = dashboard.LiveFeed(live_config, service.state)
        except (OSError, ValueError):
            service.state.end_stream("invalid-live-config")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if feed is not None:
            feed.stop()
        httpd.server_close()
        if fh is not None:
            fh.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?", default="serve", choices=["serve", "fetch", "verify"])
    ap.add_argument("--answers-log", default=None, help="JSONL of answers and timings (no image data)")
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--dashboard-only", action="store_true", help="serve read-only Monitor/Reference without loading a model")
    ap.add_argument("--live-config", help="explicit operator-owned passive native feed profile under .local")
    a = ap.parse_args(argv)
    pins = load_pins()
    if a.command == "verify":
        return cmd_verify(pins)
    if a.command == "fetch":
        return cmd_fetch(pins)
    return cmd_serve(pins, a.answers_log, a.batch_size, a.dashboard_only, a.live_config)


if __name__ == "__main__":
    sys.exit(main())
