#!/usr/bin/env python3
"""Synthetic Monitor browser checks; all requests are intercepted, never live."""
import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:18090"


def fixture(scenario):
    from scripts.tests.test_laya_numeric_ui import NumericUiTests
    value = NumericUiTests()
    value.setUp()
    raw = copy.deepcopy(value.value)
    now = raw["capture"]["last_heartbeat_unix_ms"]
    raw["capture_control"] = {"enabled": False, "control_id": "d" * 32,
        "status": "unavailable", "can_start": False, "can_stop": False}
    if scenario != "provisional":
        raw["numeric_observation"] = None
        raw["partial_observation"] = copy.deepcopy(value.native) if scenario in {"native", "native-timing"} else None
    if scenario == "native-timing":
        partial = raw["partial_observation"]
        partial["captured_at_ms"] = 1000
        partial["capture"] = {"kind": "frame", "service_instance_id": raw["server"]["instance_id"],
            "session_id": raw["session_id"], "capture_session_id": raw["capture_session"]["session_id"],
            "source_id": raw["capture"]["source_id"], "epoch": partial["epoch"], "sequence": raw["capture"]["frames"],
            "captured_at_ms": 1000, "captured_at_unix_ms": partial["captured_at_unix_ms"],
            "sha256": "f" * 64, "width": raw["capture"]["width"], "height": raw["capture"]["height"]}
        raw["native_timing"] = {"schema_version": 1, "generation": partial["generation"], "epoch": partial["epoch"],
            "captured_at_ms": 1000, "captured_at_unix_ms": partial["captured_at_unix_ms"],
            "emitted_at_unix_ms": now - 400, "ingested_at_unix_ms": now - 200, "api_snapshot_at_unix_ms": now - 10}
    if scenario not in {"native", "native-timing", "provisional", "pending-stop"}:
        raw["capture"].update(state="unavailable", fresh_capture=False)
        raw["capture_session"].update(status="idle", session_id=None, activity_state="idle")
    if scenario == "previous":
        raw["capture_session"].update(status="stopped", session_id="a" * 32,
            stop_reason="operator-stop", updated_at_unix_ms=now - 86_400_000)
    if scenario in {"capture-failure", "previous-capture-failure"}:
        raw["capture_session"].update(status="stopped", session_id="a" * 32,
            stop_reason="capture-failed", capture_failure_code="foreign-overlap",
            updated_at_unix_ms=now - (86_400_000 if scenario == "previous-capture-failure" else 0))
    if scenario == "pending-start":
        raw["capture_control"].update(enabled=True, status="available", can_start=True)
    if scenario == "pending-stop":
        raw["capture_control"].update(enabled=True, status="running", can_stop=True)
    return raw, now


