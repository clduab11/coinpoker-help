import unittest

from scripts.tests import test_laya_dashboard_stage2 as stage2


class OriginalCaptureProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = stage2.PartialTests()
        self.fixture.setUp()

    def record(self, **changes):
        record = self.fixture.record()
        original = {"schema_version": 1, "frame_index": 42, "width": 800, "height": 613,
                    "sha256": "a" * 64, "native_source_id": "18446744073709551615",
                    "recording_session_id": "utc-1-2-practice", "capture_session_id": None,
                    "source_utc_unix_ms": record["captured_at_unix_ms"],
                    "captured_at_monotonic_ms": record["observation"]["captured_at_ms"], **changes}
        record["original_capture"] = original
        return record

    def test_original_receipt_is_projected_without_current_frame_substitution(self):
        record = self.record()
        self.fixture.state.ingest(record)
        partial = self.fixture.state.snapshot()["partial_observation"]
        capture = partial["capture"]
        self.assertEqual(capture["sequence"], 42)
        self.assertEqual(capture["sha256"], "a" * 64)
        self.assertEqual(capture["native_source_id"], "18446744073709551615")
        self.assertEqual(capture["captured_at_unix_ms"], record["captured_at_unix_ms"])
        self.assertEqual(partial["field_captures"]["pot_size"], capture)
        self.assertNotIn("seats.3.displayed_stack", partial["field_captures"])

    def test_mismatched_or_unbounded_reference_is_not_filled_from_health(self):
        for changes in ({"sha256": "bad"}, {"captured_at_monotonic_ms": 99},
                        {"source_utc_unix_ms": 1}, {"width": 801},
                        {"recording_session_id": "x" * 101}, {"capture_session_id": "../other"}):
            self.fixture.setUp()
            self.fixture.state.ingest(self.record(**changes))
            partial = self.fixture.state.snapshot()["partial_observation"]
            self.assertNotIn("capture", partial)
            self.assertEqual(partial["pot_size"], 12345)


if __name__ == "__main__":
    unittest.main()
