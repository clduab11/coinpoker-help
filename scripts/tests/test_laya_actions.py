"""Pure timeline tests plus optional Pillow/numpy crop recognizer tests."""

import copy
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import laya_actions as actions

HAS_PIXELS = importlib.util.find_spec("PIL") is not None and importlib.util.find_spec("numpy") is not None


def capture(sequence=1, captured_at_ms=None, **overrides):
    return {"session_id": "session_a", "source_id": "source_a", "epoch": 1,
            "sequence": sequence, "captured_at_ms": sequence * 250 if captured_at_ms is None else captured_at_ms,
            **overrides}


def result(sequence=1, labels=None, **overrides):
    source = capture(sequence, **overrides)
    labels = labels or {}
    seats = []
    for seat in range(1, 7):
        label = labels.get(seat)
        badge = {"status": "provisional" if label else "unknown", "source_capture": dict(source),
                 "value": {"value": label} if label else None, "crop_sha256": "test"}
        seats.append({"seat": seat, "badge": badge,
                      "visible_wager": {"value": None, "source_capture": dict(source)}})
    return {"capture": source, "seats": seats}


class LiteralTests(unittest.TestCase):
    def test_displayed_units_are_never_scaled_or_guessed(self):
        for literal in ("0", "0.00", "0.05", "1.07", "99999999.99"):
            value = actions.parse_wager(literal)
            self.assertEqual(value["literal"], literal)
            self.assertEqual(value["units"], "displayed_unknown")

    def test_no_amount_is_not_numeric_zero(self):
        for literal in (None, "", "unknown", "1e2", "0,05", "-1", "01", ".05", "1.", "1.234", "chips 4", 5):
            self.assertIsNone(actions.parse_wager(literal))

    def test_geometry_fixed_physical_slots_and_bounds(self):
        self.assertEqual(actions.scaled_bounds(actions.BADGE_BOUNDS[0], (900, 686)), actions.BADGE_BOUNDS[0])
        for box in (*actions.BADGE_BOUNDS, *actions.WAGER_BOUNDS):
            x0, y0, x1, y1 = actions.scaled_bounds(box, (946, 719))
            self.assertTrue(0 <= x0 < x1 <= 946 and 0 <= y0 < y1 <= 719)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.timeline = actions.ActionTimeline()

    def test_all_six_explicit_actions_stay_distinct(self):
        for index, label in enumerate(actions.ACTIONS, 1):
            event = self.timeline.observe(result(index, {1: label}))["events"][0]
            self.assertEqual(event["action"], label)
            self.assertIsNone(event["action_sequence"])
            self.assertFalse(event["complete_prefix"])
            self.assertTrue(event["provisional"])
            self.assertFalse(event["human_reviewed"])

    def test_retained_and_unknown_badges_do_not_duplicate(self):
        self.assertEqual(len(self.timeline.observe(result(1, {1: "call"}))["events"]), 1)
        self.assertEqual(self.timeline.observe(result(2, {1: "call"}))["events"], [])
        self.assertEqual(self.timeline.observe(result(3))["events"], [])
        self.assertEqual(self.timeline.observe(result(4, {1: "call"}))["events"], [])

    def test_wager_change_or_disappearance_never_creates_action(self):
        self.timeline.observe(result(1, {1: "call"}))
        frame = result(2, {1: "call"})
        frame["seats"][0]["visible_wager"]["value"] = {"literal": "4.50"}
        self.assertEqual(self.timeline.observe(frame)["events"], [])
        self.assertEqual(self.timeline.observe(result(3))["events"], [])

    def test_explicit_badge_clear_allows_new_same_action(self):
        first = self.timeline.observe(result(1, {1: "check"}))["events"][0]
        clear = result(2)
        clear["seats"][0]["badge"]["status"] = "clear"
        clear["seats"][0]["badge"]["absence_evidence"] = {"basis": "visible_no_badge_crop"}
        self.timeline.observe(clear)
        second = self.timeline.observe(result(3, {1: "check"}))["events"][0]
        self.assertNotEqual(first["occurrence"], second["occurrence"])

    def test_capture_order_is_not_gameplay_order(self):
        observed = self.timeline.observe(result(1, {1: "fold", 5: "raise"}))
        self.assertIn("simultaneous_badges", observed["gaps"])
        for event in observed["events"]:
            self.assertEqual(event["order_status"], "simultaneous_ambiguous")
            self.assertIsNone(event["action_sequence"])

    def test_context_change_does_not_reassign_retained_badge(self):
        first = self.timeline.observe(result(1, {1: "check"}), hand_id="hand1", street="flop")["events"][0]
        observed = self.timeline.observe(result(2, {1: "check"}), hand_id="hand1", street="turn")
        self.assertEqual(observed["events"], [])
        self.assertIn("retained_badge_across_context", observed["gaps"])
        self.assertEqual(first["street"], "flop")
        self.assertEqual(self.timeline.observe(result(3, {1: "check"}), hand_id="hand2", street="preflop")["events"], [])

    def test_source_epoch_reset_is_not_hand_start(self):
        self.timeline.observe(result(1, {1: "raise"}))
        observed = self.timeline.observe(result(1, {1: "raise"}, epoch=2))
        self.assertIn("source_boundary", observed["gaps"])
        self.assertIsNone(observed["events"][0]["hand_id"])
        self.assertTrue(observed["events"][0]["boundary_uncertain"])

    def test_duplicate_old_conflicting_and_nonmonotonic_captures(self):
        frame = result(2, {1: "raise"})
        self.timeline.observe(frame)
        self.assertEqual(self.timeline.observe(copy.deepcopy(frame)), {"events": [], "gaps": []})
        self.assertEqual(self.timeline.observe(result(1, {1: "call"}))["events"], [])
        self.assertIn("capture_time", self.timeline.observe(result(3, {1: "call"}, captured_at_ms=500))["gaps"])
        conflict = result(2, {1: "call"}, captured_at_ms=700)
        self.assertIn("conflicting_or_old_capture", self.timeline.observe(conflict)["gaps"])
        self.assertIn("conflicting_or_old_capture", self.timeline.observe(result(2, {1: "call"}))["gaps"])

    def test_capture_gaps_and_staleness_are_not_hidden(self):
        self.timeline.observe(result(1, {1: "check"}))
        skipped = self.timeline.observe(result(5, {1: "call"}))
        self.assertIn("capture_gap", skipped["gaps"])
        self.assertTrue(skipped["events"][0]["boundary_uncertain"])
        old = result(6, {1: "raise"})
        self.assertEqual(self.timeline.observe(old, now_ms=3000)["gaps"], ["stale_capture"])

    def test_fixed_seats_and_exact_source_are_required(self):
        frame = result()
        frame["seats"][0]["badge"]["source_capture"]["epoch"] = 2
        with self.assertRaisesRegex(ValueError, "badge-source"):
            self.timeline.observe(frame)
        frame = result()
        frame["seats"][1]["seat"] = 1
        with self.assertRaisesRegex(ValueError, "fixed-physical"):
            self.timeline.observe(frame)

    def test_history_is_bounded(self):
        for seq in range(1, actions.MAX_EVENTS + 20):
            self.timeline.observe(result(seq, {1: "call" if seq % 2 else "raise"}))
        self.assertEqual(len(self.timeline.events), actions.MAX_EVENTS)

    def test_absence_and_wager_sources_are_validated_before_mutation(self):
        frame = result(1, {1: "fold", 6: "call"})
        frame["seats"][5]["visible_wager"]["source_capture"]["epoch"] = 2
        with self.assertRaisesRegex(ValueError, "wager-source"):
            self.timeline.observe(frame)
        self.assertEqual(len(self.timeline.events), 0)
        valid = result(1, {1: "fold"})
        self.assertEqual(len(self.timeline.observe(valid)["events"]), 1)
        clear = result(2)
        clear["seats"][0]["badge"]["status"] = "clear"
        with self.assertRaisesRegex(ValueError, "badge-absence"):
            self.timeline.observe(clear)
        self.assertEqual(self.timeline.observe(result(2, {1: "fold"}))["events"], [])

    def test_caller_mutation_does_not_rewrite_recorded_provenance(self):
        frame = result(1, {1: "call"})
        event = self.timeline.observe(frame)["events"][0]
        frame["capture"]["source_id"] = "other_source"
        frame["seats"][0]["badge"]["value"]["value"] = "raise"
        self.assertEqual(event["capture"]["source_id"], "source_a")
        self.assertEqual(event["badge_evidence"]["value"]["value"], "call")


