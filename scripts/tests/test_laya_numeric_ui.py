import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from scripts.tests.test_laya_dashboard_stage2 import NODE_UI
from scripts.tests import test_laya_visual_ui as visual_ui


SCRIPT = NODE_UI.split("const visible = ()")[0] + r"""
const seats=nodes.get('seat-readings').childNodes;
const stack=()=>seats[0].childNodes[1].childNodes[0].childNodes[1];
const wager=()=>seats[0].childNodes[1].childNodes[1].childNodes[1];
const pulse=()=>{const s=structuredClone(input.snapshot);s.event_seq+=1;s.capture.last_heartbeat_unix_ms=wall;s.capture_session.updated_at_unix_ms=wall;return s;};
accept(input.snapshot);
if(input.scenario==='fast'){
  assert.equal(nodes.get('amount-pot').textContent,'0.07');assert.equal(stack().textContent,'5.02');assert.equal(wager().textContent,'0.05');
  assert.equal(nodes.get('amount-pot').dataset.reading,'provisional');
  assert.equal(JSON.parse(stack().dataset.captureRef).sequence,2);
  assert.equal(nodes.get('source-role').textContent,'Role unknown');
  assert(!seats[0].textContent.includes('BET'));
  const next=pulse(),n=next.numeric_observation;n.capture.sequence+=1;n.capture.captured_at_unix_ms=wall-50;n.expires_at_unix_ms=wall+1450;
  const fields=[n.pot,...n.seats.flatMap(row=>[row.stack,row.wager])];for(const f of fields)f.capture=structuredClone(n.capture);
  n.pot.literal='0.12';n.pot.value=12;n.seats[0].stack.literal='4.97';n.seats[0].stack.value=497;
  n.seats[0].wager.status='empty';n.seats[0].wager.literal=n.seats[0].wager.value=null;accept(next);
  assert.equal(nodes.get('amount-pot').textContent,'0.12');assert.equal(stack().textContent,'4.97');assert.equal(wager().textContent,'-');
}else if(input.scenario==='expiry'){
  const ref=nodes.get('amount-pot').dataset.captureRef;
  wall+=1600;mono+=1600;const old=pulse();accept(old);
  assert.equal(nodes.get('amount-pot').textContent,'0.07');assert.equal(nodes.get('amount-pot').dataset.reading,'last-read');
  assert.equal(nodes.get('amount-pot').dataset.captureRef,ref);assert.equal(stack().dataset.reading,'last-read');assert.equal(wager().textContent,'-');
  wall-=1600;mono+=1;const rollback=pulse();accept(rollback);
  assert.notEqual(nodes.get('amount-pot').dataset.reading,'provisional','rollback cannot re-arm original numeric deadline');
  assert.notEqual(nodes.get('amount-pot').dataset.reading,'current');
}else if(input.scenario==='withdraw'){
  const ref=nodes.get('amount-pot').dataset.captureRef,withdrawn=pulse();
  Object.assign(withdrawn.numeric_observation.pot,{status:'unknown',literal:null,value:null});accept(withdrawn);
  assert.equal(nodes.get('amount-pot').dataset.reading,'last-read');
  accept(pulse());assert.equal(nodes.get('amount-pot').dataset.reading,'last-read');
  assert.equal(nodes.get('amount-pot').dataset.captureRef,ref);
}else if(input.scenario==='invalid'){
  assert.notEqual(nodes.get('amount-pot').dataset.reading,'provisional');
  assert.equal(nodes.get('amount-pot').textContent,'-');
}else if(input.scenario==='scope'){
  const other=pulse();other.server.instance_id='c'.repeat(32);
  accept(other);assert.equal(nodes.get('amount-pot').textContent,'-');assert.equal(stack().textContent,'-');
}else if(input.scenario==='native-older'){
  assert.equal(nodes.get('amount-pot').textContent,'0.07');assert.equal(nodes.get('amount-pot').dataset.reading,'provisional');
}else if(input.scenario==='empty-vs-visual'){
  assert.equal(wager().textContent,'-','a newer unrelated native board ticket must not restore an older visual wager');
}else if(input.scenario==='expiry-with-native'){
  assert.equal(nodes.get('amount-pot').textContent,'0.07');assert.equal(stack().textContent,'5.02');assert.equal(wager().textContent,'-');
  wall+=1600;mono+=1600;accept(pulse());
  assert.equal(nodes.get('amount-pot').textContent,'0.07');assert.equal(nodes.get('amount-pot').dataset.reading,'last-read');
  assert.equal(stack().textContent,'5.02');assert.equal(stack().dataset.reading,'last-read');
  assert.equal(wager().textContent,'-','older native wager must stay retired after newer CPU empty expires');
}
process.stdout.write(JSON.stringify({ok:true}));
"""


