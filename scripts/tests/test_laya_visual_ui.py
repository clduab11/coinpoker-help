"""Offline DOM tests for provisional CPU results, never live accuracy claims."""
import copy
import json
import shutil
import subprocess
import unittest

from scripts.tests import test_laya_dashboard_stage2 as stage2

NODE_UI, dashboard = stage2.NODE_UI, stage2.dashboard


SCRIPT = NODE_UI.split("const visible = ()")[0].replace(
    "suspend, resume, loadReference };", "suspend, resume, loadReference, normalizeVisual, captureHealthy };") + r"""
accept(input.snapshot);
const panel = nodes.get('visual-panel');
if (input.scenario === 'render' || input.scenario === 'table-render') {
  assert(!panel.hidden, JSON.stringify({visual:value(input.snapshot).visual, healthy:test.captureHealthy()}));
  assert(nodes.get('visual-seats').textContent.includes('FOLD'));
  assert(nodes.get('visual-seats').textContent.includes('Visible wager: 0.1'));
  assert(nodes.get('visual-seats').textContent.includes('No action badge / provisional'));
  assert.equal(nodes.get('visual-board').childNodes.length, 4);
  assert(nodes.get('visual-source').textContent.includes(input.snapshot.visual_observation.sha256.slice(0,16)));
  assert(!nodes.get('visual-source').textContent.includes('PRIVATE'));
  if (input.scenario === 'table-render') {
    const seats=nodes.get('seat-readings').childNodes.slice(), board=nodes.get('board-cards').childNodes.slice();
    assert.equal(seats.length,6); assert.equal(board.length,5);
    assert.equal(board[0].dataset.reading,'provisional');
    assert.equal(JSON.parse(board[0].dataset.captureRef).sequence,input.snapshot.visual_observation.sequence);
    const wager=seats[0].childNodes[1].childNodes[1].childNodes[1];
    assert.equal(wager.textContent,'0.1'); assert.equal(wager.dataset.reading,'provisional');
    assert(seats[0].textContent.includes('FOLD'));
    assert.equal(seats[0].childNodes[0].childNodes[1].dataset.reading,'provisional');
    const publication=wager.dataset.publishedAtUnixMs;
    wall+=100;mono+=100;accept(input.snapshot);
    assert.equal(wager.dataset.publishedAtUnixMs,publication);
    seats.forEach((seat,i)=>assert.equal(nodes.get('seat-readings').childNodes[i],seat));
    board.forEach((card,i)=>assert.equal(nodes.get('board-cards').childNodes[i],card));
    assert(nodes.get('controls-reading').hidden);assert(nodes.get('metrics-readings').hidden);
    assert.equal(nodes.get('amount-pot').textContent,'123.45 chips');
  }
} else if (input.scenario === 'revealed-cards') {
  const seats=nodes.get('seat-readings').childNodes,shown=seats[4].childNodes[3];
  assert.equal(shown.hidden,false);assert.equal(shown.childNodes[0].textContent,'2\u2663');
  assert.equal(shown.childNodes[1].textContent,'?');assert.equal(shown.childNodes[0].dataset.reading,'provisional');
  assert(seats[3].childNodes[3].hidden,'bottom geometry does not prove exposed cards');
  assert(!seats.some(s=>s.textContent.includes('Self')));
  assert.equal(nodes.get('game-phase').textContent,'Flop');
  assert.equal(JSON.parse(shown.childNodes[0].dataset.captureRef).sha256,input.snapshot.visual_observation.sha256);
  const unknown=structuredClone(input.snapshot);unknown.event_seq+=1;unknown.visual_observation=null;accept(unknown);
  assert.equal(shown.hidden,true,'source-absent cards must not remain current');
} else if (input.scenario === 'slot-board') {
  const board=nodes.get('board-cards').childNodes;
  assert.equal(board[0].textContent,'9\u2665');assert.equal(board[1].textContent,'4\u2663');
  assert.equal(board[2].textContent,'A\u2665');assert.equal(nodes.get('game-phase').textContent,'Flop');
  assert.equal(board[0].getAttribute('data-street'),'Flop');
  assert.equal(board[3].getAttribute('data-street'),'Turn');assert.equal(board[4].getAttribute('data-street'),'River');
  const original=board[0].dataset.captureRef;
  wall+=2000;mono+=2000;const aged=structuredClone(input.snapshot);aged.event_seq+=1;
  aged.capture.last_heartbeat_unix_ms=wall-5;aged.capture_session.updated_at_unix_ms=wall-5;
  aged.visual_observation.current_uncertain=true;
  for(const row of aged.visual_observation.board_slots) {row.status='unknown';row.card=null;}
  aged.visual_observation.board.candidate_cards=null;accept(aged);
  assert.equal(board[0].textContent,'9\u2665');assert.equal(board[0].dataset.reading,'last-read');
  assert.equal(board[0].dataset.captureRef,original);assert.equal(nodes.get('game-phase').textContent,'Flop / last seen');
  const fresh=structuredClone(input.snapshot);fresh.event_seq+=2;
  const v=fresh.visual_observation;v.sequence+=1;v.captured_at_ms+=2001;v.captured_at_unix_ms=wall-50;v.expires_at_unix_ms=wall+1450;
  fresh.capture.last_heartbeat_unix_ms=wall-5;fresh.capture_session.updated_at_unix_ms=wall-5;
  v.actions.capture.sequence=v.sequence;v.actions.capture.captured_at_ms=v.captured_at_ms;
  for(const row of v.actions.seats) for(const f of [row.badge,row.visible_wager]) {
    f.source_capture=structuredClone(v.actions.capture);f.expires_at_ms=v.captured_at_ms+1500;
  }
  for(const row of v.board_slots) {row.card=null;row.status='empty';row.capture={...row.capture,sequence:v.sequence,captured_at_ms:v.captured_at_ms,captured_at_unix_ms:v.captured_at_unix_ms};}
  v.board.candidate_cards=[];v.board.board_generation=2;v.board.last_seen=null;accept(fresh);
  assert(board.every(card=>card.textContent==='-'));
  wall+=2000;mono+=2000;fresh.event_seq+=1;fresh.capture.last_heartbeat_unix_ms=wall-5;fresh.capture_session.updated_at_unix_ms=wall-5;
  accept(fresh);assert(board.every(card=>card.textContent==='-'),'empty evidence must retire earlier board');
} else if (input.scenario === 'replacement-fence') {
  const seat=nodes.get('seat-readings').childNodes[0];
  const wager=seat.childNodes[1].childNodes[1].childNodes[1];
  assert(seat.textContent.includes('Player 1'));
  assert(!seat.textContent.includes('FOLD'));
  assert.equal(wager.textContent,'-');
  const fresh=structuredClone(input.snapshot);fresh.event_seq+=1;
  const v=fresh.visual_observation;v.sequence+=2;v.captured_at_ms+=300;
  v.captured_at_unix_ms+=400;v.expires_at_unix_ms=v.captured_at_unix_ms+1500;
  v.actions.capture.sequence=v.sequence;v.actions.capture.captured_at_ms=v.captured_at_ms;
  for(const row of v.actions.seats) for(const field of [row.badge,row.visible_wager]) {
    field.source_capture=structuredClone(v.actions.capture);field.expires_at_ms=v.captured_at_ms+1500;
  }
  accept(fresh);
  assert(seat.textContent.includes('FOLD'));
  assert.equal(wager.textContent,'0.1');
} else if (input.scenario === 'expiry') {
  assert(!panel.hidden, JSON.stringify({visual:value(input.snapshot).visual, healthy:test.captureHealthy()}));
  mono=1001; wall+=1001; test.refreshClocks(); assert(panel.hidden);
  const replay=structuredClone(input.snapshot); replay.event_seq+=1; accept(replay); assert(panel.hidden);
  const fresh=structuredClone(input.snapshot); fresh.event_seq+=2; fresh.capture.last_heartbeat_unix_ms=wall;
  fresh.visual_observation.sequence+=1; fresh.visual_observation.captured_at_ms+=1001;
  fresh.visual_observation.captured_at_unix_ms+=1001; fresh.visual_observation.expires_at_unix_ms+=1001;
  const v=fresh.visual_observation;
  v.actions.capture.sequence=v.sequence; v.actions.capture.captured_at_ms=v.captured_at_ms;
  for(const seat of v.actions.seats) for(const f of [seat.badge,seat.visible_wager]) {
    f.source_capture.sequence=v.sequence; f.source_capture.captured_at_ms=v.captured_at_ms; f.expires_at_ms+=1001;
  }
  accept(fresh); assert(!panel.hidden);
  document.hidden=true; test.suspend(); assert(panel.hidden);
} else if(input.scenario==='reject') { assert(panel.hidden); }
console.log('offline provisional visual UI: PASS');
"""


