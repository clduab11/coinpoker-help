"""Finite synthetic invariants; opt-in originals are negative evidence, not labels."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from scripts import laya_board as board
from scripts import laya_showdown as showdown


ROOT = Path(__file__).resolve().parents[2]
PATTERNS = {
    "A": ("00100", "01010", "10001", "11111", "10001", "10001", "10001"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}
ANCHORS = ((407, 64), (734, 115), (746, 381), (407, 505), (70, 381), (82, 115))


def face(card="Ad"):
    """Generic test raster, deliberately not a captured client's font."""
    image = Image.new("RGB", (42, 60), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    colour = (185, 15, 25) if card[1] in "dh" else (12, 12, 12)
    for y, row in enumerate(PATTERNS[card[0]]):
        for x, bit in enumerate(row):
            if bit == "1":
                draw.rectangle((4 + x * 2, 3 + y * 2, 5 + x * 2, 4 + y * 2), fill=colour)
    if card[1] == "d":
        draw.polygon(((9, 25), (14, 30), (9, 35), (4, 30)), fill=colour)
    elif card[1] == "h":
        draw.ellipse((4, 25, 9, 30), fill=colour)
        draw.ellipse((9, 25, 14, 30), fill=colour)
        draw.polygon(((4, 28), (14, 28), (9, 36)), fill=colour)
    elif card[1] == "c":
        draw.ellipse((7, 25, 12, 30), fill=colour)
        draw.ellipse((4, 28, 10, 33), fill=colour)
        draw.ellipse((9, 28, 15, 33), fill=colour)
        draw.rectangle((9, 30, 10, 37), fill=colour)
    else:
        draw.polygon(((9, 25), (4, 31), (6, 34), (9, 32), (12, 34), (14, 31)), fill=colour)
        draw.rectangle((8, 31, 10, 37), fill=colour)
    return image


def library():
    metadata, bitmaps = [], {}
    for red, suit in ((True, "d"), (False, "s")):
        for label in PATTERNS:
            feature = showdown.face_features(face(label + suit))["features"]["rank"]
            key = "rank-%s-%s" % (red, label)
            metadata.append({"id": key, "kind": "rank", "label": label, "w": feature["w"],
                             "h": feature["h"], "red": red, "source": "synthetic-test-only"})
            bitmaps[key] = feature["bitmap"]
    for label in "dhcs":
        feature = showdown.face_features(face("A" + label))["features"]["suit"]
        key = "suit-" + label
        metadata.append({"id": key, "kind": "suit", "label": label, "w": feature["w"],
                         "h": feature["h"], "red": label in "dh", "source": "synthetic-test-only"})
        bitmaps[key] = feature["bitmap"]
    return board.BoardTemplateRecognizer(metadata, bitmaps)


def capture(image, **changes):
    return {"session_id": "synthetic-unit-only", "source_id": "unit-table", "epoch": 1,
            "sequence": 1, "captured_at_ms": 100, "captured_at_unix_ms": 1000100,
            "width": image.width, "height": image.height, "sha256": "a" * 64,
            "service_instance_id": "unit-service", "capture_session_id": "unit-session",
            "native_source_id": "123", **changes}


def frame():
    return Image.new("RGB", showdown.REFERENCE_SIZE, (22, 94, 63))


def pair(image, seat=1, cards=("Ad", "Ks"), shift=(0, 0)):
    x, y = ANCHORS[seat - 1]
    x, y = x + shift[0], y + shift[1]
    boxes = []
    for index, card in enumerate(cards):
        crop = face(card)
        box = [x + index * 48, y, x + index * 48 + crop.width, y + crop.height]
        image.paste(crop, box)
        boxes.append(box)
    return boxes


def current_roster(receipt, **changes):
    rows = [{"seat": n, "identity": "Player%d" % n, "occupant_epoch": 1,
             "occupancy": "occupied", "status": "confirmed", "continuity": "confirmed",
             "capture": copy.deepcopy(receipt), "table_context_id": "unit-table-context"} for n in range(1, 7)]
    return {"seats": rows, "capture": copy.deepcopy(receipt), "table_context_id": "unit-table-context", **changes}


class RevealedCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.regions = json.loads((ROOT / "crates/ingest/assets/laya/regions.json").read_text())["regions"]
        cls.bank = library()

    def setUp(self):
        self.reader = showdown.RevealedCardReader(self.bank, self.regions)

    def read(self, image, **kwargs):
        return self.reader.read(image, capture(image), **kwargs)

    def test_all_six_physical_seats_are_pixel_detected_and_not_hero(self):
        for seat in range(1, 7):
            with self.subTest(seat=seat):
                image = frame()
                boxes = pair(image, seat)
                result = self.read(image)
                row = result["seats"][seat - 1]
                self.assertEqual(row["cards"], ["Ad", "Ks"])
                self.assertEqual(row["status"], "provisional")
                self.assertEqual(row["bounds"], showdown._hull(boxes))
                self.assertEqual([r["bounds"] for r in row["readings"]], boxes)
                self.assertEqual(row["face_bounds"], boxes)
                self.assertEqual(row["visible_face_count"], 2)
                self.assertTrue(all(r["status"] == "provisional" for r in row["readings"]))
                self.assertEqual(row["association_status"], "unknown")
                self.assertIsNone(row["identity"])
                self.assertIsNone(row["occupant_epoch"])
                self.assertEqual(row["observation"], "revealed_cards")
                self.assertEqual(result["phase"], "unknown")
                self.assertNotIn("hero_seat", result)
                self.assertNotIn("hero_cards", result)
                self.assertNotIn("role", result)
                self.assertFalse(result["quality_approved"])
                self.assertEqual(len(result["seats"]), 6)
                json.dumps(result, allow_nan=False)

    def test_live_white_bounds_follow_translation_not_fixed_rank_crop(self):
        image = frame()
        first = self.read(image)
        self.assertFalse(any(s["cards"] for s in first["seats"]))
        boxes = pair(image, shift=(13, 15))
        result = self.read(image)["seats"][0]
        self.assertEqual(result["cards"], ["Ad", "Ks"])
        self.assertEqual([r["bounds"] for r in result["readings"]], boxes)
        self.assertEqual(result["readings"][0]["glyph_bounds"]["rank"], [boxes[0][0] + 4, boxes[0][1] + 3,
                                                                        boxes[0][0] + 14, boxes[0][1] + 17])

    def test_actual_board_font_dependency_abstains_for_unsupported_seat_font(self):
        from scripts.tests.test_laya_board import library as board_library
        meta, pixels = board_library()
        reader = showdown.RevealedCardReader(board.BoardTemplateRecognizer(meta, pixels), self.regions)
        image = frame()
        pair(image)
        row = reader.read(image, capture(image))["seats"][0]
        self.assertEqual(row["cards"], [])
        self.assertEqual(row["status"], "unknown")
        self.assertTrue(all(r["reason"].startswith("unsupported-glyph-template:") for r in row["readings"]))

    def test_backs_blank_partial_missing_suit_and_colours_never_fill_cards(self):
        for kind in ("back", "blank", "partial", "missing_suit", "mixed_colour"):
            with self.subTest(kind=kind):
                image = frame()
                boxes = pair(image)
                draw = ImageDraw.Draw(image)
                for box in boxes:
                    if kind == "back":
                        draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=(160, 20, 50))
                    elif kind == "blank":
                        draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=(245, 245, 245))
                    elif kind == "partial":
                        draw.rectangle((box[0], box[1] + 28, box[2] - 1, box[3] - 1), fill=(22, 94, 63))
                    else:
                        draw.rectangle((box[0] + 2, box[1] + 21, box[0] + 19, box[1] + 39), fill=(245, 245, 245))
                        if kind == "mixed_colour":
                            opposite = (12, 12, 12) if box == boxes[0] else (185, 15, 25)
                            draw.polygon(((box[0] + 9, box[1] + 25), (box[0] + 14, box[1] + 30),
                                          (box[0] + 9, box[1] + 35), (box[0] + 4, box[1] + 30)), fill=opposite)
                row = self.read(image)["seats"][0]
                self.assertEqual(row["cards"], [])
                self.assertEqual(row["status"], "unknown")

    def test_one_readable_card_stays_incomplete_not_invented_pair(self):
        image = frame()
        pair(image, cards=("Ad",))
        row = self.read(image)["seats"][0]
        self.assertEqual(row["cards"], ["Ad"])
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["visible_face_count"], 1)
        self.assertEqual(row["reason"], "incomplete-or-unsupported-face-pair")
        self.assertEqual(row["observation"], "revealed_cards")

    def test_adjacent_faces_need_pair_alignment_and_no_extra_candidates(self):
        for change in ("offset", "third", "overlapping"):
            with self.subTest(change=change):
                image = frame()
                boxes = pair(image)
                if change == "offset":
                    image.paste((22, 94, 63), boxes[1])
                    image.paste(face("Ks"), (boxes[1][0], boxes[1][1] + 25))
                elif change == "third":
                    image.paste(face("7h"), (boxes[0][0] - 45, boxes[0][1]))
                else:
                    image.paste((22, 94, 63), boxes[1])
                    image.paste(face("Ks"), (boxes[0][0] + 24, boxes[0][1]))
                row = self.read(image)["seats"][0]
                self.assertNotEqual(row["status"], "provisional")
                self.assertEqual(row["cards"], [])

    def test_two_visible_fan_roofs_are_detected_but_flat_merged_shapes_are_not_split(self):
        import numpy as np
        image = frame()
        first = face("Ad").convert("RGBA").rotate(4, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))
        second = face("Ks").convert("RGBA").rotate(-4, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))
        image.paste(first, (408, 64), first)
        image.paste(second, (450, 64), second)
        row = self.read(image)["seats"][0]
        self.assertEqual(len(row["readings"]), 2)
        self.assertTrue(all(abs(r.get("deskew_degrees", 0)) > 1 for r in row["readings"]))
        rgb = np.asarray(image.convert("RGB"), dtype="int16")
        white = showdown._white(rgb)
        ys, xs = np.nonzero(white)
        self.assertEqual(row["bounds"], [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1])
        self.assertEqual(self.read(image)["phase"], "unknown")
        image = frame()
        image.paste(face("Ad"), (408, 64))
        image.paste(face("Ks"), (440, 64))
        self.assertEqual(self.read(image)["seats"][0]["cards"], [])

    def test_occlusions_clear_labels_and_preserve_exact_original_receipt(self):
        image = frame()
        boxes = pair(image)
        receipt = capture(image, occluded_regions=[boxes[0]])
        result = self.reader.read(image, receipt)
        self.assertEqual(result["capture"], receipt)
        row = result["seats"][0]
        self.assertEqual(row["status"], "occluded")
        self.assertEqual(row["cards"], [])
        self.assertEqual(row["capture"], receipt)
        self.assertEqual(row["bounds"], showdown._hull(boxes))
        clear = self.reader.read(image, capture(image))
        explicit = self.reader.read(image, capture(image), occluded_regions=[boxes[1]])
        self.assertEqual(clear["seats"][0]["status"], "provisional")
        self.assertEqual(explicit["seats"][0]["status"], "occluded")
        self.assertEqual(explicit["seats"][0]["cards"], [])
        receipt["sequence"] = 999
        self.assertEqual(row["capture"]["sequence"], 1)

    def test_transparent_or_geometry_changed_images_are_unknown(self):
        image = frame()
        pair(image)
        transparent = image.convert("RGBA")
        transparent.putalpha(128)
        distorted = image.resize((1100, 678))
        for candidate in (transparent, distorted):
            rows = self.read(candidate)["seats"]
            self.assertTrue(all(not s["cards"] and s["status"] == "unknown" for s in rows))

    def test_roster_binding_is_exact_capture_table_occupant_and_no_history(self):
        image = frame()
        pair(image, seat=3)
        receipt = capture(image)
        roster = current_roster(receipt)
        result = self.reader.read(image, receipt, roster=roster, table_context_id="unit-table-context")
        row = result["seats"][2]
        self.assertEqual((row["identity"], row["occupant_epoch"], row["association_status"]), ("Player3", 1, "confirmed"))
        roster["seats"][2].update(identity="Replacement", occupant_epoch=2)
        new = self.reader.read(image, receipt, roster=roster, table_context_id="unit-table-context")["seats"][2]
        self.assertEqual((new["identity"], new["occupant_epoch"]), ("Replacement", 2))
        unreadable = self.reader.read(frame(), capture(frame()), roster=None)["seats"][2]
        self.assertEqual(unreadable["cards"], [])
        self.assertIsNone(unreadable["identity"])
        self.assertNotIn("last_seen", unreadable)
        self.assertEqual(row["identity"], "Player3")

    def test_stale_foreign_ambiguous_or_provisional_owner_cannot_attach(self):
        image = frame()
        pair(image)
        receipt = capture(image)
        for change in ("sequence", "sha256", "clock", "service", "native", "table", "epoch", "status", "duplicate"):
            with self.subTest(change=change):
                roster = current_roster(receipt)
                row = roster["seats"][0]
                if change in ("sequence", "sha256", "service", "native", "clock"):
                    field, value = {"sequence": ("sequence", 2), "sha256": ("sha256", "b" * 64),
                                    "service": ("service_instance_id", "foreign"), "native": ("native_source_id", "456"),
                                    "clock": ("captured_at_ms", 101)}[change]
                    row["capture"][field] = value
                elif change == "table":
                    row["table_context_id"] = "foreign"
                elif change == "epoch":
                    row["occupant_epoch"] = None
                elif change == "status":
                    row.update(status="provisional", continuity="uncertain")
                else:
                    roster["seats"][1]["identity"] = row["identity"]
                result = self.reader.read(image, receipt, roster=roster, table_context_id="unit-table-context")["seats"][0]
                self.assertEqual(result["cards"], ["Ad", "Ks"])
                self.assertIsNone(result["identity"])
                self.assertIsNone(result["occupant_epoch"])
                self.assertEqual(result["association_status"], "unknown")

    def test_known_private_hero_requires_separate_explicit_public_reveal(self):
        for hero in range(1, 7):
            image = frame()
            pair(image, seat=hero)
            receipt = capture(image)
            roster = current_roster(receipt, role="seated_waiting", hero_seat=hero,
                                    evidence={"role": {"status": "provisional", "origin": "self_player",
                                                       "capture": receipt, "hero_seat": hero}})
            result = self.reader.read(image, receipt, roster=roster, table_context_id="unit-table-context")
            row = result["seats"][hero - 1]
            self.assertEqual(row["cards"], [])
            self.assertEqual(row["reason"], "known-self-private-cards-excluded")
            box = [225, 550, 305, 575]
            roster["evidence"]["revealed_cards"] = {"origin": "client_revealed_cards", "literal": "SHOWS",
                "capture": receipt, "status": "provisional", "bounds": box,
                "crop_sha256": showdown._pixel_hash(image.crop(box)), "seats": [hero]}
            public = self.reader.read(image, receipt, roster=roster, table_context_id="unit-table-context")
            self.assertEqual(public["seats"][hero - 1]["cards"], ["Ad", "Ks"])
            self.assertEqual(public["phase"], "unknown")
            self.assertNotIn("hero_seat", public)

    def test_phase_requires_external_current_pixel_bound_client_text_not_five_cards(self):
        image = frame()
        pair(image)
        receipt = capture(image)
        box = [225, 550, 305, 575]
        proof = {"origin": "client_showdown", "literal": "SHOWDOWN", "capture": receipt,
                 "status": "provisional", "bounds": box, "crop_sha256": showdown._pixel_hash(image.crop(box))}
        with mock.patch.object(self.bank, "recognize_frame", return_value={"slots": [{"card": c} for c in ("Ah", "Kd", "7c", "9h", "As")]}):
            result = self.reader.read(image, receipt)
        self.assertEqual(result["phase"], "unknown")
        result = self.reader.read(image, receipt, roster={"seats": [], "evidence": {"showdown": proof}})
        self.assertEqual(result["phase"], "showdown")
        for mutation in ({"literal": "ALL-IN"}, {"origin": "board_five"}, {"crop_sha256": "0" * 64},
                         {"capture": {**receipt, "sequence": 2}}, {"status": "unknown"}, {"bounds": [-1, 0, 5, 5]}):
            result = self.reader.read(image, receipt, roster={"seats": [], "evidence": {"showdown": {**proof, **mutation}}})
            self.assertEqual(result["phase"], "unknown")
        covered = self.reader.read(image, receipt, occluded_regions=[box], roster={"seats": [], "evidence": {"showdown": proof}})
        self.assertEqual(covered["phase"], "unknown")

    def test_duplicate_inside_pair_across_seats_and_against_board_is_unknown(self):
        for kind in ("pair", "seats", "board"):
            with self.subTest(kind=kind):
                image = frame()
                pair(image, cards=("Ad", "Ad") if kind == "pair" else ("Ad", "Ks"))
                if kind == "seats":
                    pair(image, seat=2, cards=("Ad", "7h"))
                board_result = {"slots": [{"card": "Ad"}]} if kind == "board" else {"slots": []}
                with mock.patch.object(self.bank, "recognize_frame", return_value=board_result):
                    result = self.read(image)
                self.assertEqual(result["seats"][0]["cards"], [])
                self.assertEqual(result["seats"][0]["status"], "unknown")
                self.assertEqual(result["seats"][0]["reason"], "scene-duplicate-card-conflict")
                self.assertTrue(result["conflicts"])
                if kind == "seats":
                    self.assertEqual(result["seats"][1]["cards"], [])

    def test_board_pixels_and_overlapping_seat_ownership_are_not_relabels(self):
        image = frame()
        image.paste(face("Ad"), (295, 280))
        image.paste(face("Ks"), (345, 280))
        regions = {**self.regions, "seat_1_revealed_cards_search": [.29, .38, .48, .55]}
        result = showdown.RevealedCardReader(self.bank, regions).read(image, capture(image))
        self.assertFalse(any(s["cards"] for s in result["seats"]))
        image = frame()
        pair(image)
        regions = {**self.regions, "seat_2_revealed_cards_search": [359 / 890, (45 - 28) / 650,
                                                               530 / 890, (195 - 28) / 650]}
        result = showdown.RevealedCardReader(self.bank, regions).read(image, capture(image))
        self.assertEqual(result["seats"][0]["reason"], "ambiguous-physical-seat")
        self.assertFalse(any(s["cards"] for s in result["seats"]))

    def test_invalid_provenance_geometry_masks_and_roster_are_rejected(self):
        image = frame()
        for change in ({"sha256": "bad"}, {"width": 891}, {"sequence": True}, {"captured_at_ms": -1},
                       {"source_id": "../outside"}, {"native_source_id": True}, {"captured_at_unix_ms": float("nan")}):
            with self.assertRaises(ValueError):
                self.reader.read(image, capture(image, **change))
        for mask in ([-1, 0, 20, 20], [0, 0, 20.5, 20], [0, 0, 0, 1]):
            with self.assertRaises(ValueError):
                self.read(image, occluded_regions=[mask])
        with self.assertRaises(ValueError):
            self.read(image, roster=[{"seat": 1}, {"seat": 1}])
        with self.assertRaises(ValueError):
            self.read(image, table_context_id="../table")
        regions = {**self.regions, "seat_1_revealed_cards_search": [0, float("nan"), .5, .6]}
        with self.assertRaises(ValueError):
            showdown.RevealedCardReader(self.bank, regions).read(image, capture(image))

    def test_original_intake_pins_png_and_exact_native_row_not_later_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = frame()
            pair(image)
            png = directory / "frame-0000000001.png"
            image.save(png)
            raw = png.read_bytes()
            receipt = capture(image, sha256=hashlib.sha256(raw).hexdigest(), recording_session_id=directory.name)
            record = {"event": "frame", "frame_index": 1, "source_utc_unix_ms": receipt["captured_at_unix_ms"],
                      "captured_at_monotonic_ms": receipt["captured_at_ms"], "width": image.width,
                      "height": image.height, "source_id": 123, "sha256": receipt["sha256"], "png_bytes": len(raw)}
            manifest = directory / "manifest.jsonl"
            manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")
            result = self.reader.read_original(png, manifest, receipt)
            self.assertEqual(result["seats"][0]["cards"], ["Ad", "Ks"])
            self.assertEqual(result["capture"], receipt)
            self.assertEqual(result["original_png_verification"], "sha256-and-native-manifest")
            for change in ({"captured_at_ms": 101}, {"captured_at_unix_ms": 1000101}, {"native_source_id": "456"},
                           {"sha256": "b" * 64}, {"sequence": 2}, {"recording_session_id": "foreign"}):
                with self.assertRaises(ValueError):
                    self.reader.read_original(png, manifest, {**receipt, **change})
            manifest.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate-manifest-frame"):
                self.reader.read_original(png, manifest, receipt)

    def test_original_intake_rejects_incomplete_rows_duplicate_keys_and_boolean_clocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = frame()
            png = directory / "frame-0000000001.png"
            image.save(png)
            raw = png.read_bytes()
            receipt = capture(image, captured_at_ms=0, sha256=hashlib.sha256(raw).hexdigest())
            record = {"event": "frame", "frame_index": 1, "source_utc_unix_ms": receipt["captured_at_unix_ms"],
                      "captured_at_monotonic_ms": 0, "width": image.width, "height": image.height,
                      "source_id": 123, "sha256": receipt["sha256"], "png_bytes": len(raw)}
            manifest = directory / "manifest.jsonl"
            for text in (json.dumps(record), json.dumps({**record, "captured_at_monotonic_ms": False}) + "\n",
                         json.dumps(record)[:-1] + ',"frame_index":1}\n'):
                manifest.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.reader.read_original(png, manifest, receipt)

    @unittest.skipUnless(os.environ.get("LAYA_SHOWDOWN_PRIVATE_SAVED_SCAN") == "1", "finite saved prefix intake opt-in")
    def test_private_recorded_prefix_candidate_intake_not_label_or_phase_qualification(self):
        import io
        import numpy as np
        session = "utc-1791991640-171220300-practice"
        directory = ROOT / ".local/captures" / session
        with (directory / "manifest.jsonl").open("rb") as handle:
            raw = handle.read(showdown.MAX_MANIFEST_BYTES + 1)
        self.assertLessEqual(len(raw), showdown.MAX_MANIFEST_BYTES)
        rows = [board._json(line) for line in raw.split(b"\n")[:-1] if line.strip()]
        rows = [r for r in rows if r.get("event") == "frame"][:1200]
        self.assertTrue(rows)
        seen, candidates, checked = set(), [], 0
        for record in rows:
            path = directory / ("frame-%010d.png" % record["frame_index"])
            with path.open("rb") as handle:
                png = handle.read(showdown.MAX_PNG_BYTES + 1)
            self.assertLessEqual(len(png), showdown.MAX_PNG_BYTES)
            self.assertEqual(hashlib.sha256(png).hexdigest(), record["sha256"])
            with Image.open(io.BytesIO(png)) as original:
                self.assertEqual(list(original.size), [record["width"], record["height"]])
                rgb = np.asarray(original.convert("RGB"), dtype="int16")
            for number, reference in enumerate(showdown.SEAT_SEARCH_BOUNDS, 1):
                box = showdown._scaled_search(reference, (record["width"], record["height"]))
                crop = rgb[box[1]:box[3], box[0]:box[2]]
                key = (number, hashlib.sha256(crop.tobytes()).hexdigest())
                if key in seen:
                    continue
                seen.add(key)
                faces, _ = showdown._faces(rgb, box, (record["width"], record["height"]))
                # Intake also flags merged/short white shapes for inspection;
                # they are NOT accepted card rectangles or recovered labels.
                broad = [c for c in showdown._components(showdown._white(crop))
                         if 30 <= c["x1"] - c["x0"] <= 150 and 30 <= c["y1"] - c["y0"] <= 125
                         and c["area"] >= 900 and c["area"] / ((c["x1"] - c["x0"]) * (c["y1"] - c["y0"])) >= .60]
                if faces or broad:
                    candidates.append({"sequence": record["frame_index"], "sha256": record["sha256"], "seat": number,
                                       "face_bounds": faces, "broad_bounds": [[box[0] + c["x0"], box[1] + c["y0"],
                                                                                box[0] + c["x1"], box[1] + c["y1"]] for c in broad]})
            checked += 1
        print("SAVED_SOURCE_INTAKE_ONLY " + json.dumps({"recording": session, "checked_originals": checked,
              "candidate_count": len(candidates), "first_candidates": candidates[:12], "quality_approved": False}))

    @unittest.skipUnless(os.environ.get("LAYA_SHOWDOWN_PRIVATE_SOURCE_PROOF") == "1", "private originals negative proof opt-in")
    def test_exact_originals_back_only_not_actual_showdown_or_card_labels(self):
        sources = (("utc-1791952251-581261300-practice", 1, "25a9ed1a28dd3d3c613e1c49af0095f21ea260c3674e86211cd8346cbfdc1b52"),
                   ("utc-1791942831-290126500-practice", 177, "a9c1ccff1d4d9d9f1b154e2c0ddc36331effdcf4149c6a0072597ece28e780bc"),
                   ("utc-1791991640-171220300-practice", 1, "4b2dddd4439028d3abf52ec1dba3c6d5efc0fc2b0035df1e51450e7add35a2ac"),
                   ("utc-1791991640-171220300-practice", 571, "0fac0afdc1e25568fd21c4bc6ca9afd1a7ea75eaad93f757e98739f9d57ef4c5"))
        for session, sequence, expected_sha in sources:
            with self.subTest(recording=session, sequence=sequence):
                directory = ROOT / ".local/captures" / session
                rows = [json.loads(line) for line in (directory / "manifest.jsonl").read_text().splitlines() if line.strip()]
                record = next(row for row in rows if row.get("event") == "frame" and row.get("frame_index") == sequence)
                self.assertEqual(record["sha256"], expected_sha)
                receipt = {"session_id": session, "source_id": "private-source-intake", "epoch": 1,
                           "sequence": sequence, "captured_at_ms": record["captured_at_monotonic_ms"],
                           "captured_at_unix_ms": record["source_utc_unix_ms"], "sha256": record["sha256"],
                           "width": record["width"], "height": record["height"],
                           "native_source_id": str(record["source_id"]), "recording_session_id": session,
                           "clock_origin": "native_original_recording;not_live_monitor_replay",
                           "occluded_regions": record.get("occluded_regions", [])}
                result = self.reader.read_original(directory / ("frame-%010d.png" % sequence), directory / "manifest.jsonl", receipt)
                self.assertFalse(any(s["cards"] for s in result["seats"]))
                self.assertEqual(result["phase"], "unknown")
                self.assertEqual(result["capture"]["captured_at_ms"], record["captured_at_monotonic_ms"])
                self.assertEqual(result["capture"]["sha256"], expected_sha)
                self.assertFalse(result["quality_approved"])

    @unittest.skipUnless(os.environ.get("LAYA_SHOWDOWN_PRIVATE_SOURCE_PROOF") == "1", "genuine fan private font proof opt-in")
    def test_genuine_fans_existing_bank_reads_or_reports_precise_template_gaps(self):
        session = "utc-1791991640-171220300-practice"
        directory = ROOT / ".local/captures" / session
        bank = board.BoardTemplateRecognizer.load(ROOT / ".local/laya/dataset/exemplars.json",
            ROOT / ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz",
            extra_bank_path=ROOT / ".local/laya/board-pixel-bank-20261014.json", evidence_root=ROOT)
        reader = showdown.RevealedCardReader(bank, self.regions)
        rows = [board._json(line) for line in (directory / "manifest.jsonl").read_bytes().split(b"\n")[:-1] if line.strip()]
        sources = ((91, 5, "c4f2a74b247bfae7f4bae13ece291ea554df60231e3e07d71956ef4cad207291", ["2c", "2d"]),
                   (213, 6, "92156bee37526aade85f5efba5039159c0880e93943dfae519fb0110909faeee", ["Qc", "Jd"]))
        for sequence, seat, digest, observed in sources:
            with self.subTest(sequence=sequence, seat=seat):
                record = next(r for r in rows if r.get("event") == "frame" and r.get("frame_index") == sequence)
                self.assertEqual(record["sha256"], digest)
                receipt = {"session_id": session, "source_id": "private-source-intake", "epoch": 1,
                           "sequence": sequence, "captured_at_ms": record["captured_at_monotonic_ms"],
                           "captured_at_unix_ms": record["source_utc_unix_ms"], "sha256": digest,
                           "width": record["width"], "height": record["height"],
                           "native_source_id": str(record["source_id"]), "recording_session_id": session,
                           "clock_origin": "native_original_recording;not_live_monitor_replay",
                           "occluded_regions": record.get("occluded_regions", [])}
                result = reader.read_original(directory / ("frame-%010d.png" % sequence), directory / "manifest.jsonl", receipt)
                row = result["seats"][seat - 1]
                self.assertEqual(len(row["readings"]), 2)
                self.assertEqual(row["visible_face_count"], 2)
                self.assertIsNotNone(row["bounds"])
                self.assertEqual(result["phase"], "unknown")
                self.assertIsNone(row["identity"])
                self.assertNotIn("hero_seat", result)
                self.assertFalse(result["quality_approved"])
                # Agent visual comparison only. No missing label is substituted
                # and this test passing is NOT a whole-pair accuracy claim.
                for expected, reading in zip(observed, row["readings"]):
                    if reading["card"] is not None:
                        self.assertEqual(reading["card"], expected)
                        self.assertEqual(reading["status"], "provisional")
                    else:
                        self.assertEqual(reading["status"], "unknown")
                print("GENUINE_FAN_FONT_PROOF " + json.dumps({"sequence": sequence, "sha256": digest,
                      "seat": seat, "cards": row["cards"], "status": row["status"], "bounds": row["bounds"],
                      "readings": [{k: r[k] for k in ("card", "bounds", "glyph_bounds", "reason", "rank_match", "suit_match", "deskew_degrees")
                                    if k in r} for r in row["readings"]],
                      "phase": result["phase"], "quality_approved": False}))
                # Limited, in-memory, SAME-ORIGINAL resubstitution of missing
                # ranks proves the real-mask pipeline, NOT independent font
                # accuracy. It never trains, writes or changes the installed bank.
                import numpy as np
                metadata = [dict(entry) for group in bank.templates.values() for entry, _ in group]
                vectors = {entry["id"]: vector for group in bank.templates.values() for entry, vector in group}
                with Image.open(directory / ("frame-%010d.png" % sequence)) as original:
                    rgb = np.asarray(original.convert("RGB"), dtype="int16")
                    search = showdown._scaled_search(showdown.SEAT_SEARCH_BOUNDS[seat - 1], original.size)
                    candidates, _ = showdown._faces(rgb, search, original.size, with_geometry=True)
                    self.assertEqual(len(candidates), 2)
                    for expected, candidate, reading in zip(observed, candidates, row["readings"]):
                        if reading.get("rank_match", {}).get("label") is not None:
                            continue
                        feature = showdown.face_features(original.crop(candidate["bounds"]), candidate["visible_mask"])["features"]["rank"]
                        key = "private-same-original-rank-%d-%s" % (sequence, expected)
                        metadata.append({"id": key, "kind": "rank", "label": expected[0], "w": feature["w"],
                                         "h": feature["h"], "red": feature["red"],
                                         "source": "private-test-resubstitution-only:" + digest})
                        vectors[key] = feature["bitmap"]
                private_reader = showdown.RevealedCardReader(board.BoardTemplateRecognizer(metadata, vectors), self.regions)
                replay = private_reader.read_original(directory / ("frame-%010d.png" % sequence), directory / "manifest.jsonl", receipt)
                replay_row = replay["seats"][seat - 1]
                self.assertEqual(replay_row["cards"], observed)
                self.assertEqual(replay_row["status"], "provisional")
                self.assertEqual(replay_row["capture"], receipt)
                self.assertEqual(replay["phase"], "unknown")
                self.assertFalse(replay["quality_approved"])
                print("PRIVATE_SAME_ORIGINAL_RESUBSTITUTION_NOT_ACCURACY " + json.dumps({"sequence": sequence,
                      "sha256": digest, "seat": seat, "cards": replay_row["cards"], "phase": replay["phase"],
                      "quality_approved": False}))


if __name__ == "__main__":
    unittest.main()
