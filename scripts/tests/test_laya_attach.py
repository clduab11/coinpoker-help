"""Synthetic metadata only: no real window listing, pixels, model or listener."""

import ast
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import laya_attach as attach

EXE = "CoinPoker.exe"
TITLE = "NLH 123456 - synthetic table"


def profile():
    return {"format": 1, "version": 1, "user_scope": "practice-six-max",
            "selector_exe": EXE, "selector_title_regex": r"^NLH\s*[0-9]+"}


def window(title=TITLE, hwnd="0x11", **extra):
    return {"process_id": 11, "hwnd": hwnd, "exe_name": EXE, "title": title,
            "on_screen": True, "width": 800, "height": 600, **extra}


def records(*windows, version=2):
    applications = {item["process_id"]: item["exe_name"] for item in windows}
    return ([{"schema_version": version, "event": "application",
              "application": {"process_id": pid, "exe_name": exe}}
             for pid, exe in applications.items()]
            + [{"schema_version": version, "event": "window", "window": item}
               for item in windows])


def encode(values):
    return ("".join(json.dumps(value) + "\n" for value in values)).encode("utf-8")


def listing(*windows, version=2):
    return attach.parse_window_listing(encode(records(*windows, version=version)))


class AttachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="attach-b-nlh-", dir=SCRIPTS.parent / ".local")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "target/debug/coinpoker.exe"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"synthetic nonexecutable fixture; never run")
        self.path = self.root / attach.DEFAULT_PROFILE
        self.measured = listing(window())
        guard = patch.object(attach.subprocess, "Popen", side_effect=AssertionError("Real enumeration is forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    def save(self):
        return attach.persist_profile(profile(), self.measured, confirmed=True, root=self.root)

    def select(self, metadata=None):
        with patch.object(attach, "list_windows", return_value=self.measured if metadata is None else metadata):
            return attach.PracticeAttachment(root=self.root).select()

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(attach.AttachError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), attach.MESSAGES[code])

    def test_builtin_rule_is_user_declared_not_perception_calibration(self):
        self.assertEqual(attach.BUILTIN_RULE.document(), profile())
        self.assertEqual(attach.load_profile(root=self.root).document(), profile())
        self.assertFalse(self.path.exists())
        self.assertNotIn("calibrated", attach.BUILTIN_RULE.document())
        self.assertNotIn("practice-profile-missing", attach.MESSAGES)
        self.assertNotIn("practice-scope-unverified", attach.MESSAGES)
        self.assertNotIn("practice-target-unavailable", attach.MESSAGES)

    def test_missing_profile_uses_default_rule_without_writing_or_blocking(self):
        with patch.object(attach, "list_windows", return_value=self.measured) as discover:
            result = attach.PracticeAttachment(root=self.root).select()
        discover.assert_called_once_with(root=self.root)
        self.assertTrue(result.ok)
        self.assertEqual(result.key, ("coinpoker.exe", 11, "0x11"))
        self.assertFalse(self.path.exists())

    def test_constructor_alone_has_no_discovery_or_feed_side_effect(self):
        with patch.object(attach, "list_windows") as discover, patch.object(attach.subprocess, "Popen") as process:
            attach.PracticeAttachment(root=self.root)
        discover.assert_not_called()
        process.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_anchored_nlh_ascii_digit_rule_accepts_declared_whitespace_and_suffixes(self):
        for title in ("NLH1", "NLH 00123", "NLH\t42", "NLH\n42", "NLH\u00a042",
                      "NLH123456synthetic", "NLH 123 - arbitrary cash label", "NLH 123 - lobby label"):
            with self.subTest(title=title):
                self.assertTrue(self.select(listing(window(title))).ok)

    def test_other_titles_cannot_match_generic_lobby_embedded_prefix_or_unicode_digits(self):
        for title in (None, "", "CoinPoker", "CoinPoker Lobby", "Practice Games", "Cash",
                      "XXNLH123", " NLH123", "nlh123", "NLH", "NLH abc", "NLH -12", "NLH\u0661\u0662"):
            with self.subTest(title=title):
                result = self.select(listing(window(title)))
                self.assertEqual(result.code, "practice-target-absent")
                self.assertIsNone(result.config)
        self.assertEqual(self.select(listing()).code, "practice-target-absent")

    def test_exact_coinpoker_process_required_case_insensitive_not_substring(self):
        self.assertTrue(self.select(listing(window(exe_name=EXE.upper()))).ok)
        for name in ("other-fixture.exe", "prefix-" + EXE, EXE + ".bak"):
            result = self.select(listing(window(exe_name=name)))
            self.assertEqual(result.code, "practice-target-absent")
            self.assertIsNone(result.config)

    def test_drawn_nlh_caption_requires_explicit_confirmed_os_rule(self):
        metadata = listing(window("CoinPoker", width=900, height=686))
        self.assertEqual(self.select(metadata).code, "practice-target-absent")
        value = attach.CONFIRMED_GAME_WINDOW_RULE.document()
        self.assert_error("practice-profile-confirmation-required", attach.persist_profile,
                          value, metadata, root=self.root)
        attach.persist_profile(value, metadata, confirmed=True, root=self.root)
        result = self.select(metadata)
        self.assertTrue(result.ok)
        self.assertEqual(result.config["window_title"], "CoinPoker")
        self.assertEqual(result.key, ("coinpoker.exe", 11, "0x11"))
        self.assertNotIn("calibrated", value)
        resized = self.select(listing(window("CoinPoker", width=1600, height=1200)))
        self.assertEqual(result.key, resized.key)
        self.assertEqual(result.config, resized.config)

    def test_confirmed_os_rule_stays_exact_and_fails_on_ambiguity(self):
        metadata = listing(window("CoinPoker"))
        attach.persist_profile(attach.CONFIRMED_GAME_WINDOW_RULE.document(), metadata,
                               confirmed=True, root=self.root)
        for title in ("CoinPoker Lobby", "prefix CoinPoker", "NLH 123", "CoinPoker "):
            self.assertEqual(self.select(listing(window(title))).code, "practice-target-absent")
        self.assertEqual(self.select(listing(window("CoinPoker"), window("CoinPoker", hwnd="0x21"))).code,
                         "practice-target-ambiguous")
        self.assertEqual(self.select(listing(window("CoinPoker", exe_name="other.exe"))).code,
                         "practice-target-absent")

    def test_same_title_wrong_application_cannot_make_matching_source_ambiguous(self):
        result = self.select(listing(window(), window(hwnd="0x21", process_id=21, exe_name="other-fixture.exe")))
        self.assertTrue(result.ok)
        self.assertEqual(result.config["pid"], 11)

    def test_hidden_or_zero_bounds_targets_are_not_eligible(self):
        for fields in ({"on_screen": False}, {"width": 0}, {"height": 0}):
            self.assertEqual(self.select(listing(window(**fields))).code, "practice-target-absent")
            result = self.select(listing(window(), window(hwnd="0x21", **fields)))
            self.assertTrue(result.ok)
            self.assertEqual(result.config["window_hwnd"], "0x11")

    def test_two_visible_matching_windows_fail_closed_even_with_identical_titles(self):
        for title in (TITLE, "NLH999 - another synthetic window"):
            result = self.select(listing(window(), window(title, hwnd="0x21", process_id=21)))
            self.assertEqual(result.code, "practice-target-ambiguous")
            self.assertIsNone(result.config)
            self.assertIsNone(result.key)
            self.assertEqual(len(result.private_diagnostics["candidates"]), 2)

    def test_ready_config_pins_current_identity_and_only_fixed_internal_flags(self):
        result = self.select()
        config = result.config
        self.assertTrue(result.ok)
        self.assertEqual(config["binary"], "target/debug/coinpoker.exe")
        self.assertEqual(config["exe_name"], EXE)
        self.assertEqual(config["pid"], 11)
        self.assertEqual(config["window_hwnd"], "0x11")
        self.assertEqual(config["window_title"], "NLH")
        self.assertEqual({key: config[key] for key in attach.RECORDING}, attach.RECORDING)
        self.assertEqual(set(config), {"binary", "exe_name", "pid", "window_hwnd", "window_title", *attach.RECORDING})
        self.assertNotIn("calibrated", config)
        self.assertIn("user-declared", result.message)
        config["record_dir"] = "outside"
        self.assertEqual(result.config["record_dir"], ".local/captures")

    def test_key_excludes_title_resolution_role_and_optional_profile(self):
        before = self.select()
        history = {"role": "observing", "events": ["synthetic-observation"]}
        for role, width, height in (("seated_waiting", 1, 1), ("your_turn", 7680, 4320),
                                    ("observing", 40000, 30000), ("seated_waiting", 0xffffffff, 0xffffffff)):
            history["role"] = role
            after = self.select(listing(window("NLH99999 - changed synthetic suffix", width=width, height=height)))
            self.assertEqual(before.key, after.key)
            self.assertEqual(before.config, after.config)
        self.save()
        self.path.write_text(json.dumps(profile(), indent=2), encoding="utf-8")
        self.assertEqual(before.key, self.select().key)
        self.assertEqual(history["events"], ["synthetic-observation"])

    def test_every_select_revalidates_current_metadata_and_optional_file(self):
        selector = attach.PracticeAttachment(root=self.root)
        with patch.object(attach, "list_windows", side_effect=[self.measured, listing(window("CoinPoker"))]) as discover:
            self.assertTrue(selector.select().ok)
            self.assertEqual(selector.select().code, "practice-target-absent")
        self.assertEqual(discover.call_count, 2)
        changed = self.select(listing(window(process_id=25, hwnd="0x25")))
        self.assertEqual(changed.key, ("coinpoker.exe", 25, "0x25"))
        self.save()
        self.path.write_text("{}", encoding="utf-8")
        with patch.object(attach, "list_windows") as discover:
            self.assertEqual(selector.select().code, "practice-profile-invalid")
            discover.assert_not_called()

    def test_binary_debug_preferred_release_fallback_does_not_change_identity_key(self):
        before = self.select()
        release = self.root / "target/release/coinpoker.exe"
        release.parent.mkdir(parents=True)
        release.write_bytes(b"synthetic fixture; never run")
        self.assertEqual(attach.resolve_binary(self.root), self.binary)
        self.binary.unlink()
        after = self.select()
        self.assertEqual(before.key, after.key)
        self.assertEqual(after.config["binary"], "target/release/coinpoker.exe")
        release.unlink()
        self.assert_error("native-binary-missing", attach.resolve_binary, self.root)

    def test_redirected_binary_not_silently_replaced_by_release(self):
        for outside in (self.root / "other/coinpoker.exe", self.root.parent / "coinpoker.exe"):
            with patch.object(Path, "resolve", autospec=True,
                              side_effect=lambda path: outside if path == self.binary else path):
                self.assert_error("native-binary-unsafe", attach.resolve_binary, self.root)

    def test_schema_one_numeric_and_two_string_hwnd(self):
        for version, hwnd in ((1, 0x100000001), (1, "0x100000001"), (2, "0x100000001")):
            with self.subTest(version=version, hwnd=hwnd):
                parsed = listing(window(hwnd=hwnd), version=version)
                self.assertEqual(parsed.windows[0].hwnd, "0x100000001")
                self.assertEqual(parsed.applications, ((11, "coinpoker.exe"),))

    def test_listing_requires_complete_newline_and_valid_json(self):
        for raw in (b"{}", b"\n", b"{}\n", b"[]\n", b"\xff\n", b"NaN\n"):
            self.assert_error("window-list-invalid", attach.parse_window_listing, raw)

    def test_unknown_schema_events_and_extraneous_fields_rejected(self):
        for mutate in (lambda values: values[0].update(schema_version=True),
                       lambda values: values[0].update(schema_version=3),
                       lambda values: values[0].update(argv=["--capture"]),
                       lambda values: values[0]["application"].update(endpoint="https://invalid.test/"),
                       lambda values: values[1]["window"].update(hero_cards=[]),
                       lambda values: values[1].update(event="observation")):
            values = records(window())
            mutate(values)
            self.assert_error("window-list-invalid", attach.parse_window_listing, encode(values))

    def test_invalid_identity_wire_types_or_invalid_uint32_bounds_fail_closed(self):
        variants = ({"process_id": 0}, {"process_id": True}, {"hwnd": 123}, {"hwnd": "0x0"},
                    {"hwnd": "0x10000000000000000"}, {"exe_name": "C:\\fixture.exe"},
                    {"exe_name": "--capture.exe"}, {"title": "bad\x00name"}, {"title": "\ud800"},
                    {"title": "x" * 4097}, {"on_screen": 1}, {"width": -1}, {"height": True},
                    {"width": 0x100000000}, {"height": 1.5})
        for fields in variants:
            self.assert_error("window-list-invalid", listing, window(**fields))

    def test_orphan_conflicting_application_and_duplicate_hwnd_rejected(self):
        values = records(window())
        self.assert_error("window-list-invalid", attach.parse_window_listing, encode(values[1:]))
        values[0]["application"]["exe_name"] = "other-fixture.exe"
        self.assert_error("window-list-invalid", attach.parse_window_listing, encode(values))
        self.assert_error("window-list-invalid", listing, window(), window(hwnd="0x0011"))
        self.assert_error("window-list-invalid", attach.parse_window_listing, encode([records(window())[0]] * 2))

    def test_duplicate_json_keys_rejected_not_last_wins(self):
        raw = b'{"schema_version":1,"schema_version":2,"event":"application","application":{}}\n'
        self.assert_error("window-list-invalid", attach.parse_window_listing, raw)
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(profile()).replace('"format": 1', '"format": 1, "format": 1'), encoding="utf-8")
        self.assert_error("practice-profile-invalid", attach.load_profile, root=self.root)

    def test_listing_total_record_and_count_bounds(self):
        for raw in (b"x" * (attach.MAX_LIST_BYTES + 1), b"x" * (attach.MAX_LIST_RECORD_BYTES + 1) + b"\n",
                    b"{}\n" * (attach.MAX_LIST_RECORDS + 1)):
            self.assert_error("window-list-too-large", attach.parse_window_listing, raw)

    def test_status_reason_is_static_and_never_echoed(self):
        raw = encode([{"schema_version": 2, "event": "status", "state": "failed",
                       "reason": "SYNTHETIC-PRIVATE-TITLE synthetic-client.exe 0x123"}])
        self.assert_error("window-list-unavailable", attach.parse_window_listing, raw)

    def test_optional_profile_cannot_change_source_scope_regex_or_add_capture_fields(self):
        for field, invalid in (("format", True), ("version", 2), ("user_scope", "cash"),
                               ("selector_exe", "other-fixture.exe"), ("selector_title_regex", ".*"),
                               ("selector_title_regex", "^NLH"), ("selector_title_regex", None)):
            value = profile()
            value[field] = invalid
            self.assert_error("practice-profile-invalid", attach.validate_profile, value)
        for key in ("binary", "argv", "endpoint", "record_dir", "pid", "hwnd", "window_hwnd",
                    "width", "height", "resolution", "roi", "lobby_title", "lobby_size", "cash_titles", "calibrated"):
            value = profile()
            value[key] = "synthetic-invalid"
            self.assert_error("practice-profile-invalid", attach.validate_profile, value)

    def test_optional_profile_oversize_and_invalid_data_fail_closed(self):
        self.path.parent.mkdir(parents=True)
        for raw in (b"x" * (attach.MAX_PROFILE_BYTES + 1), b'{"format": NaN}', b"[]", b"invalid", b"\xff"):
            self.path.write_bytes(raw)
            self.assert_error("practice-profile-invalid", attach.load_profile, root=self.root)

    def test_private_paths_cannot_escape_or_use_ads_devices_and_drive_relative_paths(self):
        for path in (self.root / "profile.json", ".local/../.local/profile.json", ".local/profile.json:stream",
                     "C:relative.json", ".local", ".local/profile.txt", ".local/CON.json", ".local/NUL.json",
                     ".local/LPT1.json", ".local/COM1/profile.json", ".local/bad\x00.json", ".local/bad\n.json",
                     "\\\\.\\NUL", "\\\\?\\C:\\profile.json"):
            self.assert_error("practice-profile-invalid", attach.load_profile, path, root=self.root)
        self.assertFalse(self.path.exists())

    def test_optional_persistence_needs_confirmation_and_one_eligible_window_not_cash_lobby_labels(self):
        for confirmed in (False, None, 1, "true"):
            self.assert_error("practice-profile-confirmation-required", attach.persist_profile,
                              profile(), self.measured, confirmed=confirmed, root=self.root)
        for metadata in (listing(), listing(window(exe_name="other-fixture.exe")), listing(window(on_screen=False)),
                         listing(window(), window(hwnd="0x21"))):
            self.assert_error("practice-profile-mismatch", attach.persist_profile,
                              profile(), metadata, confirmed=True, root=self.root)
        self.assertFalse(self.path.exists())
        self.save()
        self.assertTrue(self.select().ok)

    def test_rule_persistence_has_no_ephemeral_identity_title_size_or_perception_claim(self):
        value = profile()
        untouched = copy.deepcopy(value)
        saved = attach.persist_profile(value, self.measured, confirmed=True, root=self.root)
        raw = self.path.read_bytes()
        self.assertEqual(value, untouched)
        self.assertEqual(saved.document(), untouched)
        self.assertEqual(attach.load_profile(root=self.root).document(), untouched)
        self.assertLessEqual(len(raw), attach.MAX_PROFILE_BYTES)
        for field in ("pid", "hwnd", "binary", "width", "height", "calibrated", "lobby_title", "cash_titles"):
            self.assertNotIn('"' + field + '"', raw.decode("utf-8"))
        self.assertNotIn(TITLE.encode(), raw)
        self.assertNotIn(str(self.root).encode(), raw)
        self.assert_error("practice-profile-exists", attach.persist_profile,
                          value, self.measured, confirmed=True, root=self.root)
        self.assertEqual(self.path.read_bytes(), raw)
        value["selector_exe"] = "mutated caller"
        returned = saved.document()
        returned["selector_exe"] = "mutated return"
        self.assertEqual(saved.document(), untouched)

    def test_public_status_and_repr_do_not_expose_source_identity(self):
        for metadata in (self.measured, listing(window(), window(hwnd="0x21"))):
            result = self.select(metadata)
            public = json.dumps(result.public_status()) + repr(result)
            for private in (EXE, TITLE, "0x11", str(self.root)):
                self.assertNotIn(private, public)
            self.assertEqual(set(result.public_status()), {"code", "message"})
            diagnostics = result.private_diagnostics
            self.assertEqual(diagnostics["candidates"][0]["title"], TITLE)
            diagnostics["candidates"][0]["title"] = "changed caller"
            self.assertEqual(result.private_diagnostics["candidates"][0]["title"], TITLE)

    def test_private_candidates_cap_does_not_truncate_ambiguity_checks(self):
        windows = [window("CoinPoker", hex(i + 100)) for i in range(40)]
        windows.extend((window(hwnd="0x1"), window(hwnd="0x2")))
        result = self.select(listing(*windows))
        self.assertEqual(result.code, "practice-target-ambiguous")
        self.assertEqual(len(result.private_diagnostics["candidates"]), attach.MAX_DIAGNOSTIC_CANDIDATES)

    def fake_process(self, raw):
        process = Mock(stdout=io.BytesIO(raw))
        process.wait.return_value = 0
        process.poll.return_value = 0
        return process

    def test_listing_subprocess_fixed_metadata_mode_and_clean_environment(self):
        process = self.fake_process(encode(records(window())))
        hostile = {"COINPOKER_VLM_ENDPOINT": "https://invalid.test/private", "coinpoker_WINDOW_HWND": "0x99"}
        with patch.dict(os.environ, hostile), patch.object(attach.subprocess, "Popen", return_value=process) as popen:
            result = attach.list_windows(root=self.root)
        args, kwargs = popen.call_args
        self.assertEqual(args, ([str(self.binary), "--list-windows"],))
        self.assertEqual(kwargs["cwd"], self.root)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertFalse(kwargs["shell"])
        self.assertFalse(any(key.upper().startswith("COINPOKER_") for key in kwargs["env"]))
        self.assertEqual(result.windows[0].title, TITLE)
        self.assertTrue(process.stdout.closed)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_listing_spawn_error_nonzero_and_timeout_are_static(self):
        with patch.object(attach.subprocess, "Popen", side_effect=OSError("synthetic private error")):
            self.assert_error("window-list-failed", attach.list_windows, root=self.root)
        process = self.fake_process(b"")
        process.wait.return_value = 2
        with patch.object(attach.subprocess, "Popen", return_value=process):
            self.assert_error("window-list-failed", attach.list_windows, root=self.root)
        process = self.fake_process(b"")
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 5), 0]
        with patch.object(attach.subprocess, "Popen", return_value=process):
            self.assert_error("window-list-timeout", attach.list_windows, root=self.root)
        process.terminate.assert_called_once()

    def test_oversized_subprocess_output_only_terminates_the_mock_owned_child(self):
        process = self.fake_process(b"x" * (attach.MAX_LIST_BYTES + 8192))
        process.poll.return_value = None
        with patch.object(attach.subprocess, "Popen", return_value=process) as popen:
            self.assert_error("window-list-too-large", attach.list_windows, root=self.root)
        process.terminate.assert_called_once()
        self.assertTrue(process.stdout.closed)
        popen.assert_called_once()

    def test_listing_timeout_cleanup_has_bounded_kill_fallback(self):
        process = self.fake_process(b"")
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 5), subprocess.TimeoutExpired("fixture", 1), 0]
        with patch.object(attach.subprocess, "Popen", return_value=process):
            self.assert_error("window-list-timeout", attach.list_windows, root=self.root)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual([call.kwargs["timeout"] for call in process.wait.call_args_list][1:], [1, 1])

    def test_idle_stdout_uses_fixed_deadline_without_a_real_wait_or_process(self):
        process = self.fake_process(b"")
        process.poll.return_value = None
        finished, failed, reader = Mock(), Mock(), Mock()
        finished.wait.return_value = False
        reader.is_alive.return_value = False
        with patch.object(attach.subprocess, "Popen", return_value=process), \
                patch.object(attach.threading, "Event", side_effect=[finished, failed]), \
                patch.object(attach.threading, "Thread", return_value=reader):
            self.assert_error("window-list-timeout", attach.list_windows, root=self.root)
        finished.wait.assert_called_once_with(attach.LIST_TIMEOUT_SECONDS)
        reader.join.assert_called_once_with(timeout=1)
        process.terminate.assert_called_once()

    def test_sources_are_ascii_metadata_only_with_no_image_or_model_imports(self):
        for name in ("laya_attach.py", "tests/test_laya_attach.py", "start-vlm.ps1"):
            source = (SCRIPTS / name).read_text(encoding="utf-8")
            source.encode("ascii")
            self.assertFalse(any(line != line.rstrip() for line in source.splitlines()), name)
            self.assertNotIn("C:\\Users\\", source)
        tree = ast.parse((SCRIPTS / "laya_attach.py").read_text(encoding="utf-8"))
        imports = {alias.name.split(".")[0] for node in ast.walk(tree)
                   if isinstance(node, ast.Import) for alias in node.names}
        imports.update(node.module.split(".")[0] for node in ast.walk(tree)
                       if isinstance(node, ast.ImportFrom) and node.module)
        self.assertFalse(imports & {"torch", "PIL", "laya", "laya_dashboard", "laya_prep", "requests"})
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse(calls & {"capture", "capture_frame", "click", "predict", "begin_stream", "ingest"})

    def test_launcher_safe_defaults_optional_rule_offline_and_listener_order(self):
        source = (SCRIPTS / "start-vlm.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$NoAutoAttach", source)
        self.assertIn("[string]$PracticeConfig = '.local/practice-table.json'", source)
        self.assertIn("if (-not $DashboardOnly -and -not $NoAutoAttach)", source)
        self.assertIn("@('--auto-attach', '--practice-config', $PracticeConfig)", source)
        self.assertIn("if ($LiveConfig -and -not $NoAutoAttach)", source)
        self.assertLess(source.index("GetActiveTcpListeners()"), source.index("& $python"))
        self.assertLess(source.index("Port 18090 is already occupied"), source.index("$python ="))
        self.assertIn("-DashboardOnly loads no model and disables automatic attachment", source)
        self.assertIn("a missing private profile does not", source)
        self.assertIn("not title proof or perception calibration", source)
        for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
            self.assertIn(f"$env:{flag} = '1'", source)
        for unsafe in ("Stop-Process", "--fetch", "--vlm-endpoint", "Start-Process"):
            self.assertNotIn(unsafe, source)


if __name__ == "__main__":
    unittest.main()
