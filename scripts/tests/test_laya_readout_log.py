"""Synthetic tests for bounded original-clock numeric diagnostics."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.tests import test_laya_dashboard_stage2 as stage2


class ReadoutLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = stage2.PartialTests()
        self.fixture.setUp()
        self.state = self.fixture.state
        self.state.begin_stream(Path(self.temp.name) / "ledger.jsonl")
        self.fixture.health()
        self.addCleanup(self.state.end_stream)
        vocabulary = stage2.dashboard.diagnostic_vocabulary(stage2.dashboard.ROOT / "crates/ingest/assets/laya/question-set.json")
        self.pass_id = next(key for key in vocabulary if key.startswith("p5_"))
        question = next(spec for spec in vocabulary[self.pass_id].values() if spec["type"] == "choice")
        self.answer = {"question": question["id"], "answer": {"type": "choice", "value": question["option_order"][0]},
                       "score": .7, "effective_floor": .95, "status": "unknown", "reason": "below-floor", "truncated": False}

    def record(self):
        return self.fixture.record(event="perception_diagnostics", frame_width=800, frame_height=613,
            passes=[{"pass": self.pass_id, "crop_bounds": [[0, 0, 4, 4]], "crop_dimensions": [[4, 4]],
                     "questions": [self.answer], "segments": {"n": 1, "overflow": False}}],
            fields=[], source_current=True, admission="candidate")

    def test_original_clocks_raw_choices_and_scores_survive_verbose_cap(self):
        self.state.diagnostics.max_bytes = 1
        original = self.record()
        self.state.ingest(original)
        self.fixture.clock.value += 2
        self.state.ingest(original)
        rows = [json.loads(line) for line in (Path(self.temp.name) / "readouts.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["captured_at_unix_ms"], original["captured_at_unix_ms"])
            self.assertEqual(row["captured_at_ms"], original["observation"]["captured_at_ms"])
            self.assertEqual(row["generation"], original["observation"]["generation"])
            self.assertEqual(row["diagnostics"]["passes"][0]["questions"][0],
                             {k: self.answer[k] for k in ("question", "answer", "score")})
        self.assertFalse(self.state.diagnostics.complete)
        self.assertTrue(self.state.readouts.complete)
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_compact_budget_end_does_not_stop_capture_or_admit_values(self):
        self.state.readouts.max_bytes = 1
        self.state.ingest(self.record())
        snapshot = self.state.snapshot()
        self.assertFalse(snapshot["readout_evidence"]["complete"])
        self.assertEqual(snapshot["readout_evidence"]["count"], 0)
        self.assertTrue(snapshot["capture"]["fresh_capture"])
        self.assertIsNone(snapshot["partial_observation"])

    def test_stream_replacement_creates_a_separate_original_clock_log(self):
        self.state.ingest(self.record())
        old = self.state.readouts
        destination = Path(self.temp.name) / "new" / "ledger.jsonl"
        self.state.begin_stream(destination)
        self.assertIsNone(old.stream)
        self.fixture.health()
        self.state.ingest(self.record())
        self.assertEqual(self.state.readouts.count, 1)
        self.assertEqual(len((destination.parent / "readouts.jsonl").read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
