"""Synthetic logic tests and opt-in, hash-bound finite original pixel replays.

Synthetic font tests are NOT source-font accuracy evidence. Private donors are
training/resubstitution. Held-out frames and changed-value crops are separate;
even those finite agent-visible checks do not certify recognition error rates.
"""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import laya_numeric as numeric
from laya_actions import CropTemplates, Template
from laya_prep import box_px

HAS_PIXELS = all(importlib.util.find_spec(name) is not None for name in ("PIL", "numpy"))
REGIONS = json.loads((ROOT / "crates/ingest/assets/laya/regions.json").read_text())


def receipt(image, sequence=1):
    # Synthetic logic receipt only, never an intake/Monitor/accuracy assertion.
    return {"session_id": "synthetic_logic", "source_id": "synthetic_pixels", "epoch": 1,
            "sequence": sequence, "captured_at_ms": sequence * 100,
            "captured_at_unix_ms": 100000 + sequence * 100,
            "width": image.width, "height": image.height,
            "sha256": hashlib.sha256(image.tobytes()).hexdigest(),
            "readability": "full", "test_only": "synthetic_logic_not_native_png"}


def canonical(row):
    return {"service_instance_id": "private_saved_replay", "session_id": "private_saved_replay",
            "source_id": "manifest_original", "capture_session_id": "fe530937b2d741d3bb8819bc36373f00",
            "native_source_id": str(row["source_id"]), "epoch": 1, "sequence": row["frame_index"],
            "captured_at_unix_ms": row["source_utc_unix_ms"],
            "captured_at_ms": row["captured_at_monotonic_ms"],
            "source_process_created_at_100ns": row["source_process_created_at_100ns"],
            "sha256": row["sha256"], "width": row["width"], "height": row["height"],
            "generation": row["generation"], "pixel_source": row["pixel_source"], "readability": row["readability"]}


class LiteralTests(unittest.TestCase):
    def test_exact_decimal_hundredths_and_zero(self):
        for literal, expected in (("0.07", 7), ("0.7", 70), ("0", 0), ("0.00", 0),
                                  ("15.35", 1535), ("1000", 100000), ("000.07", 7)):
            with self.subTest(literal=literal):
                self.assertEqual(numeric.parse_literal(literal), expected)

    def test_unsupported_formats_are_not_rounded_or_guessed(self):
        for literal in (None, 0, "", "0.007", "1,234", "1 234", "1.234", "1,23", "1k", "1K",
                        "NaN", "Infinity", "-0.07", "+0.07", " .07", ".07", "0.", "0.07 BB"):
            with self.subTest(literal=literal):
                self.assertIsNone(numeric.parse_literal(literal))


