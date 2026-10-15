"""Finite, offline Node DOM tests for explicit monitor lifecycle controls."""

import json
import shutil
import subprocess
import unittest

from scripts.tests import test_companion_ui as companion
from scripts.tests import test_laya_dashboard_stage2 as stage2


CHECKS = r"""
(async () => {
  const start = nodes.get('start-capture'), stop = nodes.get('stop-capture'), requests = [], timeouts = [];
  const seats = [...nodes.get('seat-readings').childNodes];
  const response = (status, data, extra = {}) => {
    let read = false;
    return { status, ok: status >= 200 && status < 300,
      headers: { get: key => key === 'content-type' ? extra.contentType || 'application/json' : extra.length || null },
      body: { getReader: () => ({ read: async () => {
        if (read) return { done: true }; read = true;
        return { done: false, value: new TextEncoder().encode(JSON.stringify(data)) };
      }, cancel: async () => {} }) } };
  };
  window.setTimeout = (callback, ms) => { timeouts.push({callback, ms}); return ++timer; };
  context.fetch = (path, options) => {
    if (options.method === 'GET') return Promise.resolve(response(200, input.snapshot));
    const entry = {path, options}; requests.push(entry);
    return new Promise((resolve, reject) => {
      Object.assign(entry, {resolve, reject});
      if (input.timeout) options.signal.addEventListener('abort', () => reject(Error('PRIVATE timeout')));
    });
  };
  const status = id => nodes.get(id + '-capture-status').textContent;
  const pulse = raw => {
    raw.capture.last_heartbeat_unix_ms = wall;
    if (raw.capture_session) raw.capture_session.updated_at_unix_ms = wall;
    return raw;
  };
  const arm = (id, state, seq, session = null) => {
    const raw = pulse(structuredClone(input.snapshot)); raw.event_seq = seq;
    Object.assign(raw.capture_control, {control_id:id, status:state, can_start:state === 'available',
      can_stop:['starting', 'running'].includes(state)});
    raw.automatic_startup = {enabled:true, status:state === 'starting' ? 'searching' : state === 'running' ? 'active' : 'stopped', stop_reason:null};
    if (state === 'running') {
      raw.source = 'live'; Object.assign(raw.capture, {state:'active', fresh_capture:true});
      Object.assign(raw.capture_session, {session_id:session || 'b'.repeat(32), status:'capturing', stop_reason:null, activity_state:'active'});
      raw.partial_observation.generation = seq;
    }
    return raw;
  };
  const mounted = () => assert(nodes.get('seat-readings').childNodes.every((seat, index) => seat === seats[index]));
  assert.equal(start.tagName, 'button'); assert.equal(stop.tagName, 'button');
  assert.equal(stop.textContent, 'Stop monitor');
  assert.equal(requests.length, 0); test.loadReference(); assert.equal(requests.length, 0);
  if (input.scenario === 'controls-disabled') {
    assert(start.disabled); await start.listeners.click(); assert.equal(requests.length, 0);
    assert(status('start').includes(input.reason), status('start'));
  } else if (input.scenario === 'controls-malformed') {
    for (const changes of input.invalid) {
      const raw = structuredClone(input.snapshot); Object.assign(raw.capture_control, changes);
      assert.equal(value(raw), null, JSON.stringify(changes));
    }
  } else if (input.scenario === 'controls-poll') {
    await test.poll(); test.refreshClocks(); await test.poll();
    test.suspend(); test.resume(); await test.poll();
    assert.equal(requests.length, 0, 'GET, page lifecycle and reference never start capture');
  } else if (input.scenario === 'controls-stop-pending' || input.scenario === 'controls-stop-active') {
    assert(start.disabled); assert(!stop.disabled);
    const pending = stop.listeners.click(); await stop.listeners.click(); assert.equal(requests.length, 1);
    assert(stop.disabled); assert.equal(timeouts.at(-1).ms, 1500);
    assert.deepEqual(JSON.parse(requests[0].options.body), {service_instance_id:input.snapshot.server.instance_id,
      session_id:input.scenario === 'controls-stop-pending' ? null : input.snapshot.capture_session.session_id,
      control_id:input.snapshot.capture_control.control_id});
    requests[0].resolve(response(200, {ok:true})); await pending;
    assert(status('stop').includes('Stop requested')); assert(stop.disabled); assert(!visible()); mounted();
    assert(nodes.get('model-status').textContent.includes('model ready'));
    assert.equal(nodes.get('history-folds').textContent, '2');
    const idle = arm(input.snapshot.capture_control.control_id, 'available', input.snapshot.event_seq + 1);
    Object.assign(idle.capture_session, {status:'stopped', stop_reason:'operator-stop', activity_state:'idle'});
    Object.assign(idle.capture, {state:'idle', fresh_capture:false}); idle.source = 'idle'; accept(idle);
    assert(!start.disabled); assert(stop.disabled); assert(status('stop').includes('model stays warm')); mounted();
  } else if (input.scenario === 'controls-stop-late') {
    assert(!stop.disabled); const pending = stop.listeners.click(), seq = input.snapshot.event_seq;
    const next = arm(input.replace === 'session' ? input.snapshot.capture_control.control_id : 'c'.repeat(32), 'running', seq + 1, 'c'.repeat(32));
    if (input.replace === 'service') next.server.instance_id = 'd'.repeat(32);
    accept(next); next.event_seq += 1; next.partial_observation.generation += 1; accept(next);
    assert(requests[0].options.signal.aborted); assert(visible());
    const pot = nodes.get('amount-pot').textContent;
    requests[0].resolve(response(200, {ok:true})); await pending;
    assert(visible()); assert.equal(nodes.get('amount-pot').textContent, pot); assert(!stop.disabled);
    assert.equal(status('stop'), ''); mounted();
  } else {
    assert(!start.disabled); const pending = start.listeners.click();
    assert(start.disabled); await start.listeners.click(); assert.equal(requests.length, 1);
    const {path, options} = requests[0];
    assert.equal(path, '/api/capture/start'); assert.equal(options.method, 'POST');
    assert.equal(options.mode, 'same-origin'); assert.equal(options.credentials, 'omit');
    assert.equal(options.cache, 'no-store'); assert.equal(options.redirect, 'error');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(options.body), {service_instance_id:input.snapshot.server.instance_id,
      control_id:input.snapshot.capture_control.control_id});
    assert(options.body.length < 200); assert.equal(timeouts.at(-1).ms, 1500);
    if (input.scenario === 'controls-start-late') {
      const next = arm('b'.repeat(32), input.nextState || 'running', input.snapshot.event_seq + 1);
      if (input.replace === 'service') next.server.instance_id = 'c'.repeat(32);
      if (input.replace === 'lifecycle') { test.suspend(); test.resume(); }
      accept(next); next.event_seq += 1; next.partial_observation.generation += 1; accept(next);
      assert(options.signal.aborted);
      const before = nodes.get('amount-pot').textContent;
      if (input.nextState === 'available') {
        assert(!start.disabled); const second = start.listeners.click(); assert.equal(requests.length, 2);
        requests[0].reject(Error('PRIVATE late failure')); await pending; assert(start.disabled);
        assert(status('start').includes('Requesting'));
        requests[1].resolve(response(202, {ok:true, control_id:'c'.repeat(32)})); await second;
        assert(status('start').includes('accepted'));
      } else {
        if (input.networkError) requests[0].reject(Error('PRIVATE late failure'));
        else requests[0].resolve(response(202, {ok:true, control_id:'d'.repeat(32)}));
        await pending; assert.equal(nodes.get('amount-pot').textContent, before);
        assert(start.disabled); assert(!status('start').includes('not confirmed')); assert(!stop.disabled);
      }
    } else if (input.scenario === 'controls-start-failure') {
      if (input.timeout) timeouts.at(-1).callback();
      else if (input.networkError) requests[0].reject(Error('PRIVATE network'));
      else requests[0].resolve(response(input.status || 202, input.response || {ok:false}, input));
      await pending; assert(!start.disabled); assert(status('start').includes(input.reason || 'not confirmed'));
      assert(!status('start').includes('PRIVATE')); assert.equal(requests.length, 1);
    } else {
      requests[0].resolve(response(202, {ok:true, control_id:'b'.repeat(32)})); await pending;
      assert(start.disabled); assert(status('start').includes('accepted'));
      await start.listeners.click(); assert.equal(requests.length, 1);
      const seq = input.snapshot.event_seq, waiting = arm('b'.repeat(32), 'starting', seq + 1);
      accept(waiting); assert(start.disabled); assert(!stop.disabled); assert(!visible()); mounted();
      assert.equal(nodes.get('source-role').textContent, 'Role unknown');
      assert.equal(nodes.get('source-status').textContent, 'Searching for table');
      const running = arm('b'.repeat(32), 'running', seq + 2); accept(running);
      running.event_seq += 1; running.partial_observation.generation += 1; accept(running);
      assert(visible()); assert(start.disabled); assert(!stop.disabled); mounted();
      assert.equal(nodes.get('history-folds').textContent, '2');
      // Retired receipts never recover, even inside the new control arm.
      const retired = structuredClone(running); retired.event_seq += 1;
      retired.capture_session.session_id = input.snapshot.capture_session.session_id;
      retired.partial_observation.generation += 1; accept(retired); assert(!visible());
    }
    assert(!status('start').includes('PRIVATE')); mounted();
  }
  console.log(`offline UI ${input.scenario}: PASS`);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline monitor controls")
class MonitorControlUiTests(unittest.TestCase):
    def setUp(self):
        fixture = companion.CompanionUiTests()
        fixture.setUp()
        fixture.sustained_session()
        self.snapshot = fixture.snapshot
        self.snapshot["server"]["instance_id"] = "a" * 32
        self.snapshot["capture_session"]["session_id"] = "a" * 32
        self.snapshot["history"] = {"state": "partial", "counts": {"folds": 2}, "gaps": 1,
                                    "events": [{"kind": "action", "action": "fold", "seat": 3}]}
        self.control("available")

    def control(self, status):
        self.snapshot["capture_control"] = {"enabled": True, "control_id": "a" * 32, "status": status,
            "can_start": status == "available", "can_stop": status in ("starting", "running")}
        if status not in ("running", "stopping"):
            self.snapshot["capture_session"].update(status="stopped", stop_reason="operator-stop", activity_state="idle")
            self.snapshot["capture"].update(state="idle", fresh_capture=False)
            self.snapshot.update(source="idle", automatic_startup={"enabled": True, "status": "stopped", "stop_reason": "operator-stop"})
        else:
            self.snapshot["capture_session"].update(status="capturing", stop_reason=None, activity_state="active")
            self.snapshot["capture"].update(state="active", fresh_capture=True)
            self.snapshot.update(source="live", automatic_startup={"enabled": True, "status": "active", "stop_reason": None})

    def run_ui(self, scenario, **extra):
        payload = {"scenario": scenario, "snapshot": self.snapshot,
                   "app": str(stage2.dashboard.ROOT / "scripts/dashboard/app.js"),
                   "html": str(stage2.dashboard.ROOT / "scripts/dashboard/index.html"), **extra}
        script = stage2.NODE_UI.replace("{ normalizeSnapshot, acceptSnapshot", "{ poll, normalizeSnapshot, acceptSnapshot")
        script = script.replace("console.log(`offline UI ${input.scenario}: PASS`);", CHECKS)
        script = script.replace("JSON.parse(fs.readFileSync(0, 'utf8'))", json.dumps(payload))
        result = subprocess.run(["node", "-"], input=script, text=True, encoding="utf-8", capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_start_is_finite_explicit_duplicate_safe_and_recovers_new_arm_not_retired_receipt(self):
        for terminal in ("stopped", "failed"):
            with self.subTest(terminal=terminal):
                self.snapshot["capture_session"].update(status=terminal, stop_reason="capture-failed" if terminal == "failed" else "operator-stop")
                self.run_ui("controls-start")

    def test_start_disabled_for_unconfigured_disabled_model_and_busy_controls(self):
        for status, reason in (("starting", "Starting"), ("running", "running"), ("stopping", "Stopping"), ("unavailable", "unavailable")):
            with self.subTest(status=status):
                self.control(status)
                self.run_ui("controls-disabled", reason=reason)
        self.control("available")
        self.snapshot["capture_control"]["enabled"] = False
        self.run_ui("controls-disabled", reason="not configured")
        self.snapshot["capture_control"]["enabled"] = True
        self.snapshot["server"]["model_state"] = "disabled"
        self.run_ui("controls-disabled", reason="Model disabled")
        del self.snapshot["capture_control"]
        self.run_ui("controls-disabled", reason="not configured")

    def test_capture_control_closed_types_and_token(self):
        self.run_ui("controls-malformed", invalid=[{"control_id": token} for token in (None, "a" * 31, "a" * 33, "A" * 32)] +
                    [{"enabled": 1}, {"can_start": "true"}, {"can_stop": None}, {"status": "PRIVATE"}])

    def test_get_poll_refresh_resume_reference_never_start_or_retry(self):
        self.run_ui("controls-poll")

    def test_start_failure_timeout_and_response_validation_never_auto_retry(self):
        for extra in ({"networkError": True}, {"timeout": True}, {"status": 500},
                      {"status": 400, "reason": "rejected"}, {"status": 403, "reason": "origin"}, {"status": 409, "reason": "no longer"},
                      {"response": {"ok": True, "control_id": "a" * 32}},
                      {"response": {"ok": True, "control_id": "B" * 32}},
                      {"response": {"ok": "true", "control_id": "b" * 32}},
                      {"response": {"ok": True, "control_id": "b" * 32, "PRIVATE": "PRIVATE"}},
                      {"contentType": "text/html"}, {"length": "9999999"}):
            with self.subTest(extra=extra):
                self.run_ui("controls-start-failure", **extra)

    def test_late_start_success_or_failure_cannot_modify_new_control_service_or_lifecycle(self):
        for replace in ("control", "service", "lifecycle"):
            for failure in (False, True):
                with self.subTest(replace=replace, failure=failure):
                    self.run_ui("controls-start-late", replace=replace, networkError=failure)
        self.run_ui("controls-start-late", nextState="available")

    def test_stop_cancels_pending_arm_with_null_session_and_keeps_slots_model_history(self):
        self.control("starting")
        self.run_ui("controls-stop-pending")

    def test_active_stop_sends_current_arm_and_capture_session(self):
        self.control("running")
        self.run_ui("controls-stop-active")

    def test_late_stop_cannot_clear_new_control_service_or_capture(self):
        self.control("running")
        for replace in ("control", "service", "session"):
            with self.subTest(replace=replace):
                self.run_ui("controls-stop-late", replace=replace)