@unittest.skipUnless(shutil.which("node"), "Node required")
class VisualUiTests(unittest.TestCase):
    def setUp(self):
        fixture = stage2.PartialTests()
        fixture.setUp()
        fixture.reading()
        self.value = fixture.state.snapshot()
        now = self.value["capture"]["last_heartbeat_unix_ms"]
        instance = "b" * 32
        self.value["server"]["instance_id"] = instance
        self.value["server"].update(inference_enabled=True, model_state="ready")
        self.value["capture_session"] = {"session_id": "a" * 32, "mode": "inference-enabled", "status": "capturing",
            "inference_enabled": True, "source_policy": "manual", "activity_state": "active",
            "elapsed_ms": 1000, "remaining_ms": 9000, "max_duration_ms": 10000,
            "max_frames": 1200, "recorded_frames": 1, "updated_at_unix_ms": now}
        capture = {"session_id": self.value["session_id"], "source_id": self.value["capture"]["source_id"],
            "epoch": 1, "sequence": 1, "captured_at_ms": 200}
        field = {"status": "unknown", "value": None, "source_capture": capture,
            "expires_at_ms": 1700, "human_reviewed": False}
        seats = [{"seat": seat, "badge": copy.deepcopy(field), "visible_wager": copy.deepcopy(field)} for seat in range(1, 7)]
        seats[0]["badge"].update(status="provisional", value={"value": "fold"})
        seats[0]["visible_wager"].update(status="provisional", value={"literal": "0.1"})
        seats[1]["badge"]["status"] = "clear"
        self.value["visual_observation"] = {"schema_version": 1, "provisional": True, "quality_approved": False,
            "human_reviewed": False, "service_instance_id": instance, **{k: capture[k] for k in ("session_id", "source_id", "epoch", "sequence")},
            "captured_at_ms": 200, "captured_at_unix_ms": now - 500, "expires_at_unix_ms": now + 1000,
            "width": 800, "height": 613, "sha256": "f" * 64,
            "board": {"candidate_cards": ["7c", "2d", "Kh", "7s"], "reason": None},
            "actions": {"capture": capture, "seats": seats}, "sightings": []}

    def run_ui(self, scenario, value=None):
        payload = {"snapshot": value or self.value, "scenario": scenario,
            "app": str(dashboard.ROOT / "scripts/dashboard/app.js"), "html": str(dashboard.ROOT / "scripts/dashboard/index.html")}
        result = subprocess.run(["node", "-e", SCRIPT], input=json.dumps(payload), capture_output=True,
            text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_literals_cards_and_explicit_absence_render_without_strategy_promotion(self):
        self.run_ui("render")

    def test_persistent_diagram_shows_independent_provisional_fields_and_exact_originals(self):
        self.value["partial_observation"].update(game_phase=None, board_count=None, board_slots=[None] * 5)
        self.run_ui("table-render")

    def test_old_visual_badge_and_wager_cannot_attach_to_newly_confirmed_occupant(self):
        now = self.value["capture"]["last_heartbeat_unix_ms"]
        original = self.value["visual_observation"]
        capture = {k: original[k] for k in ("service_instance_id", "session_id", "source_id", "epoch",
                                            "sha256", "width", "height")}
        capture.update(capture_session_id="a" * 32, sequence=2, captured_at_ms=250, captured_at_unix_ms=now - 250)
        self.value["table_context"] = {"schema_version": 1, "capture": capture, "expires_at_unix_ms": now + 4750,
            "role": "observing", "hero_seat": None, "table_context_id": "table-a",
            "seats": [{"seat": seat, "occupancy": "occupied", "identity": f"Player {seat}",
                       "occupant_epoch": 1, "continuity": "confirmed", "status": "confirmed",
                       "reason": "source-bound synthetic fixture", "stats": None} for seat in range(1, 7)],
            "evidence": {"role": {"status": "confirmed", "origin": "observer_controls", "hero_seat": None,
                                   "capture": copy.deepcopy(capture)}}, "occluded_regions": [], "events": []}
        self.run_ui("replacement-fence")

    def test_per_slot_flop_and_expired_last_seen_survive_unknown_without_timestamp_renewal(self):
        self.value["partial_observation"].update(game_phase=None, board_count=None, board_slots=[None] * 5)
        visual = self.value["visual_observation"]
        capture = {k: visual[k] for k in ("service_instance_id", "session_id", "source_id", "epoch", "sequence", "captured_at_ms", "captured_at_unix_ms", "sha256", "width", "height")}
        cards = ["9h", "4c", "Ah", None, None]
        visual["board"]["candidate_cards"] = None
        visual["board"]["board_generation"] = 1
        visual["board_slots"] = [{"slot": i + 1, "card": card, "status": "provisional" if card else "unknown",
                                    "capture": copy.deepcopy(capture), "bounds": [0, 0, 1, 1], "reason": "finite synthetic pixels"}
                                   for i, card in enumerate(cards)]
        visual["board"]["last_seen"] = {"status": "last_seen", "quality_approved": False, "provisional": True,
            "board_generation": 1, "board_slots": [{**copy.deepcopy(row), "status": "last_seen"} if row["card"] else
                {"slot": row["slot"], "card": None, "status": "unknown", "capture": None} for row in visual["board_slots"]]}
        self.run_ui("slot-board")

    def test_partial_visible_seat_cards_do_not_manufacture_hero_or_showdown_phase(self):
        visual = self.value["visual_observation"]
        capture = {k: visual[k] for k in ("service_instance_id", "session_id", "source_id", "epoch", "sequence", "captured_at_ms", "captured_at_unix_ms", "sha256", "width", "height")}
        rows = [{"seat": i, "cards": [], "visible_face_count": 0, "readings": [], "association_status": "unknown",
                 "identity": None, "occupant_epoch": None} for i in range(1, 7)]
        rows[4].update(visible_face_count=2, cards=["2c"], readings=[
            {"card": "2c", "status": "provisional", "capture": copy.deepcopy(capture)},
            {"card": None, "status": "unknown", "capture": copy.deepcopy(capture)}])
        visual["revealed_cards"] = {"schema_version": 1, "source": "visible_seat_cards", "quality_approved": False,
            "phase": "unknown", "capture": capture, "seats": rows}
        self.run_ui("revealed-cards")

    def test_original_expiry_duplicate_polls_and_visibility_loss_clear(self):
        self.run_ui("expiry")

    def test_wrong_source_service_epoch_and_geometry_are_rejected(self):
        for key, value in (("source_id", "1" * 16), ("service_instance_id", "c" * 32), ("epoch", 2), ("width", 900)):
            raw = copy.deepcopy(self.value)
            raw["visual_observation"][key] = value
            self.run_ui("reject", raw)

    def test_future_capture_forged_expiry_and_approval_are_rejected(self):
        for key, value in (("captured_at_unix_ms", self.value["capture"]["last_heartbeat_unix_ms"] + 1),
            ("expires_at_unix_ms", self.value["visual_observation"]["expires_at_unix_ms"] + 1), ("quality_approved", True)):
            raw = copy.deepcopy(self.value)
            raw["visual_observation"][key] = value
            self.run_ui("reject", raw)

    def test_each_literal_requires_same_original_capture_and_unreviewed_status(self):
        for key, value in (("human_reviewed", True), ("expires_at_ms", 1800)):
            raw = copy.deepcopy(self.value)
            raw["visual_observation"]["actions"]["seats"][0]["visible_wager"][key] = value
            self.run_ui("reject", raw)
        raw = copy.deepcopy(self.value)
        raw["visual_observation"]["actions"]["seats"][0]["badge"]["source_capture"]["sequence"] = 2
        self.run_ui("reject", raw)


if __name__ == "__main__":
    unittest.main()
