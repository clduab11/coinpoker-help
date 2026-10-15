"""Synthetic bounded provenance only; no services, models, captures or clients."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import laya_provenance as provenance

spec = importlib.util.spec_from_file_location("provenance_test_server", SCRIPTS / "laya-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="provenance-fixture-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def file(self, name, raw=b"synthetic"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def test_exact_file_digest_missing_directory_and_size_bound(self):
        path = self.file("binary.exe", b"abcd")
        identity = provenance.file_identity(path, maximum=4)
        self.assertEqual(identity["sha256"], hashlib.sha256(b"abcd").hexdigest())
        self.assertEqual(identity["size_bytes"], 4)
        with patch.object(Path, "open", side_effect=AssertionError("must not open")):
            self.assertEqual(provenance.file_identity(path, maximum=3)["state"], "unknown")
            self.assertEqual(provenance.file_identity(path.parent)["state"], "unknown")
            self.assertEqual(provenance.file_identity(self.root / "missing")["state"], "unknown")

    def test_file_changed_during_hash_is_not_known(self):
        path = self.file("file")
        info = path.stat()
        changed = SimpleNamespace(**{name: getattr(info, name) for name in
                                    ("st_dev", "st_ino", "st_size", "st_mtime_ns")})
        changed.st_size += 1
        with patch.object(provenance.os, "fstat", return_value=changed):
            self.assertEqual(provenance.file_identity(path)["reason"], "changed-during-read")

    def test_redirect_is_unknown_without_opening(self):
        path = self.file("file")
        with patch.object(Path, "is_symlink", return_value=True), \
                patch.object(Path, "open", side_effect=AssertionError("redirect must not open")):
            self.assertEqual(provenance.file_identity(path)["reason"], "redirected")

    def test_fake_root_never_inherits_parent_git_or_executes_commands(self):
        with patch.object(provenance.subprocess, "run", side_effect=AssertionError("no git discovery")):
            value = provenance.git_identity(self.root)
        self.assertEqual(value, {"sha": None, "dirty": None, "state": "unknown"})

    def test_git_clean_dirty_truncated_output_and_failures_are_explicit(self):
        (self.root / ".git").mkdir()
        sha = b"a" * 40 + b"\n"
        for output, dirty in ((b"", False), (b" M scripts/file.py\n", True), (b"?" * 65537, True)):
            with patch.object(provenance, "_git", side_effect=[(0, sha), (0, output)]):
                self.assertEqual(provenance.git_identity(self.root),
                                 {"sha": "a" * 40, "dirty": dirty, "state": "known"})
        for effect in (OSError("missing"), subprocess.TimeoutExpired("git", 3)):
            with patch.object(provenance, "_git", side_effect=effect):
                self.assertIsNone(provenance.git_identity(self.root)["dirty"])
        with patch.object(provenance, "_git", side_effect=[(0, sha), (1, b"")]):
            self.assertEqual(provenance.git_identity(self.root),
                             {"sha": "a" * 40, "dirty": None, "state": "unknown"})

    def test_git_command_has_timeout_no_shell_and_bounded_file_backed_output(self):
        def run(command, **kwargs):
            self.assertIs(kwargs["shell"], False)
            self.assertEqual(kwargs["timeout"], 3)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            kwargs["stdout"].write(b"a" * 1000)
            return SimpleNamespace(returncode=0)
        with patch.object(provenance.subprocess, "run", side_effect=run):
            self.assertEqual(provenance._git(self.root, ["status"], 10), (0, b"a" * 11))

    def test_manifest_is_explicit_includes_assets_and_does_not_walk_bloat(self):
        for name in provenance.SOURCE_FILES:
            self.file(name)
        self.file("crates/ingest/src/main.rs")
        self.file("crates/ingest/src/unit_tests.rs")
        self.file(".local/huge/private.rs")
        self.file("graphify-out/generated.rs")
        self.file("models/big/model.safetensors")
        with patch.object(provenance, "runtime_identity", return_value={"python": {"executable": {"state": "known"}}}), \
                patch.object(provenance, "git_identity", return_value={"sha": "a" * 40, "dirty": True, "state": "known"}):
            value = provenance.build_identity(self.root)
        names = set(value["files"])
        self.assertIn("scripts/dashboard/app.js", names)
        self.assertIn("crates/ingest/assets/laya/regions.json", names)
        self.assertIn("crates/ingest/src/main.rs", names)
        self.assertFalse(any(name.startswith((".local", "graphify-out", "models")) for name in names))
        self.assertNotIn("crates/ingest/src/unit_tests.rs", names)
        self.assertTrue(value["complete"], "known dirty is not unknown and is not a new gate")
        self.assertTrue(value["git"]["dirty"])
        self.assertEqual(value["manifest_sha256"], provenance.digest(value["files"]))

    def test_source_total_budget_is_bounded_and_records_incomplete(self):
        self.file("Cargo.lock", b"abcdef")
        with patch.object(provenance, "MAX_SOURCE_TOTAL", 3), \
                patch.object(provenance, "runtime_identity", return_value={"python": {"executable": {"state": "known"}}}):
            value = provenance.build_identity(self.root)
        self.assertFalse(value["complete"])
        self.assertEqual(value["files"]["Cargo.lock"]["reason"], "not-regular-or-size-bound")

    def test_runtime_records_actual_distribution_and_redacts_direct_url(self):
        directory = self.root / "laya.dist-info"
        self.file("laya.dist-info/direct_url.json", json.dumps({
            "url": "https://user:SECRET@example.invalid/repo", "vcs_info": {"commit_id": "b" * 40}}).encode())
        def distribution(name):
            if name != "laya":
                raise provenance.metadata.PackageNotFoundError(name)
            return SimpleNamespace(version="1.2.3", _path=directory)
        with patch.object(provenance.metadata, "distribution", side_effect=distribution):
            value = provenance.runtime_identity()
        self.assertEqual(value["packages"]["laya"]["vcs_commit"], "b" * 40)
        self.assertEqual(value["packages"]["laya"]["version"], "1.2.3")
        self.assertIsNone(value["packages"]["torch"]["version"])
        self.assertNotIn("SECRET", json.dumps(value))
        self.assertEqual(value["python"]["executable"]["state"], "known")
        self.assertEqual(value["python"]["executable"]["path"], str(Path(provenance.sys.executable).resolve(strict=True)))

    def pins(self):
        entry = {"path": "model.safetensors", "size": 4, "sha256": hashlib.sha256(b"base").hexdigest()}
        ft = {"path": "checkpoint", "files": [{**entry, "sha256": hashlib.sha256(b"fine").hexdigest()}],
              "calibration_file": "temperature.json", "acceptance_file": "floors.json"}
        for name in ("temperature.json", "floors.json"):
            ft["files"].append({"path": name, "size": 2, "sha256": hashlib.sha256(b"{}").hexdigest()})
        return {"model": {"repository": "synthetic/model", "revision": "r1", "files": [entry], "finetuned": ft}}

    def test_expected_model_pins_never_become_verified_without_actual_verifier(self):
        pins = self.pins()
        pins["model"]["files"].append({"path": "processor/config.json", "size": 2,
                                       "sha256": hashlib.sha256(b"{}").hexdigest()})
        snapshot = self.root / "base"
        self.file("base/model.safetensors", b"base")
        self.file("base/processor/config.json", b"{}")
        self.file("checkpoint/model.safetensors", b"fine")
        self.file("checkpoint/temperature.json", b"{}")
        self.file("checkpoint/floors.json", b"{}")
        expected = provenance.model_identity(pins, self.root, snapshot)
        self.assertFalse(expected["complete"])
        self.assertTrue(all(row["actual"]["sha256"] is None for row in expected["files"]))
        actual = []
        with patch.object(server, "REPO", str(self.root)), patch.object(server, "snapshot_dir", return_value=str(snapshot)):
            self.assertEqual(server.verify(pins, check_runtime=False, verified_files=actual), [])
        verified = provenance.model_identity(pins, self.root, snapshot, actual)
        self.assertTrue(verified["complete"])
        self.assertTrue(all(row["actual"]["sha256"] == row["expected_sha256"] for row in verified["files"]))
        pins["model"]["files"][0]["sha256"] = "0" * 64
        self.assertFalse(provenance.model_identity(pins, self.root, snapshot, actual)["complete"],
                         "verification of a different expectation cannot be relabelled")
        pins["model"]["files"][0]["sha256"] = hashlib.sha256(b"base").hexdigest()
        self.file("checkpoint/model.safetensors", b"oops")
        actual = []
        with patch.object(server, "REPO", str(self.root)), patch.object(server, "snapshot_dir", return_value=str(snapshot)):
            self.assertEqual(server.verify(pins, check_runtime=False, verified_files=actual),
                             ["hash mismatch fine-tuned model.safetensors"])
        self.assertFalse(provenance.model_identity(pins, self.root, snapshot, actual)["complete"])
        model_row = next(row for row in actual if row["path"] == str(self.root / "checkpoint/model.safetensors"))
        self.assertEqual(model_row["sha256"], hashlib.sha256(b"oops").hexdigest())

    def test_admission_binds_selector_and_requires_matching_service_identity_only_for_completeness(self):
        self.file(".local/selector.json", b'{"selector":"synthetic"}')
        approval = {"mode": "inference-enabled", "source": {"id": "synthetic"}, "service_instance_id": "a" * 32}
        service = {"instance_id": "b" * 32, "complete": True}
        with patch.object(provenance, "build_identity", return_value={"complete": True}):
            value = provenance.admission_identity(self.root, "synthetic.exe", approval,
                                                 service=service, selector=".local/selector.json")
            self.assertFalse(value["complete"])
            self.assertEqual(value["service"]["state"], "unknown")
            self.assertEqual(value["selector"]["sha256"], hashlib.sha256(b'{"selector":"synthetic"}').hexdigest())
            manual = provenance.admission_identity(self.root, "synthetic.exe", {**approval, "mode": "capture-only"})
            self.assertTrue(manual["complete"])
            self.assertEqual(manual["selector"]["sha256"], provenance.digest(approval["source"]))

    def test_service_startup_identity_binds_python_launch_options_without_loading_models(self):
        pins = {"server": {"port": 18090, "alias": "synthetic"}, "model": {"revision": "r1"}}
        captured = {}
        real_service = server.Service
        def service(*args, **kwargs):
            captured["service"] = real_service(*args, **kwargs)
            return captured["service"]
        with patch.object(server, "ROOT", self.root), patch.object(server, "Service", side_effect=service), \
                patch.object(server, "BoundedHTTPServer"), patch.object(server, "Engine", side_effect=AssertionError("no model")), \
                patch.object(server.provenance, "build_identity", return_value={"complete": False}), \
                patch("sys.stdout", io.StringIO()):
            self.assertEqual(server.cmd_serve(pins, None, None,
                provenance_directory=".local/laya/service-provenance"), 0)
        identity = captured["service"].provenance
        path = self.root / ".local/laya/service-provenance" / (captured["service"].instance_id + ".json")
        self.assertEqual(json.loads(path.read_bytes()), identity)
        self.assertEqual(identity["pid"], provenance.os.getpid())
        self.assertEqual(identity["argv"][0], sys.executable)
        self.assertFalse(identity["options"]["enable_inference"])
        self.assertFalse(identity["model"]["complete"])
        self.assertFalse(identity["complete"])

    def test_server_stderr_cap_retains_exact_counts_through_tail(self):
        stream = io.BytesIO()
        with patch.object(server.manual_capture, "MAX_LOG", 4):
            logger = server.BoundedErrorLog(stream)
            self.assertEqual(logger.write("abcd"), 4)
            self.assertFalse(logger.counter.value["truncated"])
            self.assertEqual(logger.write("tail"), 4)
            self.assertEqual(logger.write("!"), 1)
        self.assertEqual(stream.getvalue(), b"abcd")
        self.assertEqual(logger.counter.value["bytes_seen"], 9)
        self.assertEqual(logger.counter.value["bytes_dropped"], 5)
        self.assertEqual(logger.counter.value["cap_bytes"], 4)

    def test_unknown_startup_identity_does_not_create_a_service_gate(self):
        pins = {"server": {"port": 18090, "alias": "synthetic"}, "model": {"revision": "r1"}}
        with patch.object(server, "BoundedHTTPServer"), \
                patch.object(server.provenance, "service_identity", side_effect=OSError("synthetic unavailable")), \
                patch.object(server, "Engine", side_effect=AssertionError("no model")), patch("sys.stdout", io.StringIO()):
            self.assertEqual(server.cmd_serve(pins, None, None), 0)

    def test_server_stderr_write_flush_and_short_write_failures_make_counts_uncertain(self):
        for kind in ("write", "flush", "short"):
            with self.subTest(kind=kind):
                stream = Mock()
                stream.tell.return_value = 0
                stream.write.return_value = 4 if kind != "short" else 2
                if kind == "write":
                    stream.write.side_effect = OSError("synthetic write failure")
                if kind == "flush":
                    stream.flush.side_effect = OSError("synthetic flush failure")
                logger = server.BoundedErrorLog(stream)
                with self.assertRaises(OSError):
                    logger.write("tail")
                self.assertFalse(logger.counter.value["accounting_complete"])
                self.assertTrue(logger.counter.value["write_failed"])
                self.assertEqual(logger.counter.value["bytes_unaccounted"], 4)
                self.assertEqual(logger.counter.value["bytes_dropped"], 0, "uncertain writes are not exact dropped bytes")

    def test_service_answer_write_failure_is_persisted_as_incomplete_not_exact_loss(self):
        pins = {"server": {"port": 18090, "alias": "synthetic"}, "model": {"revision": "r1"}}
        captured = {}
        real_service = server.Service
        def service(*args, **kwargs):
            captured["service"] = real_service(*args, **kwargs)
            return captured["service"]
        def log():
            with self.assertRaises(OSError):
                captured["service"].log_fn({"n": 0})
        filename = Mock()
        filename.stat.return_value = SimpleNamespace(st_size=0)
        filename.open.return_value.write.side_effect = OSError("synthetic answer archive failure")
        with patch.object(server, "ROOT", self.root), patch.object(server, "Service", side_effect=service), \
                patch.object(server, "BoundedHTTPServer") as http, \
                patch.object(server.dashboard, "local_path", return_value=filename), \
                patch.object(server.provenance, "build_identity", return_value={"complete": False}), \
                patch("sys.stdout", io.StringIO()):
            http.return_value.serve_forever.side_effect = log
            self.assertEqual(server.cmd_serve(pins, ".local/answers.jsonl", None,
                provenance_directory=".local/laya/service-provenance"), 0)
        instance = captured["service"].instance_id
        receipt = json.loads((self.root / ".local/laya/service-provenance" / (instance + ".json")).read_bytes())
        self.assertFalse(receipt["diagnostics_complete"])
        answer = receipt["diagnostic_streams"]["answers"]
        self.assertTrue(answer["write_failed"])
        self.assertFalse(answer["accounting_complete"])
        self.assertEqual(answer["bytes_unaccounted"], 9)
        self.assertEqual(answer["bytes_dropped"], 0)

    def test_server_answer_cap_is_accounted_and_final_private_receipt_is_refreshed(self):
        pins = {"server": {"port": 18090, "alias": "synthetic"}, "model": {"revision": "r1"}}
        captured = {}
        real_service = server.Service
        def service(*args, **kwargs):
            captured["service"] = real_service(*args, **kwargs)
            return captured["service"]
        def log():
            for n in range(3):
                captured["service"].log_fn({"n": n})
        with patch.object(server, "ROOT", self.root), patch.object(server, "Service", side_effect=service), \
                patch.object(server, "BoundedHTTPServer") as http, patch.object(server.threading, "Thread"), \
                patch.object(server.dashboard, "ManualSessionFeed"), \
                patch.object(server.dashboard, "local_path", return_value=self.root / ".local/answers.jsonl"), \
                patch.object(server.manual_capture, "MAX_LOG", 18), \
                patch.object(server.provenance, "build_identity", return_value={"complete": False}), \
                patch("sys.stdout", io.StringIO()):
            http.return_value.serve_forever.side_effect = log
            self.assertEqual(server.cmd_serve(pins, ".local/answers.jsonl", None, dashboard_only=False,
                enable_inference=True, automatic_inference=True, continuous_observation=True,
                manual_start=True, provenance_directory=".local/laya/service-provenance"), 0)
        instance = captured["service"].instance_id
        receipt = json.loads((self.root / ".local/laya/service-provenance" / (instance + ".json")).read_bytes())
        answer = receipt["diagnostic_streams"]["answers"]
        self.assertEqual((answer["bytes_seen"], answer["bytes_archived"], answer["bytes_dropped"]), (27, 18, 9))
        self.assertTrue(answer["truncated"])
        self.assertEqual((self.root / ".local/answers.jsonl").read_bytes(), b'{"n": 0}\n{"n": 1}\n')

    def test_persistent_answer_close_flush_failure_still_publishes_uncertain_final_receipt(self):
        for fail_initial_flush in (False, True):
            with self.subTest(fail_initial_flush=fail_initial_flush):
                class Stream:
                    closing = False
                    flush_calls = 0
                    close_calls = 0
                    def write(self, line):
                        return len(line)
                    def flush(self):
                        self.flush_calls += 1
                        if fail_initial_flush or self.closing:
                            raise OSError("persistent synthetic buffered flush failure")
                    def close(self):
                        self.close_calls += 1
                        self.closing = True
                        self.flush()
                stream = Stream()
                pins = {"server": {"port": 18090, "alias": "synthetic"}, "model": {"revision": "r1"}}
                captured = {}
                real_service = server.Service
                def service(*args, **kwargs):
                    captured["service"] = real_service(*args, **kwargs)
                    return captured["service"]
                def log():
                    if fail_initial_flush:
                        with self.assertRaisesRegex(OSError, "persistent synthetic"):
                            captured["service"].log_fn({"n": 0})
                    else:
                        captured["service"].log_fn({"n": 0})
                filename = Mock()
                filename.stat.return_value = SimpleNamespace(st_size=0)
                filename.open.return_value = stream
                with patch.object(server, "ROOT", self.root), patch.object(server, "Service", side_effect=service), \
                        patch.object(server, "BoundedHTTPServer") as http, \
                        patch.object(server.dashboard, "local_path", return_value=filename), \
                        patch.object(server.provenance, "build_identity", return_value={"complete": False}), \
                        patch("sys.stdout", io.StringIO()):
                    http.return_value.serve_forever.side_effect = log
                    with self.assertRaisesRegex(OSError, "persistent synthetic"):
                        server.cmd_serve(pins, ".local/answers.jsonl", None,
                                         provenance_directory=".local/laya/service-provenance")
                self.assertEqual(stream.close_calls, 1)
                self.assertEqual(stream.flush_calls, 2)
                instance = captured["service"].instance_id
                receipt = json.loads((self.root / ".local/laya/service-provenance" / (instance + ".json")).read_bytes())
                self.assertFalse(receipt["diagnostics_complete"])
                answer = receipt["diagnostic_streams"]["answers"]
                self.assertTrue(answer["write_failed"])
                self.assertFalse(answer["accounting_complete"])
                self.assertEqual(answer["bytes_unaccounted"], 9 if fail_initial_flush else 0)
                self.assertEqual(answer["bytes_dropped"], 0, "a failed close cannot establish an exact byte loss")


if __name__ == "__main__":
    unittest.main()
