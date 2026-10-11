"""Synthetic Node DOM contracts, not recognition or desktop geometry tests."""

import json
import shutil
import subprocess
import unittest

from scripts.tests import test_laya_dashboard_stage2 as stage2


CHECKS = r"""
if (input.scenario === 'literal') {
  assert.equal(nodes.get('amount-pot').textContent, '123.45');
  assert(nodes.get('seat-readings').childNodes[0].textContent.includes('1.0'));
  assert(nodes.get('seat-readings').childNodes[2].textContent.includes('Occluded'));
  assert(nodes.get('seat-readings').childNodes[3].textContent.includes('0.00 chips'));
  assert(!nodes.get('field-diagnostics').textContent.includes('PRIVATE'));
} else if (input.scenario === 'recording') {
  assert(nodes.get('recorder-status').textContent.includes('capturing'));
  assert(nodes.get('recorder-budget').textContent.includes('1,200'));
  assert(nodes.get('recorder-loss').textContent.includes('3 estimated missed samples'));
  assert(nodes.get('opportunity-status').textContent.includes('deficit 18'));
  assert.equal(nodes.get('inference-status').textContent, 'Inference OFF');
  wall += 6000; mono += 6000; test.refreshClocks();
  assert(nodes.get('recorder-status').textContent.includes('status stale'));
} else if (input.scenario === 'reference-select') {
  test.loadReference();
  const topics = nodes.get('reference-topics').childNodes, articles = nodes.get('reference-sections').childNodes;
  assert.equal(topics.length, 8); assert.equal(articles.filter(x => !x.hidden).length, 1);
  topics[2].listeners.click();
  assert.equal(topics[2].getAttribute('aria-current'), 'true'); assert(!articles[2].hidden);
  const search = nodes.get('reference-search'); search.value = '54.116559'; search.listeners.input();
  assert.equal(topics.filter(x => !x.hidden).length, 1); assert(!articles[2].hidden);
  search.value = 'not_a_topic'; search.listeners.input(); assert(!nodes.get('reference-empty').hidden);
  assert.equal(articles.filter(x => !x.hidden).length, 0);
  search.value = ''; search.listeners.input(); assert.equal(topics.filter(x => !x.hidden).length, 8);
} else if (input.scenario === 'phase-independent') {
  assert(visible()); assert.equal(nodes.get('game-phase').textContent, '-');
  assert.equal(nodes.get('board-cards').childNodes.length, 3);
  assert.equal(nodes.get('amount-pot').textContent, '123.45 chips');
} else if (input.scenario === 'hero-independent') {
  assert.equal(nodes.get('source-role').textContent, 'Uncertain');
  assert.equal(nodes.get('amount-stack').textContent, '21.45');
  assert.equal(nodes.get('amount-call').textContent, '-');
  assert(!nodes.get('hero-stack-reading').hidden);
  assert.equal(nodes.get('hero-label').textContent, 'Hero / seat 2');
}
"""


@unittest.skipUnless(shutil.which("node"), "Node required for synthetic DOM contracts")
class CompanionUiTests(unittest.TestCase):
    def setUp(self):
        fixture = stage2.PartialTests()
        fixture.setUp()
        fixture.reading()
        self.snapshot = fixture.state.snapshot()

    def run_ui(self, scenario):
        payload = {"scenario": scenario, "snapshot": self.snapshot,
                   "app": str(stage2.dashboard.ROOT / "scripts/dashboard/app.js"),
                   "html": str(stage2.dashboard.ROOT / "scripts/dashboard/index.html")}
        script = stage2.NODE_UI.replace("console.log(`offline UI", CHECKS + "\nconsole.log(`offline UI")
        result = subprocess.run(["node", "-e", script, json.dumps(payload)], capture_output=True,
                                text=True, encoding="utf-8", timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_literal_amounts_reasons_and_zero_without_currency_invention(self):
        value = self.snapshot["partial_observation"]
        value["pot_size_text"] = "123.45"
        value["seats"][0]["displayed_stack_text"] = "1.0"
        value["seats"][3]["displayed_stack_text"] = "$0.00"
        value["field_statuses"]["seats.3.displayed_stack"] = {"status": "unavailable", "reason": "occluded"}
        value["field_statuses"]["PRIVATE"] = {"status": "unavailable", "reason": "PRIVATE"}
        self.run_ui("literal")

    def test_capture_only_budget_loss_deficit_and_stale_receipt(self):
        self.snapshot["server"]["inference_enabled"] = False
        self.snapshot["capture_session"] = {
            "mode": "capture-only", "status": "capturing", "inference_enabled": False,
            "elapsed_ms": 1000, "max_duration_ms": 600000, "max_frames": 1200,
            "recorded_frames": 2, "capture_failures": 1, "gap_count": 1,
            "max_gap_ms": 2000, "estimated_missed_samples": 3,
            "distinct_opportunities": 2, "target_opportunities": 20, "opportunity_deficit": 18,
            "updated_at_unix_ms": self.snapshot["capture"]["last_heartbeat_unix_ms"],
        }
        self.run_ui("recording")

    def test_topic_selection_and_search_preserve_educational_content(self):
        self.run_ui("reference-select")

    def test_phase_contradiction_does_not_clear_independent_card_identities(self):
        self.snapshot["partial_observation"].update(game_phase="preflop", board_count=0)
        self.run_ui("phase-independent")

    def test_uncertain_turn_preserves_explicit_hero_stack_not_guessed_seat_four(self):
        now = self.snapshot["capture"]["last_heartbeat_unix_ms"]
        self.snapshot["partial_observation"] = None
        self.snapshot["observation"] = {
            "generation": 1, "epoch": 1, "captured_at_unix_ms": now - 500,
            "expires_at_unix_ms": now + 1000, "remaining_ms": 1000,
            "role": "uncertain", "hero_seated": True, "hero_seat": 2, "action_required": None,
            "hero_cards": [], "board": [], "game_phase": "preflop", "controls": [], "wagers": [],
            "amounts": {"pot_size": 12345, "hero_chips": 2145, "to_call": 500},
            "amount_texts": {"hero_chips": "21.45"}, "experimental": True,
        }
        self.run_ui("hero-independent")


if __name__ == "__main__":
    unittest.main()
