import importlib.util
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from unittest.mock import patch
import zlib

SPEC = importlib.util.spec_from_file_location("doctor", Path(__file__).resolve().parents[1] / "doctor.py")
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)


class DoctorTests(unittest.TestCase):
    def test_only_loopback_laya_endpoint_without_credentials_or_redirects(self):
        for host in ["127.0.0.1", "localhost", "[::1]"]:
            doctor.loopback_endpoint("http://" + host + ":18090/v1/laya/predict")
        for url in ["https://example.com/v1/laya/predict", "http://localhost@evil.example/v1/laya/predict",
                    "file:///tmp/data", "http://127.0.0.1/v1/laya/predict?token=secret",
                    "http://127.0.0.1:18080/v1/chat/completions",
                    "http://127.0.0.1:18080/v1/laya/predict", "http://localhost:8080/v1/laya/predict",
                    "http://127.0.0.1:18091/v1/laya/predict"]:
            with self.assertRaises(ValueError):
                doctor.loopback_endpoint(url)
        self.assertIsNone(doctor.NoRedirect().redirect_request(None, None, 302, None, None, "https://evil.example"))

    def test_png_bytes_are_generated_color_not_external_input(self):
        png = doctor.color_png((255, 0, 0))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        length = struct.unpack(">I", png[33:37])[0]
        self.assertEqual(png[37:41], b"IDAT")
        pixels = zlib.decompress(png[41:41 + length])
        self.assertEqual(pixels, (b"\0" + b"\xff\0\0" * 64) * 64)
        body = doctor.probe_body("local-model", (0, 0, 255))
        self.assertEqual((body["model"], body["layout"]), ("local-model", "full"))
        self.assertEqual(len(body["images_png_b64"]), 1)
        self.assertEqual(set(body["questions"]["dominant_color"]["criteria"]), {"red", "blue"})

    def test_success_requires_correct_image_dependent_answer(self):
        answer = {"answers": {"dominant_color": {"type": "choice", "choice": "red", "confidence": 0.9, "truncated": False}}}
        self.assertTrue(doctor.verify_probe(answer, "red"))
        self.assertFalse(doctor.verify_probe(answer, "blue"))
        answer["answers"]["dominant_color"]["truncated"] = True
        self.assertFalse(doctor.verify_probe(answer, "red"))

    def test_bad_api_shapes_fail_without_echoing_payloads(self):
        for response in [None, [], {}, {"answers": []}, {"answers": {"dominant_color": None}},
                         {"error": "data:image/png;base64,PRIVATE"}]:
            self.assertFalse(doctor.verify_probe(response, "red"))
        for response in [None, [], {}, {"data": None}, {"data": [None, "bad", 4]}]:
            self.assertFalse(doctor.model_available(response, "local-model"))
        self.assertTrue(doctor.model_available({"data": [{"id": "local-model"}]}, "local-model"))

    def make_model(self, root):
        files = {"model.safetensors": b"model", "vlm_agent_config.json": b"{}"}
        snap = root / "hf/hub/models--test--model/snapshots" / ("a" * 40)
        ft = root / "ft"
        for d in (snap, ft):
            d.mkdir(parents=True)
            for name, data in files.items():
                (d / name).write_bytes(data)
        listing = [{"path": n, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()]
        return {"model": {"repository": "test/model", "revision": "a" * 40, "hf_home": "hf", "files": listing,
                          "finetuned": {"path": "ft", "files": [dict(x) for x in listing]}}}

    def test_model_requires_pinned_size_and_sha256_for_base_and_finetuned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pins = self.make_model(root)
            doctor.check_model_files(root, pins)
            (root / "ft/model.safetensors").write_bytes(b"other")
            with self.assertRaises(ValueError):
                doctor.check_model_files(root, pins)
            (root / "ft/model.safetensors").write_bytes(b"model")
            del pins["model"]["finetuned"]
            with self.assertRaises(ValueError):
                doctor.check_model_files(root, pins)

    def test_hf_snapshot_links_may_resolve_only_into_the_configured_hub_cache(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / ".local") as directory:
            hub = Path(directory) / "hub"
            cache = hub / "repo"
            snapshot = cache / "snapshots" / "revision"
            snapshot.mkdir(parents=True)
            blobs = hub / "blobs"
            blobs.mkdir()
            blob = blobs / "sha"
            blob.write_bytes(b"test-model")
            outside = Path(directory) / "outside.bin"
            outside.write_bytes(b"test-model")
            artifact = {"path": "model.bin", "size": 10, "sha256": doctor.sha256_file(blob)}
            original = Path.resolve

            def resolve(path, *args, **kwargs):
                if path == snapshot / "model.bin":
                    return original(blob)
                return original(path, *args, **kwargs)

            with patch.object(Path, "resolve", resolve):
                doctor._check_files(snapshot, [artifact], "base", allowed_root=hub)
                with self.assertRaises(ValueError):
                    doctor._check_files(snapshot, [artifact], "fine-tuned")

            def escaping(path, *args, **kwargs):
                if path == snapshot / "model.bin":
                    return original(outside)
                return original(path, *args, **kwargs)

            with patch.object(Path, "resolve", escaping), self.assertRaises(ValueError):
                doctor._check_files(snapshot, [artifact], "base", allowed_root=hub)
            for name in ("../blobs/sha", str(blob)):
                with self.assertRaises(ValueError):
                    doctor._check_files(snapshot, [{**artifact, "path": name}], "base", allowed_root=hub)

    def test_model_path_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pins = self.make_model(root)
            pins["model"]["finetuned"]["files"][0]["path"] = "../outside.safetensors"
            with self.assertRaises(ValueError):
                doctor.check_model_files(root, pins)

    def test_runtime_requires_pinned_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            pins = {"runtime": {"env_prefix": "env", "packages": {"torch": "1"}, "laya": {"commit": "c" * 40}}}
            with self.assertRaises(ValueError):
                doctor.runtime_python(Path(directory), pins)

    def test_pins_are_lazy(self):
        with self.assertRaises(OSError):
            doctor.load_pins(Path("does-not-exist.json"))
        self.assertEqual(doctor.load_pins()["server"]["port"], 18090)

    def test_windows_v2_metadata_and_calibrated_identity(self):
        records = [
            {"schema_version": 2, "event": "application", "application": {"exe_name": "CoinPoker.exe", "process_id": 42}},
            {"schema_version": 2, "event": "window", "window": {"exe_name": "CoinPoker.exe", "process_id": 42,
             "hwnd": "0x100000001", "title": "Table 1", "on_screen": True, "width": 1200, "height": 800}},
        ]
        apps, windows = doctor.metadata_records("\n".join(json.dumps(r) for r in records))
        present, matched = doctor.matching_metadata(apps, windows,
            {"COINPOKER_EXE_NAME": "coinpoker.EXE", "COINPOKER_PID": "42", "COINPOKER_WINDOW_HWND": "0x100000001"})
        self.assertTrue(present)
        self.assertEqual(len(matched), 1)
        _, matched = doctor.matching_metadata(apps, windows,
            {"COINPOKER_EXE_NAME": "coinpoker.exe", "COINPOKER_WINDOW_HWND": "0x100000002"})
        self.assertEqual(matched, [])
        _, matched = doctor.matching_metadata(apps, windows,
            {"COINPOKER_EXE_NAME": "coinpoker.exe", "COINPOKER_WINDOW_HWND": "04294967297"})
        self.assertEqual(len(matched), 1)
        records[1]["window"]["hwnd"] = 4294967297
        with self.assertRaises(ValueError):
            doctor.metadata_records("\n".join(json.dumps(r) for r in records))

    def test_subprocess_metadata_uses_utf8_and_rejects_invalid_output(self):
        title = "Mesa café"
        script = ("import sys; sys.stdout.buffer.write(" +
                  repr(json.dumps({"schema_version": 2, "event": "window", "window": {
                      "exe_name": "CoinPoker.exe", "process_id": 42, "hwnd": "0x1",
                      "title": title, "on_screen": True, "width": 1, "height": 1}},
                      ensure_ascii=False).encode("utf-8") + b"\n") + ")")
        output = doctor.run_command([sys.executable, "-c", script], timeout=5)
        self.assertEqual(output.returncode, 0)
        _, windows = doctor.metadata_records(output.stdout)
        self.assertEqual(windows[0]["title"], title)
        with self.assertRaisesRegex(ValueError, "not UTF-8"):
            doctor.run_command([sys.executable, "-c",
                                "import sys; sys.stdout.buffer.write(bytes([255]))"], timeout=5)

    def test_offline_never_calls_http_and_reports_blocked(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(doctor, "request_json", side_effect=AssertionError("network forbidden")), \
             patch.object(doctor, "run_command", side_effect=OSError("missing tools")):
            checks = doctor.collect(Path(directory), Path("missing-binary"), offline=True)
            self.assertTrue(any(c["status"] == "blocked" for c in checks))
            self.assertFalse(any(c["check"] == "multimodal_api" and c["status"] == "pass" for c in checks))

    def test_rust_is_required_only_for_source_checkout(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(doctor, "run_command", side_effect=OSError("missing tools")) as runner:
            root = Path(directory)
            bundle_checks = doctor.collect(root, Path("missing-binary"), offline=True)
            self.assertEqual(next(c for c in bundle_checks if c["check"] == "rust_toolchain")["status"], "info")
            self.assertFalse(any(call.args[0][0] == "rustc" for call in runner.call_args_list))

            (root / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
            runner.reset_mock()
            source_checks = doctor.collect(root, Path("missing-binary"), offline=True)
            self.assertEqual(next(c for c in source_checks if c["check"] == "rust_toolchain")["status"], "fail")
            self.assertTrue(any(call.args[0][0] == "rustc" for call in runner.call_args_list))

    def test_informational_check_does_not_fail_doctor(self):
        checks = [{"check": "rust_toolchain", "status": "info", "detail": "prebuilt bundle"}]
        with patch.object(doctor, "collect", return_value=checks), \
             patch.object(doctor.sys, "argv", ["doctor.py"]), redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(), 0)

    def test_offline_skips_only_http_probes_not_failed_hashes(self):
        checks = [{"check": "runtime_asset", "status": "pass", "detail": "verified"},
                  {"check": "vlm_models", "status": "blocked", "detail": "offline"},
                  {"check": "multimodal_api", "status": "blocked", "detail": "offline"}]
        with patch.object(doctor, "collect", return_value=checks), \
             patch.object(doctor.sys, "argv", ["doctor.py", "--offline"]), redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(), 0)
            checks[0]["status"] = "fail"
            self.assertEqual(doctor.main(), 1)


if __name__ == "__main__":
    unittest.main()