def check_case(browser, out, viewport, forced, scenario, assets, csp):
    from playwright.sync_api import expect
    raw, now = fixture(scenario)
    context = browser.new_context(viewport=viewport, forced_colors="active" if forced else "none",
                                  service_workers="block", reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(5000)
    page.clock.install(time=now / 1000)
    page.clock.pause_at(time=now / 1000)
    errors, unexpected, pending = [], [], []
    polls = 0
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_request(route):
        nonlocal polls
        request = route.request
        url = urlsplit(request.url)
        if f"{url.scheme}://{url.netloc}" != ORIGIN:
            unexpected.append(request.url)
            route.abort()
        elif request.method == "GET" and url.path == "/api/state":
            polls += 1
            if scenario == "disconnect-first" and polls == 1:
                route.abort("connectionfailed")
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(raw))
        elif request.method == "POST" and scenario in {"pending-start", "pending-stop"} and url.path == (
                "/api/capture/start" if scenario == "pending-start" else "/api/capture/stop"):
            pending.append(route)
        elif request.method == "GET" and url.path in assets:
            body, mime = assets[url.path]
            route.fulfill(status=200, content_type=mime, body=body,
                          headers={"Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff"})
        elif request.method == "GET" and url.path == "/favicon.ico":
            route.fulfill(status=204, body="")
        else:
            unexpected.append(f"{request.method} {request.url}")
            route.abort()

    context.route("**/*", route_request)
    name = f"{viewport['width']}x{viewport['height']}-{'forced' if forced else 'normal'}-{scenario}"
    result = {"case": name, "passed": False, "synthetic_wall_unix_ms": now,
              "snapshot_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()}
    try:
        page.goto(ORIGIN, wait_until="networkidle")
        expect(page.locator("#seat-readings > li")).to_have_count(6)
        page.clock.run_for(350)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "horizontal overflow"
        if viewport["width"] >= 800:
            bounds = page.locator("#monitor-readings").bounding_box()
            assert bounds["y"] + bounds["height"] <= viewport["height"], "core table extends below target viewport"
        assert page.evaluate("""() => [...document.querySelectorAll('#seat-readings > li')].every(seat => {
          const dot = seat.querySelector('.seat-freshness').getBoundingClientRect();
          return [...seat.querySelectorAll('.seat-select span')].every(label => {
            const range = document.createRange(); range.selectNodeContents(label);
            return [...range.getClientRects()].every(r => r.right <= dot.left || r.left >= dot.right ||
              r.bottom <= dot.top || r.top >= dot.bottom);
          });
        })"""), "freshness marker overlaps seat text"
        if scenario in {"idle", "disconnect-first"}:
            expect(page.locator("#monitor-empty")).to_be_visible()
            expect(page.locator("#pot-reason")).to_contain_text("Insufficient context")
            expect(page.locator("#monitor-launch")).to_be_visible()
            expect(page.locator("#monitor-launch")).to_contain_text("-ManualStart")
        elif scenario == "previous":
            expect(page.locator("#monitor-stop")).to_be_visible()
            expect(page.locator("#monitor-stop")).to_contain_text("Previous session receipt")
            assert page.locator("#source-status").get_attribute("data-tone") != "okay"
        elif scenario in {"capture-failure", "previous-capture-failure"}:
            expect(page.locator("#monitor-stop")).to_be_visible()
            if scenario == "capture-failure":
                expect(page.locator("#monitor-stop")).to_contain_text("Last capture diagnostic")
                expect(page.locator("#monitor-stop")).to_contain_text("Uncover the table")
            else:
                expect(page.locator("#monitor-stop")).to_contain_text("Previous capture diagnostic")
                expect(page.locator("#monitor-empty")).to_contain_text("Previous session receipt")
                expect(page.locator("#monitor-stop")).not_to_contain_text("Uncover the table")
        elif scenario in {"native", "native-timing", "provisional"}:
            expect(page.locator("#amount-pot")).to_be_visible()
            expect(page.locator("#amount-pot")).to_have_attribute("data-reading",
                "provisional" if scenario == "provisional" else "current")
            displayed = page.locator("#amount-pot").inner_text().strip()
            if scenario != "provisional":
                assert displayed.endswith(" chips"), "native amount must declare chip units"
                displayed = displayed.removesuffix(" chips")
                expected = Decimal(raw["partial_observation"]["pot_size"]) / 100
            else:
                expected = Decimal(raw["numeric_observation"]["pot"]["literal"])
            assert Decimal(displayed.replace(",", "")) == expected, "displayed pot differs from synthetic source"
            if scenario == "provisional":
                expect(page.locator("#pot-reason")).to_be_visible()
                expect(page.locator("#pot-reason")).to_contain_text("Provisional")
            if scenario == "native-timing":
                receipts = page.evaluate("() => window.coinpokerMonitor.renderReceipts().receipts.filter(r => r.field === 'pot_size' && r.status === 'current')")
                assert len(receipts) == 1, "repeated API polls must not create new first-current receipts"
                assert receipts[0].get("native_timing") == raw["native_timing"], "stage timing must bind the original native capture"
                result["synthetic_native_timing"] = receipts[0]["native_timing"]
            page.screenshot(path=str(out / f"{name}-reading.png"), full_page=True)
            page.clock.run_for(1700)
            assert page.locator("#amount-pot").get_attribute("data-reading") not in {"current", "provisional"}
        elif scenario in {"pending-start", "pending-stop"}:
            button = page.locator("#start-capture" if scenario == "pending-start" else "#stop-capture")
            expect(button).to_have_accessible_name("Start monitor" if scenario == "pending-start" else "Stop monitor")
            button.focus()
            page.keyboard.press("Enter")
            expect(button).to_have_attribute("aria-disabled", "true")
            expect(button).to_be_focused()
            page.keyboard.press("Enter")
            assert len(pending) == 1, "repeated keyboard activation sent multiple control requests"
            pending.pop().fulfill(status=202 if scenario == "pending-start" else 200,
                                  content_type="application/json", body=json.dumps(
                                      {"ok": True, "control_id": "e" * 32} if scenario == "pending-start" else {"ok": True}))
        assert not errors, errors
        assert not unexpected, unexpected
        result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
    finally:
        result.update(polls=polls, page_errors=errors, unexpected_requests=unexpected)
        page.screenshot(path=str(out / f"{name}.png"), full_page=True)
        while pending:
            pending.pop().abort("aborted")
        context.close()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default=None, help="Installed browser channel, e.g. msedge or chrome")
    parser.add_argument("--output-dir", type=Path, default=None, help="New directory; existing outputs are refused")
    parser.add_argument("--scenario", action="append", choices=("idle", "disconnect-first", "previous", "native", "native-timing", "provisional", "pending-start", "pending-stop", "capture-failure", "previous-capture-failure"),
                        help="Run only selected scenarios; repeatable, defaults to all")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from playwright.sync_api import sync_playwright
    from laya_server_validation import CSP
    directory = args.output_dir or ROOT / ".local/browser-smoke" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    out = directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    assets = {}
    digests = {}
    for path, name, mime in (("/", "index.html", "text/html"), ("/app.js", "app.js", "text/javascript"),
                             ("/styles.css", "styles.css", "text/css")):
        data = (ROOT / "scripts/dashboard" / name).read_bytes()
        assets[path] = data, mime
        digests[name] = hashlib.sha256(data).hexdigest()
    report = {"evidence_kind": "synthetic-intercepted-real-browser", "physical_acceptance": False,
              "browser_version": None, "channel": args.channel, "asset_sha256": digests,
              "passed": False, "cases": []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, channel=args.channel)
            report["browser_version"] = browser.version
            try:
                for width, height in ((800, 600), (375, 812), (1280, 800)):
                    for forced in (False, True):
                        for scenario in args.scenario or ("idle", "disconnect-first", "previous", "native", "native-timing", "provisional", "pending-start", "pending-stop", "capture-failure", "previous-capture-failure"):
                            result = check_case(browser, out, {"width": width, "height": height}, forced, scenario, assets, CSP)
                            report["cases"].append(result)
                            print(json.dumps(result), flush=True)
            finally:
                browser.close()
        report["passed"] = bool(report["cases"]) and all(row["passed"] for row in report["cases"])
    except Exception as error:
        report["error"] = str(error)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {out / 'report.json'}", flush=True)
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