@unittest.skipUnless(HAS_PIXELS, "Pillow and numpy are not installed")
class PixelTests(unittest.TestCase):
    def word(self, text, *, fold=False):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (90, 28), (24, 80, 84))
        font = ImageFont.load_default(size=18)
        ImageDraw.Draw(image).text((4, 3), text, font=font, fill=(5, 12, 17) if fold else (255, 255, 255))
        return image

    def test_explicit_word_masks_not_colors(self):
        bank = actions.CropTemplates()
        for label in actions.ACTIONS:
            bank.add_badge(label, self.word("ALL-IN" if label == "all_in" else label.upper(), fold=label == "fold"),
                           {"path": "synthetic-word", "annotation": "test_only"})
        for label in actions.ACTIONS:
            match = bank.badge(self.word("ALL-IN" if label == "all_in" else label.upper(), fold=label == "fold"))
            self.assertEqual(match["value"], label)
            self.assertGreaterEqual(match["similarity"], bank.min_score)
        self.assertIsNone(bank.badge(self.word("ANTE")))
        self.assertIsNone(bank.badge(self.word("WINNER")))

    def test_blank_and_unknown_are_not_actions(self):
        from PIL import Image
        bank = actions.CropTemplates()
        bank.add_badge("call", self.word("CALL"), {"path": "synthetic"})
        for color in ((24, 80, 84), (255, 255, 255), (0, 0, 0)):
            self.assertIsNone(bank.badge(Image.new("RGB", (90, 28), color)))

    def test_absence_is_source_bound_pixel_match_not_unknown(self):
        from PIL import Image
        bank = actions.CropTemplates()
        image = Image.new("RGB", (90, 28), (100, 20, 35))
        self.assertIsNone(bank.badge_absence(image))
        self.assertTrue(bank.add_absent(image, {"path": "synthetic_no_badge"}))
        self.assertEqual(bank.badge_absence(image)["basis"], "visible_no_badge_crop")
        self.assertIsNone(bank.badge_absence(self.word("CALL")))
        self.assertFalse(bank.add_absent(self.word("CALL"), {"path": "not_absent"}))
        self.assertIsNone(bank.badge_absence(Image.new("RGB", image.size, (5, 80, 60))))

    def test_ambiguous_templates_return_unknown(self):
        bank = actions.CropTemplates()
        image = self.word("CALL")
        bank.add_badge("call", image, {"path": "synthetic1"})
        bank.add_badge("raise", image, {"path": "synthetic2"})
        self.assertIsNone(bank.badge(image))

    def test_wager_glyph_import_segmentation_and_literal(self):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (100, 30), (12, 45, 39))
        ImageDraw.Draw(image).text((8, 4), "0.05", font=ImageFont.load_default(size=18), fill="white")
        bank = actions.CropTemplates()
        self.assertTrue(bank.add_wager("0.05", image, {"path": "synthetic_amount"}))
        value = bank.wager(image)
        self.assertEqual(value["literal"], "0.05")
        self.assertEqual(value["units"], "displayed_unknown")
        self.assertIsNone(bank.wager(Image.new("RGB", image.size, (12, 45, 39))))


