"""Synthetic guards and opt-in exact-source replay; all annotations are provisional."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
from PIL import Image, ImageDraw

from scripts import laya_board as board
from scripts import laya_prep


def synthetic_card(red=True):
    image = Image.new("RGB", (76, 107), (0, 70, 40))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 71, 102), radius=5, fill=(245, 245, 245))
    colour = (195, 20, 30) if red else (15, 15, 15)
    draw.rectangle((11, 10, 14, 28), fill=colour)
    draw.rectangle((11, 10, 23, 13), fill=colour)
    draw.rectangle((20, 10, 23, 28), fill=colour)
    draw.polygon([(17, 40), (24, 47), (17, 54), (10, 47)], fill=colour)
    return image


def library():
    features = board.slot_features(synthetic_card())["features"]
    metadata, bitmaps = [], {}
    for kind, labels in (("rank", ("8", "9")), ("suit", ("d", "h"))):
        ft = features[kind]
        for index, label in enumerate(labels):
            eid = kind + str(index)
            metadata.append({"id": eid, "kind": kind, "label": label, "w": ft["w"], "h": ft["h"],
                             "red": True, "source": "synthetic-test-only"})
            vector = ft["bitmap"].copy()
            bitmaps[eid] = vector if index == 0 else 1 - vector
    return metadata, bitmaps


def source_suit_updates():
    """Agent-inspected originals, not synthetic glyphs or human-reviewed labels."""
    directory = ".local/captures/utc-1791991640-171220300-practice"
    common = {"source_id": 4030215874350685307, "source_process_created_at_100ns": 134364617596088162,
              "width": 890, "height": 678, "generation": None, "timestamp_basis": "capture_call_start",
              "pixel_source": "visible_desktop_pixels", "readability": "full", "occluded_regions": []}
    records = [{**common, "frame_index": 1, "source_utc_unix_ms": 1791991640245,
                "captured_at_monotonic_ms": 74, "png_bytes": 710875,
                "sha256": "4b2dddd4439028d3abf52ec1dba3c6d5efc0fc2b0035df1e51450e7add35a2ac"},
               {**common, "frame_index": 289, "source_utc_unix_ms": 1791991802774,
                "captured_at_monotonic_ms": 162603, "png_bytes": 719706,
                "sha256": "7181b1d8983cbb05cc32e14e1ca60f0f7414586b7fa40a70ade547b6ccd0113b"}]
    return {"sources": [{"file": directory + f"/frame-{r['frame_index']:010d}.png",
                         "manifest": directory + "/manifest.jsonl", "record": r} for r in records],
            "templates": [
                {"id": "pixel-20261014-890-frame1-slot3-As-suit", "source_index": 1, "slot": 3,
                 "kind": "suit", "label": "s", "card": "As", "crop_bounds": [412, 271, 478, 365],
                 "crop_pixel_sha256": "5535b52e09a10a53f3d4b9b17cb4a66446a5df32dcb5229d4817e00e8f49de3e",
                 "glyph_bounds": [419, 306, 437, 324],
                 "glyph_pixel_sha256": "f5501b3ebfe299f6acdaccaaabcdc251ef50975846169ec772904b7c69550c55"},
                {"id": "pixel-20261014-890-frame289-slot2-4c-suit", "source_index": 2, "slot": 2,
                 "kind": "suit", "label": "c", "card": "4c", "crop_bounds": [344, 271, 411, 365],
                 "crop_pixel_sha256": "72132e9a6367dc30760c647468c1ca6e50a30624db37600eb0f5581017ae0346",
                 "glyph_bounds": [351, 306, 367, 323],
                 "glyph_pixel_sha256": "7bb3a4d1eea11dff8edb245b498fc6532ffe0c13659364bf5f0a6d88607fc593"}]}


class BoardTemplateTests(unittest.TestCase):
    def setUp(self):
        self.metadata, self.bitmaps = library()
        self.recognizer = board.BoardTemplateRecognizer(self.metadata, self.bitmaps)

    def test_complete_face_extracts_deterministic_training_compatible_masks(self):
        first = board.slot_features(synthetic_card())
        second = board.slot_features(synthetic_card())
        self.assertEqual(first["state"], "card_candidate")
        self.assertEqual(first["pixel_sha256"], second["pixel_sha256"])
        for kind in ("rank", "suit"):
            self.assertEqual(first["features"][kind]["bitmap"].shape, (24, 16))
            self.assertTrue(first["features"][kind]["red"])
            np.testing.assert_array_equal(first["features"][kind]["bitmap"], second["features"][kind]["bitmap"])
            feature = first["features"][kind]
            pixels = np.asarray(synthetic_card().crop(feature["glyph_bounds"]))
            self.assertEqual(feature["glyph_pixel_sha256"], hashlib.sha256(pixels.tobytes()).hexdigest())
            self.assertEqual(list(pixels.shape[:2]), [feature["h"], feature["w"]])

    def test_template_match_is_explicitly_provisional_and_never_probability(self):
        images = [synthetic_card()] * 3 + [Image.new("RGB", (76, 107), (0, 70, 40))] * 2
        result = self.recognizer.recognize_slots(images)
        self.assertEqual(result["slots"][0]["card"], "8d")
        self.assertIsNone(result["candidate_cards"])
        self.assertEqual(result["reason"], "duplicate-card")
        self.assertTrue(result["diagnostic_only"])
        self.assertFalse(result["quality_approved"])
        self.assertFalse(result["human_verified"])
        self.assertEqual(result["admission_status"], "unknown")
        for key in ("p", "probability", "acceptance_floor", "effective_floor"):
            self.assertNotIn('"' + key + '"', json.dumps(result))

    def test_ambiguity_uses_other_labels_not_other_exemplars_and_includes_size_competitors(self):
        ft = board.slot_features(synthetic_card())["features"]["rank"]
        metadata = copy.deepcopy(self.metadata)
        bitmaps = dict(self.bitmaps)
        metadata.append({**metadata[0], "id": "same-label"})
        bitmaps["same-label"] = bitmaps["rank0"]
        self.assertEqual(board.BoardTemplateRecognizer(metadata, bitmaps).match("rank", ft)["label"], "8")
        bitmaps["rank1"] = bitmaps["rank0"]
        metadata[1]["w"] = 100
        result = board.BoardTemplateRecognizer(metadata, bitmaps).match("rank", ft)
        self.assertIsNone(result["label"])
        self.assertEqual(result["reason"], "ambiguous-distinct-label")

    def test_distant_size_mismatched_missing_competitors_and_colours_abstain(self):
        ft = board.slot_features(synthetic_card())["features"]["rank"]
        for change, reason in (({"bitmap": np.clip(ft["bitmap"] - .4, 0, 1)}, "template-distance"),
                               ({"h": 90}, "template-size-mismatch"),
                               ({"red": False}, "no-colour-compatible-template")):
            self.assertEqual(self.recognizer.match("rank", {**ft, **change})["reason"], reason)
        metadata = [e for e in self.metadata if e["id"] != "rank1"]
        self.assertEqual(board.BoardTemplateRecognizer(metadata, self.bitmaps).match("rank", ft)["reason"],
                         "ambiguous-distinct-label")

    def test_partial_blank_transparent_back_and_missing_ink_do_not_yield_cards(self):
        transparent = synthetic_card().convert("RGBA")
        transparent.putalpha(128)
        partial = synthetic_card()
        ImageDraw.Draw(partial).rectangle((0, 40, 75, 106), fill=(0, 70, 40))
        images = [Image.new("RGB", (76, 107), colour) for colour in ((0, 0, 0), (180, 20, 30), (245, 245, 245))]
        images += [transparent, partial, Image.new("RGB", (4, 4))]
        for image in images:
            self.assertNotEqual(board.slot_features(image)["state"], "card_candidate")

    def test_empty_requires_positive_surface_not_missing_or_covered_faces(self):
        for colour in ((0, 0, 0), (180, 20, 30), (70, 70, 70), (10, 20, 10)):
            result = self.recognizer.recognize_slots([Image.new("RGB", (76, 107), colour)] * 5)
            self.assertIsNone(result["candidate_cards"])
            self.assertFalse(result["empty_board_supported"])
            self.assertTrue(all(s["status"] == "unknown" for s in result["slots"]))
        result = self.recognizer.recognize_slots([Image.new("RGB", (76, 107), (0, 70, 40))] * 5)
        self.assertEqual(result["candidate_cards"], [])
        self.assertTrue(result["empty_board_supported"])
        self.assertIsNone(result["stage"])
        self.assertFalse(result["scene_verified"])

    def test_each_slot_remains_available_during_another_slot_transition(self):
        original = self.recognizer.match
        ranks = iter(("9", "4", "A"))
        self.recognizer.match = lambda kind, feature: {"label": next(ranks) if kind == "rank" else "h"}
        empty = Image.new("RGB", (76, 107), (0, 70, 40))
        transition = synthetic_card()
        ImageDraw.Draw(transition).rectangle((0, 40, 75, 106), fill=(0, 70, 40))
        result = self.recognizer.recognize_slots([synthetic_card()] * 3 + [transition, empty])
        self.recognizer.match = original
        self.assertIsNone(result["candidate_cards"])
        self.assertEqual([s["card"] for s in result["slots"]], ["9h", "4h", "Ah", None, None])
        self.assertEqual([s["status"] for s in result["slots"]], ["provisional"] * 3 + ["unknown", "empty"])

    def test_mixed_colour_or_missing_suit_abstains(self):
        image = synthetic_card()
        ImageDraw.Draw(image).rectangle((10, 40, 24, 54), fill=(245, 245, 245))
        self.assertEqual(board.slot_features(image)["reason"], "missing-suit-ink")
        image = synthetic_card()
        ImageDraw.Draw(image).polygon([(17, 40), (24, 47), (17, 54), (10, 47)], fill=(15, 15, 15))
        self.assertEqual(board.slot_features(image)["reason"], "rank-suit-colour-disagreement")

    def test_whole_board_rejects_invalid_prefix_duplicate_and_unknown_slots(self):
        empty = {"state": "empty_candidate", "card": None}
        cards = [{"state": "card_candidate", "card": c} for c in ("8d", "9h", "Qs", "Tc", "Ah")]
        for count in (0, 3, 4, 5):
            self.assertEqual(board.assemble_board(cards[:count] + [empty] * (5 - count))[0],
                             [c["card"] for c in cards[:count]])
        for slots in (cards[:2] + [empty] * 3, [empty] + cards[:3] + [empty],
                      [cards[0]] * 3 + [empty] * 2, cards[:3] + [{"state": "unknown"}, empty]):
            self.assertIsNone(board.assemble_board(slots)[0])

    def test_library_validates_finite_bitmaps_labels_and_agent_provenance(self):
        for key, value in (("w", True), ("red", 1), ("label", "bogus"), ("source", "")):
            metadata = copy.deepcopy(self.metadata)
            metadata[0][key] = value
            with self.assertRaises(ValueError):
                board.BoardTemplateRecognizer(metadata, self.bitmaps)
        for value in (np.full(384, np.nan), np.full(384, np.inf), np.full(384, -1), np.zeros(384), np.zeros(3)):
            with self.assertRaises(ValueError):
                board.BoardTemplateRecognizer(self.metadata, {**self.bitmaps, "rank0": value})
        recognizer = board.BoardTemplateRecognizer(self.metadata, self.bitmaps,
            {"human_verified": True, "quality_approved": True})
        result = recognizer.recognize_slots([Image.new("RGB", (76, 107))] * 5)
        self.assertFalse(result["human_verified"])
        self.assertFalse(result["quality_approved"])
        self.assertEqual(result["template_artifacts"], {})

    def test_dual_shape_distance_checks_holes_and_both_directions(self):
        mask = np.zeros((24, 16), dtype=np.float32)
        mask[3:21, 3:13] = 1
        hollow = mask.copy()
        hollow[8:17, 6:10] = 0
        full, hole = board._shape_fields(mask), board._shape_fields(hollow)
        self.assertGreater(board._shape_distance(full, hole), board.MAX_SHAPE_DISTANCE)
        self.assertEqual(board._shape_distance(full, hole), board._shape_distance(hole, full))
        self.assertEqual(board._shape_distance(full, full), 0)

    def test_matching_accepts_only_bounded_uniform_raster_scaling(self):
        ft = board.slot_features(synthetic_card())["features"]["rank"]
        small_scale = {**ft, "w": round(ft["w"] * 1.2), "h": round(ft["h"] * 1.2)}
        self.assertEqual(self.recognizer.match("rank", small_scale)["label"], "8")
        squashed = {**ft, "w": round(ft["w"] * .7), "h": round(ft["h"] * 1.35)}
        self.assertIsNone(self.recognizer.match("rank", squashed)["label"])

    def test_batched_matching_preserves_all_symmetric_scalar_comparisons(self):
        random = np.random.default_rng(9021)
        feature = board.slot_features(synthetic_card())["features"]["rank"]
        for shift in (0, .05, .2, .4):
            query = {**feature, "bitmap": np.clip(feature["bitmap"] + random.uniform(-shift, shift, (24, 16)), 0, 1)}
            shape = board._shape_fields(query["bitmap"])
            references = sorted((board._shape_distance(shape, self.recognizer.shape_templates[e["id"]]), e["id"])
                                for e, _ in self.recognizer.templates["rank"])
            result = self.recognizer.match("rank", query)
            self.assertAlmostEqual(result["distance"], references[0][0], places=14)
            self.assertAlmostEqual(result["other_label_distance"], references[1][0], places=14)
            if result["label"] is not None:
                self.assertEqual(result["template_id"], references[0][1])

    def test_disk_loader_binds_artifact_bytes_and_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path, bitmaps_path = root / "metadata.json", root / "bitmaps.npz"
            metadata_path.write_text(json.dumps(self.metadata), encoding="utf-8")
            np.savez(bitmaps_path, **self.bitmaps)
            loaded = board.BoardTemplateRecognizer.load(metadata_path, bitmaps_path)
            self.assertEqual(len(loaded.provenance["metadata_sha256"]), 64)
            self.assertEqual(len(loaded.provenance["bitmaps_sha256"]), 64)
            metadata_path.write_text('{"not": "a-library"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid-template-metadata"):
                board.BoardTemplateRecognizer.load(metadata_path, bitmaps_path)
        with self.assertRaises(ValueError):
            board._json('{"label": "A", "label": "K"}')

    def test_blank_full_frame_does_not_claim_an_empty_verified_board(self):
        regions = {f"board_slot_{k}": [.05 + k * .1, .3, .12 + k * .1, .44] for k in range(1, 6)}
        for colour in ((0, 0, 0), (0, 70, 40), (245, 245, 245)):
            result = self.recognizer.recognize_frame(Image.new("RGB", (800, 613), colour), regions)
            self.assertIsNone(result["candidate_cards"])
            self.assertEqual(result["reason"], "blank-frame")
            self.assertEqual(len(result["crop_bounds"]), 5)
            self.assertEqual(len(result["frame_pixel_sha256"]), 64)

    def test_frame_regions_reject_nonfinite_overlap_order_and_invalid_geometry(self):
        regions = {f"board_slot_{k}": [.05 + k * .1, .3, .12 + k * .1, .44] for k in range(1, 6)}
        for roi in ([float("nan"), .3, .32, .44], [True, .3, .32, .44], [0.4, .3, .3, .44],
                    [-.1, .3, .2, .44], regions["board_slot_1"], [.25, .2, .32, .4]):
            with self.assertRaises(ValueError):
                self.recognizer.recognize_frame(Image.new("RGB", (800, 613)), {**regions, "board_slot_2": roi})
        with self.assertRaises(ValueError):
            self.recognizer.recognize_frame(None, regions)

    def test_normalized_nonoverlap_allows_shared_projected_boundary_pixel(self):
        regions = {f"board_slot_{k}": [.31 + (k - 1) * .077, .36, .386 + (k - 1) * .077, .5]
                   for k in range(1, 6)}
        result = self.recognizer.recognize_frame(Image.new("RGB", (100, 80)), regions)
        self.assertIsNone(result["candidate_cards"])

    def test_evidence_geometry_uses_actual_source_dimensions_and_card_face(self):
        regions = {f"board_slot_{k}": [.31 + (k - 1) * .077, .36, .386 + (k - 1) * .077, .5]
                   for k in range(1, 6)}
        for size in ((939, 714), (890, 678)):
            image = Image.new("RGB", size, (0, 70, 40))
            box = laya_prep.box_px(regions["board_slot_1"], *size)
            image.paste(synthetic_card().resize((box[2] - box[0], box[3] - box[1])), box)
            result = self.recognizer.recognize_frame(image, regions)
            slot = result["slots"][0]
            self.assertEqual(slot["crop_bounds"], list(box))
            face = slot["card_bounds"]
            self.assertEqual(slot["evidence_bounds"], [box[0] + face[0], box[1] + face[1], box[0] + face[2], box[1] + face[3]])
            self.assertNotEqual(slot["evidence_bounds"], list(box))
            self.assertEqual(slot["evidence_pixel_sha256"], hashlib.sha256(
                np.asarray(image.crop(slot["evidence_bounds"])).tobytes()).hexdigest())

    def pixel_fixture(self, root):
        capture = root / "capture"
        capture.mkdir()
        regions = {f"board_slot_{k}": [.05 + k * .1, .3, .12 + k * .1, .44] for k in range(1, 6)}
        regions_path = root / "regions.json"
        regions_path.write_text(json.dumps({"regions": regions}), encoding="utf-8")
        image = Image.new("RGB", (800, 613), (0, 70, 40))
        glyph = synthetic_card()
        draw = ImageDraw.Draw(glyph)
        draw.rectangle((10, 9, 25, 29), fill=(245, 245, 245))
        draw.rectangle((11, 10, 14, 28), fill=(195, 20, 30))
        draw.polygon([(23, 10), (19, 10), (13, 19), (19, 28), (24, 28), (17, 19)], fill=(195, 20, 30))
        box = laya_prep.box_px(regions["board_slot_1"], *image.size)
        image.paste(glyph.resize((box[2] - box[0], box[3] - box[1])), box)
        png = capture / "frame-0000000001.png"
        image.save(png)
        record = {"frame_index": 1, "source_utc_unix_ms": 1000, "captured_at_monotonic_ms": 1,
                  "source_id": 123, "width": 800, "height": 613,
                  "sha256": hashlib.sha256(png.read_bytes()).hexdigest()}
        manifest = capture / "manifest.jsonl"
        manifest.write_text(json.dumps({"event": "frame", **record}) + "\n", encoding="utf-8")
        extra = {"schema": "coinpoker-board-pixel-templates/1", "annotation_origin": "agent-generated",
                 "human_verified": False, "quality_approved": False, "calibration": "unvalidated",
                 "regions_file": "regions.json", "regions_sha256": hashlib.sha256(regions_path.read_bytes()).hexdigest(),
                 "sources": [{"file": "capture/" + png.name, "manifest": "capture/manifest.jsonl", "record": record}],
                 "templates": [{"id": "synthetic-pixel-K", "source_index": 0, "slot": 1, "kind": "rank", "label": "K"}]}
        bank_path = root / "extra.json"
        bank_path.write_text(json.dumps(extra), encoding="utf-8")
        base_meta, base_vectors = root / "base.json", root / "base.npz"
        base_meta.write_text(json.dumps(self.metadata), encoding="utf-8")
        np.savez(base_vectors, **self.bitmaps)
        return extra, bank_path, base_meta, base_vectors, board.slot_features(image.crop(box))["features"]["rank"]

    def test_extra_pixel_bank_is_opt_in_manifest_bound_and_keeps_provisional_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extra, path, meta, vectors, feature = self.pixel_fixture(root)
            original = board.BoardTemplateRecognizer.load(meta, vectors)
            self.assertNotEqual(original.match("rank", feature)["label"], "K")
            loaded = board.BoardTemplateRecognizer.load(meta, vectors, extra_bank_path=path, evidence_root=root)
            result = loaded.match("rank", feature)
            self.assertEqual(result["label"], "K")
            self.assertEqual(result["distance"], 0)
            self.assertEqual(result["pixel_source"]["sha256"], extra["sources"][0]["record"]["sha256"])
            self.assertEqual(result["pixel_source"]["source_utc_unix_ms"], 1000)
            self.assertEqual(loaded.provenance["extra_template_count"], 1)
            self.assertEqual(loaded.provenance["extra_bank_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            diagnostic = loaded.recognize_slots([Image.new("RGB", (76, 107))] * 5)
            self.assertFalse(diagnostic["human_verified"])
            self.assertFalse(diagnostic["quality_approved"])
            self.assertEqual(diagnostic["match_rules"], original.recognize_slots([Image.new("RGB", (76, 107))] * 5)["match_rules"])
            with self.assertRaisesRegex(ValueError, "extra-bank-requires-evidence-root"):
                board.BoardTemplateRecognizer.load(meta, vectors, extra_bank_path=path)

    def test_extra_bank_refuses_tampering_foreign_sources_and_review_claims(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, path, meta, vectors, _ = self.pixel_fixture(root)
            for mutate, message in ((lambda b: b.update(human_verified=True), "invalid-pixel-bank"),
                                    (lambda b: b.update(regions_sha256="0" * 64), "pixel-bank-regions-sha-mismatch"),
                                    (lambda b: b["sources"][0].update(file="../outside.png"), "pixel-source-outside-root"),
                                    (lambda b: b["sources"][0]["record"].update(source_utc_unix_ms=1001), "pixel-source-manifest-mismatch"),
                                    (lambda b: b["templates"][0].update(label="X"), "invalid-pixel-template"),
                                    (lambda b: b["templates"][0].update(slot=5), "pixel-template-incomplete-card")):
                changed = copy.deepcopy(original)
                mutate(changed)
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    board.BoardTemplateRecognizer.load(meta, vectors, extra_bank_path=path, evidence_root=root)
            path.write_text(json.dumps(original), encoding="utf-8")
            (root / "capture/frame-0000000001.png").write_bytes(b"tampered-source")
            with self.assertRaisesRegex(ValueError, "pixel-source-sha-mismatch"):
                board.BoardTemplateRecognizer.load(meta, vectors, extra_bank_path=path, evidence_root=root)

    def test_extra_pixel_label_does_not_override_distinct_label_ambiguity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, path, meta, vectors, feature = self.pixel_fixture(root)
            original["templates"].append({**original["templates"][0], "id": "conflicting-agent-label", "label": "A"})
            path.write_text(json.dumps(original), encoding="utf-8")
            loaded = board.BoardTemplateRecognizer.load(meta, vectors, extra_bank_path=path, evidence_root=root)
            self.assertIsNone(loaded.match("rank", feature)["label"])
            self.assertEqual(loaded.match("rank", feature)["reason"], "ambiguous-distinct-label")

    def test_pixel_bank_checks_original_generation_masks_and_exact_glyph_witness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, path, meta, vectors, _ = self.pixel_fixture(root)
            source = original["sources"][0]
            source["record"].update(generation=None, source_process_created_at_100ns=999,
                                    pixel_source="visible_desktop_pixels", readability="full", occluded_regions=[],
                                    png_bytes=(root / source["file"]).stat().st_size)
            (root / source["manifest"]).write_text(json.dumps({"event": "frame", **source["record"]}) + "\n", encoding="utf-8")
            regions = json.loads((root / "regions.json").read_bytes())["regions"]
            box = list(laya_prep.box_px(regions["board_slot_1"], 800, 613))
            with Image.open(root / source["file"]) as image:
                slot = board.slot_features(image.crop(box))
            feature = slot["features"]["rank"]
            glyph = feature["glyph_bounds"]
            original["templates"][0].update(card="Kd", crop_bounds=box, crop_pixel_sha256=slot["pixel_sha256"],
                glyph_bounds=[box[0] + glyph[0], box[1] + glyph[1], box[0] + glyph[2], box[1] + glyph[3]],
                glyph_pixel_sha256=feature["glyph_pixel_sha256"])
            path.write_text(json.dumps(original), encoding="utf-8")
            loaded = board.BoardTemplateRecognizer.load(meta, vectors, extra_bank_path=path, evidence_root=root)
            proof = loaded.match("rank", feature)["pixel_source"]
            self.assertIsNone(proof["generation"])
            self.assertEqual(proof["source_process_created_at_100ns"], 999)
            self.assertEqual(proof["glyph_bounds"], original["templates"][0]["glyph_bounds"])
            for mutate, reason in (
                    (lambda b: b["sources"][0]["record"].update(generation=85), "pixel-source-manifest-mismatch"),
                    (lambda b: b["sources"][0]["record"].update(source_process_created_at_100ns=998), "pixel-source-manifest-mismatch"),
                    (lambda b: b["sources"][0]["record"].update(png_bytes=1), "pixel-source-manifest-mismatch"),
                    (lambda b: b["templates"][0].update(glyph_pixel_sha256="0" * 64), "pixel-template-witness-mismatch"),
                    (lambda b: b["templates"][0].update(glyph_bounds=[0, 0, 2, 2]), "pixel-template-witness-mismatch"),
                    (lambda b: b["templates"][0].update(crop_pixel_sha256="0" * 64), "pixel-template-witness-mismatch"),
                    (lambda b: b["templates"][0].update(card="Ks"), "pixel-template-witness-mismatch"),
                    (lambda b: b["templates"][0].pop("card"), "pixel-template-witness-mismatch")):
                changed = copy.deepcopy(original)
                mutate(changed)
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, reason):
                    board.BoardTemplateRecognizer.load(meta, vectors, extra_bank_path=path, evidence_root=root)
            path.write_text(json.dumps(original), encoding="utf-8")
            row = {"event": "frame", **source["record"], "occluded_regions": [box]}
            (root / source["manifest"]).write_text(json.dumps(row) + "\n", encoding="utf-8")
            original["sources"][0]["record"]["occluded_regions"] = [box]
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pixel-template-incomplete-card"):
                board.BoardTemplateRecognizer.load(meta, vectors, extra_bank_path=path, evidence_root=root)

    @unittest.skipUnless(os.environ.get("LAYA_BOARD_CURRENT_PIXEL_PROOF") == "1", "private current pixel-bank replay opt-in")
    def test_current_pixel_discrepancy_and_bank_excluded_later_boards(self):
        root = Path(__file__).resolve().parents[2]
        metadata = root / ".local/laya/dataset/exemplars.json"
        vectors = root / ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz"
        original = board.BoardTemplateRecognizer.load(metadata, vectors)
        extra = board.BoardTemplateRecognizer.load(metadata, vectors,
            extra_bank_path=root / ".local/laya/board-pixel-bank-20261014.json", evidence_root=root)
        capture = root / ".local/captures/utc-1791937564-730008400-practice"
        records = {row["frame_index"]: row for row in
                   (json.loads(line) for line in (capture / "manifest.jsonl").read_bytes().split(b"\n")[:-1])
                   if row.get("event") == "frame"}
        regions = json.loads((root / "crates/ingest/assets/laya/regions.json").read_bytes())
        # Agent-observed references only. 485 is resubstitution; 500 repeats
        # that hand. Later distinct-hand boards were not extra-bank sources.
        for index, expected in ((485, ["7c", "2d", "Kh", "7s"]),
                                (500, ["7c", "2d", "Kh", "7s"]), (525, []),
                                (660, ["4s", "Kd", "3c"])):
            path = capture / f"frame-{index:010d}.png"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), records[index]["sha256"])
            with Image.open(path) as image:
                self.assertEqual(image.size, (records[index]["width"], records[index]["height"]))
                before, after = original.recognize_frame(image, regions), extra.recognize_frame(image, regions)
            self.assertEqual(after["candidate_cards"], expected)
            self.assertEqual(before["match_rules"], after["match_rules"])
            self.assertFalse(after["quality_approved"])
            self.assertFalse(after["human_verified"])
            if index == 485:
                self.assertIsNone(before["candidate_cards"])
                self.assertEqual(after["slots"][2]["matches"]["rank"]["distance"], 0)
                self.assertEqual(after["slots"][2]["matches"]["rank"]["pixel_source"]["sha256"],
                                 "37b0b6d1b5160ec1b0b7a88f730d038ef7b79c3724c8da284a6ac743ee4bb102")
        # Known agent-observed later boards still have unrelated coverage gaps:
        # 740 = 4s Kd 3c 3d 8s (spade/club ambiguity in slot5);
        # 860 = 8c 9s 6d 9h Qc (8/9 ambiguity in slot1).
        # The new red-K template must not suppress these guards or guess cards.
        for index, slot, kind in ((740, 4, "suit"), (860, 0, "rank")):
            path = capture / f"frame-{index:010d}.png"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), records[index]["sha256"])
            with Image.open(path) as image:
                before, after = original.recognize_frame(image, regions), extra.recognize_frame(image, regions)
            self.assertIsNone(before["candidate_cards"])
            self.assertIsNone(after["candidate_cards"])
            self.assertEqual(after["slots"][slot]["matches"][kind]["reason"], "ambiguous-distinct-label")
        fitted = json.loads((root / "models/laya-vision/finetuned/20261009T190322Z-it1/calibration.json").read_bytes())
        self.assertEqual(fitted["thresholds_per_pass"]["p2_board"], 1.0)
        self.assertEqual(fitted["thresholds"]["card:p2_board"], 1.0)

    @unittest.skipUnless(os.environ.get("LAYA_BOARD_SELECTED_SOURCE_PROOF") == "1", "selected 890x678 original replay opt-in")
    def test_selected_original_supported_streets_and_distinct_card_holdout(self):
        root = Path(__file__).resolve().parents[2]
        capture = root / ".local/captures/utc-1791991640-171220300-practice"
        records = {}
        with (capture / "manifest.jsonl").open("rb") as stream:
            for _ in range(571):
                row = json.loads(stream.readline())
                records[row["frame_index"]] = row
        installed = board.BoardTemplateRecognizer.load(root / ".local/laya/dataset/exemplars.json",
            root / ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz",
            extra_bank_path=root / ".local/laya/board-pixel-bank-20261014.json", evidence_root=root)
        additions = source_suit_updates()
        bank = json.loads((root / ".local/laya/board-pixel-bank-20261014.json").read_bytes())
        for source, template in zip(additions["sources"], additions["templates"]):
            if not any(t["id"] == template["id"] for t in bank["templates"]):
                template = {**template, "source_index": len(bank["sources"])}
                bank["sources"].append(source)
                bank["templates"].append(template)
        with tempfile.TemporaryDirectory() as temporary:
            proposed = Path(temporary) / "source-bound-suit-bank.json"
            proposed.write_text(json.dumps(bank), encoding="utf-8")
            recognizer = board.BoardTemplateRecognizer.load(root / ".local/laya/dataset/exemplars.json",
                root / ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz",
                extra_bank_path=proposed, evidence_root=root)
        fitted_ids = {t["id"] for t in additions["templates"]}
        previous = [(e, v) for entries in installed.templates.values() for e, v in entries if e["id"] not in fitted_ids]
        baseline = board.BoardTemplateRecognizer([e for e, _ in previous], {e["id"]: v for e, v in previous})
        regions = json.loads((root / "crates/ingest/assets/laya/regions.json").read_bytes())
        calibration = root / "models/laya-vision/finetuned/20261009T190322Z-it1/calibration.json"
        before = calibration.read_bytes()
        self.assertEqual(records[289]["sha256"], "7181b1d8983cbb05cc32e14e1ca60f0f7414586b7fa40a70ade547b6ccd0113b")
        # References are observed in these exact original PNGs, not training labels.
        for index, expected in ((1, ["Td", "8d", "As"]), (289, ["9h", "4c", "Ah"]),
                                (310, ["9h", "4c", "Ah", "2d"]), (350, ["9h", "4c", "Ah", "2d", "2c"]),
                                (400, []), (571, [])):
            path = capture / f"frame-{index:010d}.png"
            raw = path.read_bytes()
            record = records[index]
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
            self.assertEqual(len(raw), record["png_bytes"])
            self.assertEqual(record["source_id"], 4030215874350685307)
            with Image.open(path) as image:
                self.assertEqual(image.size, (890, 678))
                self.assertEqual(list(image.size), [record["width"], record["height"]])
                before_result = baseline.recognize_frame(image, regions)
                started = time.perf_counter()
                result = recognizer.recognize_frame(image, regions)
                processing_ms = round((time.perf_counter() - started) * 1000, 2)
                if index == 350:
                    heldout_glyph = board.slot_features(image.crop(result["crop_bounds"][4]))["features"]["suit"]["glyph_pixel_sha256"]
            print("selected_original_board", json.dumps({"sequence": index, "sha256": record["sha256"],
                "source_utc_unix_ms": record["source_utc_unix_ms"], "captured_at_ms": record["captured_at_monotonic_ms"],
                "candidate_cards": result["candidate_cards"], "slot_statuses": [s["status"] for s in result["slots"]],
                "reason": result["reason"], "native_qualified": False, "processing_ms": processing_ms,
                "resubstitution": index in (1, 289),
                "unknown_matches": [{"slot": s["slot"], "reason": s["reason"],
                                     "matches": {k: m["reason"] for k, m in s.get("matches", {}).items()}}
                                    for s in result["slots"] if s["status"] == "unknown"]}))
            if index in (1, 350):
                self.assertIsNone(before_result["candidate_cards"])
                self.assertEqual([s["card"] for s in before_result["slots"]],
                                 ["Td", "8d", None, None, None] if index == 1 else ["9h", "4c", "Ah", "2d", None])
                rejected = before_result["slots"][2 if index == 1 else 4]
                self.assertEqual(rejected["reason"], "unmatched-card-ink")
                self.assertEqual(rejected["matches"]["suit"]["reason"], "ambiguous-distinct-label")
                if index == 350:
                    # Train on 4c@289; evaluate 2c@350, not the source glyph/frame.
                    match = result["slots"][4]["matches"]["suit"]
                    self.assertEqual(match["template_id"], additions["templates"][1]["id"])
                    self.assertEqual(match["pixel_source"]["frame_index"], 289)
                    self.assertNotEqual(match["pixel_source"]["sha256"], record["sha256"])
                    self.assertNotEqual(match["pixel_source"]["glyph_pixel_sha256"], heldout_glyph)
                    self.assertGreater(match["distance"], 0)
                    self.assertIsNone(match["pixel_source"]["generation"])
            self.assertEqual(result["candidate_cards"], expected)
            self.assertEqual(result["match_rules"], before_result["match_rules"])
            self.assertFalse(result["human_verified"])
            self.assertFalse(result["quality_approved"])
            self.assertFalse(result["scene_verified"])
            self.assertEqual(result["stage"], {3: "flop", 4: "turn", 5: "river"}.get(len(expected)))
        self.assertEqual(calibration.read_bytes(), before)
        fitted = json.loads(before)
        self.assertEqual(fitted["thresholds_per_pass"]["p2_board"], 1.0)
        self.assertEqual(fitted["thresholds"]["card:p2_board"], 1.0)
        other_capture = root / ".local/captures/utc-1791937564-730008400-practice"
        other_records = {r["frame_index"]: r for r in
                         (json.loads(line) for line in (other_capture / "manifest.jsonl").read_bytes().splitlines())}
        for index, slot, kind in ((740, 4, "suit"), (860, 0, "rank")):
            path = other_capture / f"frame-{index:010d}.png"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), other_records[index]["sha256"])
            with Image.open(path) as image:
                result = recognizer.recognize_frame(image, regions)
            self.assertIsNone(result["candidate_cards"])
            self.assertEqual(result["slots"][slot]["matches"][kind]["reason"], "ambiguous-distinct-label")
            print("expanded_bank_holdout_unknown", json.dumps({"sequence": index, "sha256": other_records[index]["sha256"],
                "candidate_cards": None, "cards": [s["card"] for s in result["slots"]],
                "unknown_slot": slot + 1, "unknown_kind": kind, "native_qualified": False}))

    @unittest.skipUnless(os.environ.get("LAYA_BOARD_RELOAD_SOURCE_PROOF") == "1", "failed 927x705 finite original replay opt-in")
    def test_reload_first505_originals_full_flop_only_and_dealing_abstention(self):
        root = Path(__file__).resolve().parents[2]
        session = root / ".local/laya/manual-capture/fe530937b2d741d3bb8819bc36373f00"
        run = json.loads((session / "run.json").read_bytes())
        status = json.loads((session / "status.json").read_bytes())
        self.assertEqual(run["stop_reason"], "feed-failed")
        self.assertFalse(run["forced_stop"])
        self.assertEqual(status["recorded_frames"], 505)
        capture = Path(status["capture_directory"])
        self.assertEqual(capture, root / ".local/captures/utc-1792003095-224479100-practice")
        records = [json.loads(line) for line in (capture / "manifest.jsonl").read_bytes().splitlines()]
        self.assertEqual(len(records), 505)
        recognizer = board.BoardTemplateRecognizer.load(root / ".local/laya/dataset/exemplars.json",
            root / ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz",
            extra_bank_path=root / ".local/laya/board-pixel-bank-20261014.json", evidence_root=root)
        # Even the pre-update bank reads this flop; do not blame missing templates
        # for the concurrent stopped feed or claim a turn/river absent in this run.
        fitted_ids = {t["id"] for t in source_suit_updates()["templates"]}
        entries = [(e, v) for values in recognizer.templates.values() for e, v in values if e["id"] not in fitted_ids]
        baseline = board.BoardTemplateRecognizer([e for e, _ in entries], {e["id"]: v for e, v in entries})
        regions = json.loads((root / "crates/ingest/assets/laya/regions.json").read_bytes())
        bounds = [[288, 281, 358, 379], [358, 281, 428, 379], [429, 281, 498, 379],
                  [499, 281, 569, 379], [569, 281, 639, 379]]
        counts, timings, previous_clock = {}, [], (-1, -1)
        for index, record in enumerate(records, 1):
            self.assertEqual(record["frame_index"], index)
            self.assertEqual(record["source_id"], 3235148086084101343)
            self.assertEqual(record["source_process_created_at_100ns"], 134364766616945609)
            self.assertIsNone(record["generation"])
            clock = record["source_utc_unix_ms"], record["captured_at_monotonic_ms"]
            self.assertTrue(all(now > old for now, old in zip(clock, previous_clock)))
            previous_clock = clock
            path = capture / f"frame-{index:010d}.png"
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
            self.assertEqual(len(raw), record["png_bytes"])
            with Image.open(path) as image:
                self.assertEqual(image.size, (927, 705))
                # Occupancy intake only for the finite empty prefix; full glyph
                # matching starts when an actual source card reaches the board.
                if index < 492:
                    states = [board.slot_features(image.crop(box))["state"] for box in bounds]
                    self.assertEqual(states, ["empty_candidate"] * 5)
                    counts["empty"] = counts.get("empty", 0) + 1
                    continue
                started = time.perf_counter()
                result = recognizer.recognize_frame(image, regions)
                timings.append((time.perf_counter() - started) * 1000)
                self.assertEqual(result["crop_bounds"], bounds)
                self.assertEqual(result["candidate_cards"], None if index < 495 else ["Kc", "Kd", "Ah"])
                counts[result["stage"] or "unknown"] = counts.get(result["stage"] or "unknown", 0) + 1
                if index >= 495:
                    self.assertEqual(baseline.recognize_frame(image, regions)["candidate_cards"], ["Kc", "Kd", "Ah"])
                    self.assertFalse(result["human_verified"])
                    self.assertFalse(result["quality_approved"])
            if index in (492, 495, 501, 505):
                print("reload_original_board", json.dumps({"sequence": index, "sha256": record["sha256"],
                    "source_utc_unix_ms": clock[0], "captured_at_ms": clock[1], "generation": record["generation"],
                    "candidate_cards": result["candidate_cards"], "stage": result["stage"],
                    "crop_bounds": result["crop_bounds"], "processing_ms": round(timings[-1], 2),
                    "native_qualified": False}))
        self.assertEqual(counts, {"empty": 491, "unknown": 3, "flop": 11})
        print("reload_finite_summary", json.dumps({"originals": 505, "counts": counts,
            "reader_processing_ms": {"min": round(min(timings), 2), "median": round(float(np.median(timings)), 2),
                                     "max": round(max(timings), 2)}, "turn_river_source_available": False}))

    @unittest.skipUnless(os.environ.get("LAYA_BOARD_PRIVATE_REPLAY_PROOF") == "1", "private agent-observation replay opt-in")
    def test_exact_manifest_bound_agent_board_observations_and_unchanged_model_floor(self):
        root = Path(__file__).resolve().parents[2]
        recognizer = board.BoardTemplateRecognizer.load(root / ".local/laya/dataset/exemplars.json",
            root / ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz")
        regions = json.loads((root / "crates/ingest/assets/laya/regions.json").read_bytes())
        capture = root / ".local/captures/utc-1791930788-730768600-practice"
        manifest = {row["frame_index"]: row for row in
                    (json.loads(line) for line in (capture / "manifest.jsonl").read_text(encoding="utf-8").splitlines())
                    if row.get("event") == "frame"}
        # These are exact agent-observed originals, not human-reviewed ground truth.
        for index, expected in ((2, ["8h", "6c", "Js", "Qh"]), (17, ["8h", "6c", "Js", "Qh", "7h"])):
            path = capture / f"frame-{index:010d}.png"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), manifest[index]["sha256"])
            with Image.open(path) as image:
                self.assertEqual(list(image.size), [manifest[index]["width"], manifest[index]["height"]])
                result = recognizer.recognize_frame(image, regions)
            self.assertEqual(result["candidate_cards"], expected)
            self.assertFalse(result["human_verified"])
            self.assertFalse(result["quality_approved"])
            self.assertEqual(result["admission_status"], "unknown")
        fitted = json.loads((root / "models/laya-vision/finetuned/20261009T190322Z-it1/calibration.json").read_bytes())
        self.assertEqual(fitted["thresholds_per_pass"]["p2_board"], 1.0)
        self.assertEqual(fitted["thresholds"]["card:p2_board"], 1.0)
        for path in (root / ".local/captures/20261009T170508Z-laya-train/lobby/lobby-user-screengrab.png",
                     root / ".local/captures/20261008T232842Z-new-calibration/lobby.png"):
            with Image.open(path) as image:
                result = recognizer.recognize_frame(image, regions)
            self.assertFalse(result["candidate_cards"])
            self.assertFalse(result["scene_verified"])


if __name__ == "__main__":
    unittest.main()