@unittest.skipUnless(shutil.which("node"), "node is required for numeric UI tests")
class NumericUiTests(unittest.TestCase):
    def setUp(self):
        fixture = visual_ui.VisualUiTests()
        fixture.setUp()
        self.value = fixture.value
        self.native = copy.deepcopy(self.value["partial_observation"])
        self.value["partial_observation"] = None
        visual = self.value.pop("visual_observation")
        self.visual = copy.deepcopy(visual)
        now = self.value["capture"]["last_heartbeat_unix_ms"]
        capture = {key: visual[key] for key in ("service_instance_id", "session_id", "source_id", "epoch", "sha256", "width", "height")}
        capture.update(sequence=2, captured_at_ms=400, captured_at_unix_ms=now-100, capture_session_id="a" * 32)
        def field(literal, value):
            return {"literal": literal, "value": value, "status": "provisional", "capture": copy.deepcopy(capture)}
        self.value["numeric_observation"] = {"schema_version": 1, "source": "cpu-visible-numeric",
            "provisional": True, "quality_approved": False, "capture": capture, "expires_at_unix_ms": now+1400,
            "pot": field("0.07", 7), "seats": [{"seat": seat, "stack": field("5.02", 502),
                                                     "wager": field("0.05", 5)} for seat in range(1, 7)]}

    def run_ui(self, scenario):
        app = Path(__file__).resolve().parents[1] / "dashboard/app.js"
        data = json.dumps({"scenario": scenario, "snapshot": self.value, "app": str(app), "html": str(app.with_name("index.html"))})
        result = subprocess.run([shutil.which("node"), "-e", SCRIPT, str(app)], input=data,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_fast_values_are_independent_of_native_inference_and_actions(self):
        self.run_ui("fast")

    def test_expiry_and_clock_rollback_do_not_renew_last_seen_amounts(self):
        self.run_ui("expiry")

    def test_same_receipt_cannot_reconfirm_a_withdrawn_pot(self):
        self.run_ui("withdraw")

    def test_service_replacement_clears_old_numeric_values(self):
        self.run_ui("scope")

    def test_newer_cpu_measurement_wins_over_older_native_pot(self):
        self.value["partial_observation"] = self.native
        self.run_ui("native-older")

    def test_newer_cpu_empty_wager_beats_visual_even_with_unrelated_newer_native_ticket(self):
        self.value["visual_observation"] = self.visual
        self.value["partial_observation"] = self.native
        now = self.value["capture"]["last_heartbeat_unix_ms"]
        self.native["captured_at_unix_ms"] = now-50
        self.native["expires_at_unix_ms"] = now+1450
        self.value["numeric_observation"]["seats"][0]["wager"].update(status="empty", literal=None, value=None)
        self.run_ui("empty-vs-visual")

    def test_cpu_expiry_does_not_restore_older_native_pot_stack_or_cleared_wager(self):
        self.value["partial_observation"] = self.native
        seat = self.native["seats"][0]
        seat.update(visible_wager=10, visible_wager_text="0.10", visible_wager_status="accepted")
        seat["scene_fields"] = [*(seat.get("scene_fields") or []), "visible_wager"]
        self.native["field_statuses"]["seats.1.visible_wager"] = {"status": "accepted", "reason": None}
        self.value["numeric_observation"]["seats"][0]["wager"].update(status="empty", literal=None, value=None)
        self.run_ui("expiry-with-native")

    def test_invalid_literals_minor_units_and_field_source_do_not_publish(self):
        for change in ({"literal": "0.07%"}, {"literal": "0.07", "value": 70},
                       {"value": True}, {"capture": {**self.value["numeric_observation"]["capture"], "sha256": "c" * 64}}):
            with self.subTest(change=change):
                old = copy.deepcopy(self.value["numeric_observation"]["pot"])
                self.value["numeric_observation"]["pot"].update(change)
                self.run_ui("invalid")
                self.value["numeric_observation"]["pot"] = old


if __name__ == "__main__":
    unittest.main()