@unittest.skipUnless(HAS_PIXELS, "Pillow/numpy are unavailable")
class PixelLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image, ImageDraw, ImageFont
        cls.font = ImageFont.load_default(size=18)
        cls.bank = CropTemplates()
        for char in "0123456789":
            for kind, color in (("wager", (245, 245, 245)), ("stack", (245, 190, 25))):
                image = Image.new("RGB", (96, 28), (16, 18, 20) if kind == "stack" else (12, 45, 39))
                ImageDraw.Draw(image).text((5, 3), char + "." + char, font=cls.font, fill=color)
                for label, glyph in numeric._annotated_glyphs(image, kind, char + "." + char):
                    cls.bank.digits.append(Template(label, numeric._signature(glyph),
                        {"annotation": "synthetic_logic_not_source_font"}, numeric._hash(glyph)))

    def reader(self, bank=None, regions=None):
        return numeric.NumericReader(ROOT / "unused-private-root", regions or REGIONS, bank or self.bank)

    def line(self, text, kind="wager"):
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (140, 28), (12, 45, 39))
        ImageDraw.Draw(image).text((5, 3), text, font=self.font,
                                  fill=(245, 190, 25) if kind == "stack" else (245, 245, 245))
        return image

    def scene(self):
        from PIL import Image, ImageDraw
        reader = self.reader()
        image = Image.new("RGB", (927, 705), (15, 90, 78))
        boxes = reader._boxes(image)
        for seat in range(1, 7):
            box = boxes["stack%d" % seat]
            crop = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), (16, 18, 20))
            ImageDraw.Draw(crop).text((8, 1), "0.07", font=self.font, fill=(245, 190, 25))
            image.paste(crop, box[:2])
        return reader, image, boxes

    def test_visible_small_decimal_and_numeric_zero(self):
        reader = self.reader()
        for literal in ("0.07", "0", "0.00", "12.35"):
            result = reader._compute(self.line(literal), "wager")
            with self.subTest(literal=literal):
                self.assertEqual(result["status"], "provisional")
                self.assertEqual(result["literal"], literal)
                self.assertEqual(result["value"], numeric.parse_literal(literal))

    def test_pot_zero_requires_a_recognized_label_and_visible_digits(self):
        from PIL import Image, ImageDraw
        reader = self.reader()

        def pot(word, literal):
            crop = Image.new("RGB", (140, 28), (12, 45, 39))
            draw = ImageDraw.Draw(crop)
            draw.text((5, 3), word, font=self.font, fill=(35, 150, 225))
            draw.text((45, 3), literal, font=self.font, fill=(245, 245, 245))
            return crop

        label = reader._pot_label(pot("Pot", "0.00"))
        self.assertIsNotNone(label)
        reader.pot_labels = [Template("Pot", numeric._signature(label),
                                     {"annotation": "synthetic_logic_not_source_font"}, numeric._hash(label))]
        result = reader._compute(pot("Pot", "0.00"), "pot")
        self.assertEqual(result["literal"], "0.00")
        self.assertEqual(result["value"], 0)
        for word, literal in (("BB", "0.07"), ("Bet", "0.07"), ("Pot", ""), ("Pot", "??")):
            with self.subTest(word=word, literal=literal):
                self.assertEqual(reader._compute(pot(word, literal), "pot")["status"], "unknown")

    def test_unsupported_thousands_and_aliases_do_not_become_numbers(self):
        reader = self.reader()
        for literal in ("1,234", "1 234", "1.234", "12 BB", "ALL-IN", "WINNER", "0.07k", "1+2"):
            with self.subTest(literal=literal):
                result = reader._compute(self.line(literal), "wager")
                self.assertEqual(result["status"], "unknown")
                self.assertNotIn("value", result)

    def test_clipped_unreadable_and_detached_decimal_do_not_turn_into_integer(self):
        from PIL import Image, ImageDraw
        reader = self.reader()
        clipped = self.line("0.07").crop((8, 0, 140, 28))
        self.assertEqual(reader._compute(clipped, "wager")["status"], "unknown")
        image = self.line("007")
        ImageDraw.Draw(image).rectangle((14, 1, 16, 3), fill="white")
        self.assertEqual(reader._compute(image, "wager")["status"], "unknown")
        for color in ("black", "white", (100, 100, 100)):
            self.assertEqual(reader._compute(Image.new("RGB", (140, 28), color), "wager")["status"], "unknown")

    def test_positive_wager_absence_is_empty_not_zero_or_vacancy(self):
        from PIL import Image
        reader = self.reader()
        result = reader._compute(Image.new("RGB", (100, 40), (15, 90, 78)), "wager")
        self.assertEqual(result, {"status": "empty", "reason": "visible-felt-with-no-wager-line"})
        self.assertEqual(reader._compute(Image.new("RGB", (100, 40), (15, 90, 78)), "stack")["status"], "unknown")

    def test_ambiguous_distinct_label_is_unknown(self):
        bank = copy.deepcopy(self.bank)
        digit = next(t for t in bank.digits if t.label == "5")
        bank.digits.append(Template("8", digit.mask, {"annotation": "synthetic_ambiguous"}, digit.crop_sha256))
        self.assertEqual(self.reader(bank)._compute(self.line("5"), "wager")["status"], "unknown")

    def test_one_unknown_field_does_not_invalidate_others(self):
        from PIL import ImageDraw
        reader, image, boxes = self.scene()
        ImageDraw.Draw(image).rectangle(boxes["stack3"], fill=(16, 18, 20))
        result = reader.read(image, receipt(image))
        self.assertEqual(result["seats"][2]["stack"]["status"], "unknown")
        self.assertIsNone(result["seats"][2]["stack"]["value"])
        self.assertTrue(all(s["stack"]["value"] == 7 for s in result["seats"] if s["seat"] != 3))
        self.assertTrue(all(s["wager"]["value"] is None for s in result["seats"]))
        self.assertEqual(len(result["seats"]), 6)
        self.assertFalse(result["quality_approved"])
        self.assertFalse(result["human_reviewed"])
        self.assertNotIn("confidence", result)
        self.assertNotIn("role", result)
        self.assertNotIn("occupancy", result["seats"][2])

    def test_occlusion_source_dimensions_and_independent_fields(self):
        reader, image, boxes = self.scene()
        result = reader.read(image, receipt(image), [boxes["stack2"]])
        self.assertEqual(result["seats"][1]["stack"]["status"], "occluded")
        self.assertIsNone(result["seats"][1]["stack"]["literal"])
        self.assertEqual(result["seats"][0]["stack"]["value"], 7)
        original = receipt(image)
        original["occluded_regions"] = [list(boxes["stack4"])]
        self.assertEqual(reader.read(image, original)["seats"][3]["stack"]["status"], "occluded")
        for mask in ([[0, 0, 928, 705]], [[0, 0, 1.0, 2]], [[3, 3, 2, 2]], "bad", [None]):
            with self.subTest(mask=mask):
                failed = reader.read(image, receipt(image), mask)
                self.assertTrue(all(s["stack"]["status"] == "unknown" for s in failed["seats"]))
                self.assertEqual(failed["pot"]["status"], "unknown")

    def test_original_receipt_and_expiry_are_not_guessed(self):
        reader, image, _ = self.scene()
        source = receipt(image)
        result = reader.read(image, source)
        self.assertEqual(result["capture"], source)
        self.assertEqual(result["expires_at_unix_ms"], source["captured_at_unix_ms"] + 1500)
        for field in [result["pot"], *[s[k] for s in result["seats"] for k in ("stack", "wager")]]:
            self.assertEqual(field["capture"], source)
            self.assertEqual(field["recognizer_version"], numeric.VERSION)
            self.assertEqual(field["crop_sha256"], numeric._hash(image.crop(field["bounds"])))
        source["source_id"] = "caller_mutated"
        result["seats"][0]["stack"]["capture"]["sequence"] = 900
        repeat = reader.read(image, receipt(image))
        self.assertEqual(repeat["capture"]["source_id"], "synthetic_pixels")
        self.assertEqual(repeat["seats"][0]["stack"]["capture"]["sequence"], 1)
        self.assertEqual(repeat["expires_at_unix_ms"], 101600)
        for changes in ({"width": 890}, {"captured_at_unix_ms": True}, {"sha256": "bad"},
                        {"source_utc_unix_ms": 12}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                reader.read(image, {**receipt(image), **changes})

    def test_exact_roi_cache_has_no_receipts_and_rebinds_only_caller_receipt(self):
        reader, image, boxes = self.scene()
        with patch.object(reader, "_compute", wraps=reader._compute) as compute:
            first = reader.read(image, receipt(image))
            self.assertEqual(compute.call_count, 13)
            second = reader.read(image, receipt(image, 2))
            self.assertEqual(compute.call_count, 13)
            self.assertEqual(second["seats"][0]["stack"]["capture"]["sequence"], 2)
            self.assertEqual(first["seats"][0]["stack"]["capture"]["sequence"], 1)
            self.assertEqual(second["expires_at_unix_ms"], 101700)
            # Unrelated source pixels may change while the exact numeric ROIs do not.
            image.putpixel((0, 0), (255, 0, 0))
            reader.read(image, receipt(image, 3))
            self.assertEqual(compute.call_count, 13)
            image.putpixel(tuple(boxes["stack1"][:2]), (1, 2, 3))
            reader.read(image, receipt(image, 4))
            self.assertEqual(compute.call_count, 14)
        self.assertTrue(all("capture" not in value for value in reader._cache.values()))

    def test_geometry_and_title_bar_projection(self):
        from PIL import Image
        reader = self.reader()
        for size in ((927, 705), (890, 678)):
            boxes = reader._boxes(Image.new("RGB", size))
            self.assertEqual(boxes["pot"], box_px(REGIONS["regions"]["pot"], *size))
            for seat in range(1, 7):
                self.assertEqual(boxes["stack%d" % seat], box_px(REGIONS["regions"]["seat_%d_stack" % seat], *size))
                self.assertGreaterEqual(boxes["wager%d" % seat][1], 28)
            # The central lower chip-total and the title stakes are not Pot.
            self.assertLess(boxes["pot"][3], size[1] * .42)
            self.assertGreater(boxes["pot"][1], 200)
        bad = copy.deepcopy(REGIONS)
        bad["regions"]["pot"][0] = float("nan")
        with self.assertRaises(ValueError):
            self.reader(regions=bad)

    def test_cache_sizes_are_bounded_even_for_unfamiliar_glyphs(self):
        from PIL import Image
        reader, image, boxes = self.scene()
        with patch.object(reader, "_compute", return_value={"status": "unknown", "reason": "synthetic_cache_test"}):
            for number in range(numeric.MAX_CACHE + 8):
                image.putpixel(tuple(boxes["stack1"][:2]), (number % 256, number // 256, 3))
                reader.read(image, receipt(image, number + 1))
        self.assertLessEqual(len(reader._cache), numeric.MAX_CACHE)
        for number in range(numeric.MAX_CACHE + 8):
            glyph = Image.new("RGB", (20, 12))
            for x in range(8):
                if number & (1 << x):
                    glyph.putpixel((x + 1, 5), (255, 255, 255))
            reader._match(glyph)
        self.assertLessEqual(len(reader._glyph_cache), numeric.MAX_CACHE)


@unittest.skipUnless(HAS_PIXELS and os.environ.get("LAYA_NUMERIC_PRIVATE_SOURCE_PROOF") == "1",
                     "private hash-bound numeric source replay not enabled")
class PrivateOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        started = time.perf_counter()
        cls.reader = numeric.NumericReader(ROOT)
        cls.load_ms = (time.perf_counter() - started) * 1000
        cls.rows = {}
        for directory in (numeric.CURRENT, numeric.EARLIER):
            rows = [json.loads(line) for line in (ROOT / directory / "manifest.jsonl").read_text().splitlines()]
            cls.rows[directory] = {r["frame_index"]: r for r in rows if r.get("event") == "frame"}

    def source(self, index, directory=numeric.CURRENT):
        row = self.rows[directory][index]
        image, actual = numeric._original(ROOT, directory, index, row["sha256"], (row["width"], row["height"]))
        self.assertEqual(actual, row)
        source = canonical(row)
        if directory == numeric.EARLIER:
            source["capture_session_id"] = "70a0080b0cf74dc18fe51416b03989e6"
        return image, source

    def test_source_bank_training_and_first_frame_resubstitution_not_accuracy(self):
        self.assertEqual(self.reader.reference_count, len(numeric.REFERENCES))
        self.assertEqual(self.reader.reference_errors, [])
        self.assertEqual(set(".0123456789"), {t.label for t in self.reader.digits})
        image, source = self.source(1)
        value = self.reader.read(image, source)
        self.assertEqual([s["stack"]["literal"] for s in value["seats"]], ["5.07", "7.93", "6.64", "4.99", "2.5", "8.22"])
        self.assertEqual(value["pot"]["status"], "unknown")
        self.assertIsNone(value["pot"]["literal"])
        self.assertTrue(all(s["wager"]["value"] is None for s in value["seats"]))
        self.assertFalse(value["quality_approved"])
        self.assertFalse(value["human_reviewed"])
        print("numeric private training: %d hash-bound originals, load_ms=%.3f; NOT accuracy certification" %
              (self.reader.reference_count, self.load_ms))

    def test_distinct_heldout_current_frames_and_changed_tail_crop(self):
        # Expected values were checked with tool Read on the exact originals.
        # Repeated glyphs are expected; adjacent frames are not independent
        # statistical samples, and these labels are agent checks, not ground truth.
        cases = {
            11: ("0.07", ["5.02", "7.93", "6.64", "5", "2.5", "8.2"], {1: "0.05", 6: "0.02"}),
            51: ("0.12", ["5.07", "7.88", "6.64", "5", "2.45", "8.2"], {1: "0.02", 2: "0.05", 5: "0.05"}),
            101: ("0.07", ["5.07", "7.31", "6.59", "5", "3.12", "8.2"], {2: "0.02", 3: "0.05"}),
            201: ("0.63", ["5.07", "7.31", "6.44", "4.52", None, "8.27"], {3: "0.15", 4: "0.48"}),
            505: ("0.46", ["5.17", "6.99", "6.56", "5.03", "4.93", "8.1"], {2: "0.2"}),
        }
        donor_indices = {i for directory, i, *_ in numeric.REFERENCES if directory == numeric.CURRENT}
        for index, (pot, stacks, wagers) in cases.items():
            with self.subTest(index=index):
                self.assertNotIn(index, donor_indices)
                image, source = self.source(index)
                value = self.reader.read(image, source)
                self.assertEqual(value["pot"]["literal"], pot)
                self.assertEqual(value["pot"]["value"], numeric.parse_literal(pot))
                self.assertEqual([s["stack"]["literal"] for s in value["seats"]], stacks)
                for seat in value["seats"]:
                    expected = wagers.get(seat["seat"])
                    self.assertEqual(seat["wager"]["literal"], expected)
                    self.assertEqual(seat["wager"]["value"], numeric.parse_literal(expected))
                    if expected is None:
                        self.assertIn(seat["wager"]["status"], ("empty", "unknown"))
                self.assertEqual(value["capture"], source)
                self.assertEqual(value["expires_at_unix_ms"], source["captured_at_unix_ms"] + 1500)
                self.assertIsNone(source["generation"])
                self.assertFalse(value["quality_approved"])
                if index == 505:
                    # This actual upper-pot crop differs from every donor pot
                    # crop and from the excluded lower central chip total0.26.
                    donors = [numeric._hash(numeric._original(ROOT, d, i, sha, size)[0].crop(
                        self.reader._boxes(numeric._original(ROOT, d, i, sha, size)[0])["pot"]))
                        for d, i, sha, size, annotations in numeric.REFERENCES if any(a[0] == "pot" for a in annotations)]
                    self.assertNotIn(value["pot"]["crop_sha256"], donors)
                    self.assertNotEqual(value["pot"]["value"], 26)
                if index == 201:
                    self.assertEqual(value["seats"][4]["stack"]["status"], "unknown")
                    self.assertNotIn("occupancy", value["seats"][4])

    def test_genuine_earlier_geometry_digits_and_lower_chip_total_exclusion(self):
        image, source = self.source(1, numeric.EARLIER)
        value = self.reader.read(image, source)
        self.assertEqual(value["pot"]["literal"], "0.67")
        self.assertEqual(value["seats"][5]["stack"]["literal"], "4.77")
        self.assertTrue(all(s["wager"]["literal"] is None for s in value["seats"]))
        # A real mask suppresses the upper label, never falls back to lower0.67.
        masked = self.reader.read(image, source, [value["pot"]["bounds"]])
        self.assertEqual(masked["pot"]["status"], "occluded")
        self.assertIsNone(masked["pot"]["value"])
        self.assertEqual(masked["seats"][5]["stack"]["literal"], "4.77")

    def test_earlier_distinct_heldouts_report_actual_coverage_gaps(self):
        image, source = self.source(310, numeric.EARLIER)
        value = self.reader.read(image, source)
        self.assertEqual(value["pot"]["literal"], "0.62")
        self.assertEqual([s["stack"]["literal"] for s in value["seats"]],
                         ["6.59", "5", "7.11", "4.71", "15.35", "5.13"])
        self.assertTrue(all(s["wager"]["literal"] is None for s in value["seats"]))
        image, source = self.source(571, numeric.EARLIER)
        value = self.reader.read(image, source)
        self.assertEqual(value["pot"]["literal"], "0.07")
        self.assertEqual([s["stack"]["literal"] for s in value["seats"]], ["4.95", "5", "5.05", None, None, None])
        # Tool Read shows6.8 and4.98 in slots4/5, but those actual raster shapes
        # are below unchanged guards. Slot6 has no visible stack. NONE is not0,
        # no vacancy/action inference, and no guessed-label bank update here.
        for seat in (4, 5):
            self.assertEqual(value["seats"][seat - 1]["stack"]["reason"], "unsupported-or-ambiguous-glyph")
        self.assertEqual(value["seats"][0]["wager"]["literal"], "0.05")
        self.assertEqual(value["seats"][4]["wager"]["literal"], "0.02")
        self.assertFalse(value["quality_approved"])
        self.assertFalse(value["human_reviewed"])

    def test_private_original_wrong_hash_and_annotation_mismatch_reject(self):
        with self.assertRaises(ValueError):
            numeric._original(ROOT, numeric.CURRENT, 1, "0" * 64, (927, 705))
        image, _ = self.source(11)
        crop = image.crop(self.reader._boxes(image)["pot"])
        with self.assertRaises(ValueError):
            numeric._annotated_glyphs(crop, "pot", "007")
        with self.assertRaises(ValueError):
            numeric._annotated_glyphs(crop, "pot", ".007")

    @unittest.skipUnless(os.environ.get("LAYA_NUMERIC_PRIVATE_BENCHMARK") == "1",
                         "finite private benchmark not enabled")
    def test_finite_original_processing_and_cache_timings(self):
        reader = numeric.NumericReader(ROOT)
        samples, cached = [], []
        for index in (11, 51, 101, 201, 505):
            image, source = self.source(index)
            reader._cache.clear()
            samples.append(reader.read(image, source)["processing_ms"])
            for _ in range(8):
                # Same ORIGINAL receipt, not a made-up new source clock/lease.
                value = reader.read(image, source)
                self.assertEqual(value["expires_at_unix_ms"], source["captured_at_unix_ms"] + 1500)
                cached.append(value["processing_ms"])
        print("numeric finite13fields: newROI min/median/max_ms=%.3f/%.3f/%.3f; exactROIcache40 min/median/max_ms=%.3f/%.3f/%.3f" %
              (min(samples), statistics.median(samples), max(samples), min(cached), statistics.median(cached), max(cached)))
        self.assertTrue(all(0 <= n < 10000 for n in samples + cached))
        # Timings are observations, deliberately not a flaky hard real-time gate.


if __name__ == "__main__":
    unittest.main()