@unittest.skipUnless(HAS_PIXELS and os.environ.get("LAYA_ACTION_PRIVATE_REPLAY_PROOF") == "1",
                     "explicit private CPU pixel replay not enabled")
class PrivateAgentReferenceReplay(unittest.TestCase):
    def test_manifest_verified_originals_keep_six_explicit_action_slots(self):
        from PIL import Image
        root = SCRIPTS.parent
        directory = root / ".local/captures/utc-1791930788-730768600-practice"
        review = root / ".local/laya/datasets/observing-20261010-v2-staging/human-review-20261010/labels.draft.json"
        bank = actions.CropTemplates.from_draft_review(review, root)
        self.assertEqual({template.label for template in bank.badges}, set(actions.ACTIONS))
        rows = [json.loads(line) for line in (directory / "manifest.jsonl").read_text().splitlines()]
        by_index = {row["frame_index"]: row for row in rows if row.get("event") == "frame"}
        # Expected labels here are agent observations, NOT human ground truth.
        cases = {2: ("fold", "check", "fold", None, "fold", None),
                 50: ("fold", "check", "fold", "check", "fold", "bet"),
                 300: ("fold", "fold", "raise", "fold", None, None)}
        for index, expected in cases.items():
            row = by_index[index]
            path = directory / ("frame-%010d.png" % index)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])
            with Image.open(path) as opened:
                image = opened.convert("RGB")
            self.assertEqual(list(image.size), [row["width"], row["height"]])
            source = capture(index, captured_at_ms=row["captured_at_monotonic_ms"])
            value = actions.ActionReader(bank).read(image, source)
            actual = tuple(seat["badge"]["value"]["value"] if seat["badge"]["value"] else None
                           for seat in value["seats"])
            self.assertEqual(actual, expected)
            self.assertFalse(value["human_reviewed"])
            self.assertTrue(value["provisional"])
            for seat in value["seats"]:
                self.assertEqual(seat["badge"]["source_capture"], source)
                self.assertEqual(seat["badge"]["expires_at_ms"], source["captured_at_ms"] + 1500)
            if index == 50:
                # The wager visibly contains7, absent from the bounded donor bank.
                self.assertIsNone(value["seats"][5]["visible_wager"]["value"])


if __name__ == "__main__":
    unittest.main()
