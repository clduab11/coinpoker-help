"""Deterministic, provisional board diagnostics from private card-ink templates.

The existing template labels are agent-generated cluster annotations, not ground
truth or fitted probabilities. This module never changes Laya acceptance floors,
emits accepted observations, trains, relabels source evidence, or writes image pixels.
Callers must bind results to the original capture ticket and source lifetime.
Empty slots alone do not identify a table, preflop, or a new hand; lobby crops
can also lack card faces. This module performs no screen/phase classification.
"""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path

try:
    from . import laya_prep
except ImportError:
    import laya_prep


RANKS = frozenset("23456789TJQKA")
SUITS = frozenset("shdc")
BITMAP_SIZE = (16, 24)
# Provisional shape guards, not fitted probabilities or Laya admission floors.
MAX_SHAPE_DISTANCE = 0.015
MAX_MASK_DISTANCE = 0.15
DISTINCT_LABEL_RATIO = 1.6
DISTINCT_LABEL_GAP = 0.0025
MARKERS = {"diagnostic_only": True, "quality_approved": False,
           "human_verified": False, "annotation_origin": "agent-generated",
           "calibration": "unvalidated", "admission_status": "unknown"}


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate-json-key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite-json")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def slot_features(image):
    """Extract occupancy and rank/small-suit ink using the training crop geometry."""
    import numpy as np
    from PIL import Image

    unknown = {"state": "unknown", "reason": "invalid-crop", "features": {}}
    if not isinstance(image, Image.Image) or min(image.size) < 8:
        return unknown
    a = np.asarray(image.convert("RGB")).astype(np.int16)
    if image.mode == "RGBA" and np.asarray(image.getchannel("A")).min() != 255:
        return {**unknown, "reason": "transparent-crop"}
    white_fraction = float((a.min(axis=2) > 225).mean())
    # Positive visible felt is distinct from merely failing to find a white face.
    felt = ((a[..., 1] >= 45) & (a[..., 1] >= a[..., 0] + 20)
            & (a[..., 2] >= 20) & (a[..., 1] > a[..., 2] * 1.1))
    result = {"state": "unknown", "reason": "partial-card-or-occlusion", "features": {},
              "white_fraction": white_fraction,
              "empty_surface": {"kind": "visible-green-felt", "fraction": float(felt.mean()),
                                "supported": bool(felt.mean() >= .70 and white_fraction < .03)},
              "pixel_sha256": hashlib.sha256(a.astype(np.uint8).tobytes()).hexdigest(),
              "dimensions": list(image.size)}
    if white_fraction < 0.03:
        back = float(((a[..., 0] > 110) & (a[..., 1] < 60) & (a[..., 2] < 80)).mean())
        if back < 0.02:
            if result["empty_surface"]["supported"]:
                result.update(state="empty_candidate", reason="visible-felt-without-card-face")
            else:
                result["reason"] = "no-supported-card-surface"
        return result
    if white_fraction <= 0.50:
        return result
    near_white = a.min(axis=2) > 200
    cols = np.flatnonzero(near_white.mean(axis=0) > 0.3)
    rows = np.flatnonzero(near_white.mean(axis=1) > 0.3)
    if len(cols) < 8 or len(rows) < 8:
        return result
    x0, x1, y0, y1 = int(cols[0]), int(cols[-1]) + 1, int(rows[0]), int(rows[-1]) + 1
    h, w = y1 - y0, x1 - x0
    # Complete card faces only: clipped/dealing cards must not resemble stable glyphs.
    if not (0.55 <= w / h <= 0.85 and w >= 0.75 * a.shape[1] and h >= 0.80 * a.shape[0]
            and x0 > 0 and y0 > 0 and x1 < a.shape[1] and y1 < a.shape[0]):
        result["reason"] = "incomplete-card-face"
        return result
    a = a[y0:y1, x0:x1]
    green = (a[..., 1] > a[..., 0] + 20) & (a[..., 1] > a[..., 2])
    ink = (a.min(axis=2) < 150) & ~green
    red = a[..., 0] - a[..., 1] > 70
    features = {}
    for kind, (top, bottom) in {"rank": (0.02, 0.36), "suit": (0.36, 0.60)}.items():
        top_px, left_px = int(top * h), int(0.03 * w)
        sub = ink[top_px:int(bottom * h), left_px:int(0.46 * w)]
        rsub = red[top_px:int(bottom * h), left_px:int(0.46 * w)]
        comps = [c for c in laya_prep._components(sub) if c["area"] >= 6]
        if not comps:
            result["reason"] = "missing-" + kind + "-ink"
            return result
        xa, xb = min(c["x0"] for c in comps), max(c["x1"] for c in comps)
        ya, yb = min(c["y0"] for c in comps), max(c["y1"] for c in comps)
        mask = sub[ya:yb, xa:xb]
        red_fraction = float(rsub[ya:yb, xa:xb][mask].mean())
        if 0.05 < red_fraction < 0.95:
            result["reason"] = "mixed-ink-colour"
            return result
        bitmap = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize(
            BITMAP_SIZE, Image.Resampling.BILINEAR)).astype(np.float32) / 255.0
        features[kind] = {"bitmap": bitmap, "w": xb - xa, "h": yb - ya,
                           "red": red_fraction >= 0.95,
                           "glyph_bounds": [x0 + left_px + xa, y0 + top_px + ya,
                                            x0 + left_px + xb, y0 + top_px + yb],
                           "glyph_pixel_sha256": hashlib.sha256(
                               a[top_px + ya:top_px + yb, left_px + xa:left_px + xb].astype(np.uint8).tobytes()).hexdigest()}
    if features["rank"]["red"] != features["suit"]["red"]:
        result["reason"] = "rank-suit-colour-disagreement"
        return result
    result.update(state="card_candidate", reason="complete-card-face", features=features,
                  card_bounds=[x0, y0, x1, y1])
    return result


def assemble_board(slots):
    """A candidate board is complete, unique and a legal contiguous 0/3/4/5 prefix."""
    if len(slots) != 5 or any(s.get("state") not in ("card_candidate", "empty_candidate") for s in slots):
        return None, "unknown-slot"
    cards = [s.get("card") for s in slots if s["state"] == "card_candidate"]
    if any(not isinstance(c, str) or len(c) != 2 or c[0] not in RANKS or c[1] not in SUITS for c in cards):
        return None, "unmatched-card-ink"
    n = len(cards)
    if n not in (0, 3, 4, 5) or [s["state"] for s in slots] != ["card_candidate"] * n + ["empty_candidate"] * (5 - n):
        return None, "noncontiguous-or-transitional-board"
    if len(set(cards)) != n:
        return None, "duplicate-card"
    return cards, "provisional-template-match" if cards else "provisional-empty-board"


def _shape_fields(vector):
    """Distance to both ink and background; holes matter as well as silhouettes."""
    import numpy as np

    mask = np.asarray(vector).reshape(24, 16) >= 0.5
    if not mask.any() or mask.all():
        raise ValueError("invalid-template-ink")
    grid = np.indices(mask.shape).reshape(2, -1).T
    fields = []
    for selected in (mask, ~mask):
        points = np.column_stack(np.nonzero(selected))
        squared = ((grid[:, None, :] - points[None, :, :]) ** 2).sum(axis=2)
        fields.append(np.sqrt(squared.min(axis=1)).reshape(mask.shape))
    return mask, fields[0], fields[1]


def _shape_distance(first, second):
    a, af, ab = first
    b, bf, bb = second
    return max(float(af[b].mean()), float(bf[a].mean()),
               float(ab[~b].mean()), float(bb[~a].mean())) / BITMAP_SIZE[1]


class BoardTemplateRecognizer:
    def __init__(self, metadata, bitmaps, provenance=None):
        import numpy as np

        if not isinstance(metadata, list):
            raise ValueError("invalid-template-metadata")
        self.templates = {"rank": [], "suit": []}
        self.shape_templates = {}
        seen = set()
        for entry in metadata:
            if not isinstance(entry, dict):
                raise ValueError("invalid-template-entry")
            kind = entry.get("kind")
            if kind not in ("rank", "suit"):
                continue
            eid, label = entry.get("id"), entry.get("label")
            if (not isinstance(eid, str) or not eid or eid in seen or eid not in bitmaps
                    or not isinstance(label, str) or label not in (RANKS if kind == "rank" else SUITS)
                    or any(type(entry.get(key)) is not int or not 1 <= entry[key] <= 256 for key in ("w", "h"))
                    or type(entry.get("red")) is not bool
                    or not isinstance(entry.get("source"), str) or not entry["source"]
                    or kind == "suit" and entry["red"] != (label in "hd")):
                raise ValueError("invalid-template-entry")
            vector = np.asarray(bitmaps[eid], dtype=np.float32).reshape(-1).copy()
            if (vector.size != BITMAP_SIZE[0] * BITMAP_SIZE[1] or not np.isfinite(vector).all()
                    or vector.min() < 0 or vector.max() > 1 or not 0 < float(vector.mean()) < 1):
                raise ValueError("invalid-template-bitmap")
            vector.setflags(write=False)
            self.templates[kind].append((dict(entry), vector))
            self.shape_templates[eid] = _shape_fields(vector)
            seen.add(eid)
        if any(not entries for entries in self.templates.values()):
            raise ValueError("missing-card-templates")
        self.comparisons = {}
        for kind, entries in self.templates.items():
            shapes = [self.shape_templates[e["id"]] for e, _ in entries]
            self.comparisons[kind] = (np.stack([v for _, v in entries]),
                                     *(np.stack([s[i].reshape(-1) for s in shapes]) for i in range(3)))
        self.provenance = {key: value for key, value in (provenance or {}).items()
                           if key in ("metadata_sha256", "bitmaps_sha256", "extra_bank_sha256",
                                      "extra_template_count", "extra_source_sha256s")}

    @classmethod
    def load(cls, metadata_path, bitmaps_path, *, extra_bank_path=None, evidence_root=None):
        """Optional pixel banks re-extract glyphs from manifest/SHA-verified originals."""
        import numpy as np

        metadata_path, bitmaps_path = Path(metadata_path), Path(bitmaps_path)
        if metadata_path.stat().st_size > 1_048_576 or bitmaps_path.stat().st_size > 16_777_216:
            raise ValueError("template-artifact-too-large")
        raw, bitmap_raw = metadata_path.read_bytes(), bitmaps_path.read_bytes()
        metadata = _json(raw)
        if not isinstance(metadata, list) or not all(isinstance(e, dict) for e in metadata):
            raise ValueError("invalid-template-metadata")
        with np.load(io.BytesIO(bitmap_raw), allow_pickle=False) as arrays:
            try:
                bitmaps = {e["id"]: arrays[e["id"]] for e in metadata if e.get("kind") in ("rank", "suit")}
            except (KeyError, TypeError) as exc:
                raise ValueError("missing-card-template-bitmap") from exc
        provenance = {"metadata_sha256": hashlib.sha256(raw).hexdigest(),
                      "bitmaps_sha256": hashlib.sha256(bitmap_raw).hexdigest()}
        if (extra_bank_path is None) != (evidence_root is None):
            raise ValueError("extra-bank-requires-evidence-root")
        if extra_bank_path is not None:
            extra, vectors, extra_provenance = cls._pixel_bank(extra_bank_path, evidence_root)
            metadata.extend(extra)
            if set(vectors) & set(bitmaps):
                raise ValueError("duplicate-pixel-template-id")
            bitmaps.update(vectors)
            provenance.update(extra_provenance)
        return cls(metadata, bitmaps, provenance)

    @staticmethod
    def _pixel_bank(bank_path, evidence_root):
        from PIL import Image

        root = Path(evidence_root).resolve()

        def local_path(value):
            if not isinstance(value, str) or not value or Path(value).is_absolute() or Path(value).drive:
                raise ValueError("invalid-pixel-source-path")
            path = (root / value).resolve()
            if not path.is_relative_to(root):
                raise ValueError("pixel-source-outside-root")
            return path

        bank_path = Path(bank_path)
        if bank_path.stat().st_size > 1_048_576:
            raise ValueError("pixel-bank-too-large")
        raw = bank_path.read_bytes()
        bank = _json(raw)
        if (not isinstance(bank, dict) or bank.get("schema") != "coinpoker-board-pixel-templates/1"
                or bank.get("annotation_origin") != "agent-generated"
                or bank.get("human_verified") is not False or bank.get("quality_approved") is not False
                or bank.get("calibration") != "unvalidated"
                or not isinstance(bank.get("sources"), list) or not 1 <= len(bank["sources"]) <= 32
                or not isinstance(bank.get("templates"), list) or not 1 <= len(bank["templates"]) <= 128):
            raise ValueError("invalid-pixel-bank")
        regions_path = local_path(bank.get("regions_file"))
        regions_raw = regions_path.read_bytes()
        if hashlib.sha256(regions_raw).hexdigest() != bank.get("regions_sha256"):
            raise ValueError("pixel-bank-regions-sha-mismatch")
        regions = _json(regions_raw)["regions"]
        sources = []
        for source in bank["sources"]:
            if not isinstance(source, dict) or not isinstance(source.get("record"), dict):
                raise ValueError("invalid-pixel-source")
            record = source["record"]
            required = ("frame_index", "source_utc_unix_ms", "captured_at_monotonic_ms", "source_id", "width", "height")
            digest = record.get("sha256")
            if (any(type(record.get(key)) is not int or record[key] < (0 if key == "captured_at_monotonic_ms" else 1)
                    for key in required)
                    or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                    or record["width"] * record["height"] > 16_777_216):
                raise ValueError("invalid-pixel-source-record")
            png, manifest = local_path(source.get("file")), local_path(source.get("manifest"))
            if (png.name != f"frame-{record['frame_index']:010d}.png" or png.parent != manifest.parent
                    or png.stat().st_size > 8_388_608 or manifest.stat().st_size > 2_097_152):
                raise ValueError("invalid-pixel-source")
            # The recorder may still append. Read complete rows only and demand
            # exactly one matching index, never a nearest-frame substitution.
            matches = []
            for line in manifest.read_bytes().split(b"\n")[:-1]:
                if not line:
                    continue
                row = _json(line)
                if isinstance(row, dict) and row.get("event") == "frame" and row.get("frame_index") == record["frame_index"]:
                    matches.append(row)
            if len(matches) != 1 or any(matches[0].get(key) != record[key] for key in (*required, "sha256")):
                raise ValueError("pixel-source-manifest-mismatch")
            original = matches[0]
            for key in ("generation", "source_process_created_at_100ns", "timestamp_basis",
                        "pixel_source", "readability", "occluded_regions", "png_bytes"):
                if key in record and (key not in original or record[key] != original[key]):
                    raise ValueError("pixel-source-manifest-mismatch")
            if ("generation" in record and record["generation"] is not None
                    and (type(record["generation"]) is not int or record["generation"] < 0)
                    or "source_process_created_at_100ns" in record
                    and (type(record["source_process_created_at_100ns"]) is not int
                         or record["source_process_created_at_100ns"] < 1)
                    or original.get("readability") not in (None, "full")
                    or original.get("pixel_source") not in (None, "visible_desktop_pixels")):
                raise ValueError("invalid-pixel-source-record")
            masks = original.get("occluded_regions", [])
            if not isinstance(masks, list) or any(not isinstance(m, list) or len(m) != 4
                    or any(type(v) is not int for v in m)
                    or not (0 <= m[0] < m[2] <= record["width"] and 0 <= m[1] < m[3] <= record["height"]) for m in masks):
                raise ValueError("invalid-pixel-source-masks")
            png_raw = png.read_bytes()
            if hashlib.sha256(png_raw).hexdigest() != digest or ("png_bytes" in original
                    and (type(original["png_bytes"]) is not int or len(png_raw) != original["png_bytes"])):
                raise ValueError("pixel-source-sha-mismatch")
            with Image.open(io.BytesIO(png_raw)) as image:
                if image.format != "PNG" or image.size != (record["width"], record["height"]):
                    raise ValueError("pixel-source-dimensions-mismatch")
                features = [slot_features(image.crop(laya_prep.box_px(regions[f"board_slot_{k}"], *image.size)))
                            for k in range(1, 6)]
                for k, feature in enumerate(features, 1):
                    box = laya_prep.box_px(regions[f"board_slot_{k}"], *image.size)
                    face = feature.get("card_bounds", [0, 0, box[2] - box[0], box[3] - box[1]])
                    bound = [box[0] + face[0], box[1] + face[1], box[0] + face[2], box[1] + face[3]]
                    if any(bound[0] < m[2] and bound[2] > m[0] and bound[1] < m[3] and bound[3] > m[1] for m in masks):
                        feature.update(state="unknown", reason="source-region-occluded")
                    feature["crop_bounds"] = list(box)
            sources.append(({**source, "record": original}, features))
        metadata, vectors, used = [], {}, set()
        for template in bank["templates"]:
            if (not isinstance(template, dict) or type(template.get("source_index")) is not int
                    or not 0 <= template["source_index"] < len(sources)
                    or type(template.get("slot")) is not int or not 1 <= template["slot"] <= 5
                    or template.get("kind") not in ("rank", "suit")
                    or not isinstance(template.get("label"), str)
                    or template["label"] not in (RANKS if template["kind"] == "rank" else SUITS)
                    or not isinstance(template.get("id"), str) or not template["id"] or template["id"] in vectors):
                raise ValueError("invalid-pixel-template")
            source, slots = sources[template["source_index"]]
            slot = slots[template["slot"] - 1]
            if slot["state"] != "card_candidate":
                raise ValueError("pixel-template-incomplete-card")
            feature = slot["features"][template["kind"]]
            witness_keys = ("card", "crop_bounds", "crop_pixel_sha256", "glyph_bounds", "glyph_pixel_sha256")
            if any(key in template for key in witness_keys):
                card = template.get("card")
                box = slot["crop_bounds"]
                glyph = feature["glyph_bounds"]
                expected_glyph = [box[0] + glyph[0], box[1] + glyph[1], box[0] + glyph[2], box[1] + glyph[3]]
                if (not isinstance(card, str) or len(card) != 2 or card[0] not in RANKS or card[1] not in SUITS
                        or template["label"] != card[0 if template["kind"] == "rank" else 1]
                        or feature["red"] != (card[1] in "hd")
                        or any(not isinstance(template.get(key), list) or len(template[key]) != 4
                               or any(type(v) is not int for v in template[key]) for key in ("crop_bounds", "glyph_bounds"))
                        or template.get("crop_bounds") != box
                        or template.get("crop_pixel_sha256") != slot["pixel_sha256"]
                        or template.get("glyph_bounds") != expected_glyph
                        or template.get("glyph_pixel_sha256") != feature["glyph_pixel_sha256"]):
                    raise ValueError("pixel-template-witness-mismatch")
            pixel_source = {"file": source["file"], **source["record"], "slot": template["slot"],
                            "crop_bounds": slot["crop_bounds"], "crop_pixel_sha256": slot["pixel_sha256"],
                            "glyph_bounds": [slot["crop_bounds"][0] + feature["glyph_bounds"][0],
                                             slot["crop_bounds"][1] + feature["glyph_bounds"][1],
                                             slot["crop_bounds"][0] + feature["glyph_bounds"][2],
                                             slot["crop_bounds"][1] + feature["glyph_bounds"][3]],
                            "glyph_pixel_sha256": feature["glyph_pixel_sha256"],
                            "regions_sha256": bank["regions_sha256"]}
            metadata.append({"id": template["id"], "kind": template["kind"], "label": template["label"],
                             "w": feature["w"], "h": feature["h"], "red": feature["red"],
                             "source": "agent-pixel-bank:" + source["file"], "pixel_source": pixel_source})
            vectors[template["id"]] = feature["bitmap"]
            used.add(source["record"]["sha256"])
        return metadata, vectors, {"extra_bank_sha256": hashlib.sha256(raw).hexdigest(),
                                   "extra_template_count": len(metadata), "extra_source_sha256s": sorted(used)}

    def match(self, kind, feature):
        import numpy as np

        unknown = {"label": None, "reason": "invalid-ink-feature", "distance": None,
                   "distance_metric": "dual-ink-chamfer", "mask_distance": None,
                   "other_label_distance": None, "template_id": None}
        if kind not in ("rank", "suit") or not isinstance(feature, dict):
            return unknown
        try:
            vector = np.asarray(feature["bitmap"], dtype=np.float32).reshape(-1)
        except (KeyError, TypeError, ValueError):
            return unknown
        if (vector.size != 384 or not np.isfinite(vector).all() or vector.min() < 0 or vector.max() > 1
                or not 0 < float(vector.mean()) < 1 or type(feature.get("red")) is not bool
                or any(type(feature.get(key)) is not int or feature[key] < 1 for key in ("w", "h"))):
            return unknown
        try:
            shape = _shape_fields(vector)
        except ValueError:
            return unknown
        vectors, masks, ink_fields, background_fields = self.comparisons[kind]
        query, ink, background = (s.reshape(-1) for s in shape)
        # The same four symmetric means as _shape_distance, batched across every
        # template, including differently sized distinct-label competitors.
        distances = np.maximum.reduce((
            (masks * ink).sum(axis=1) / masks.sum(axis=1),
            ink_fields[:, query].mean(axis=1),
            ((~masks) * background).sum(axis=1) / (~masks).sum(axis=1),
            background_fields[:, ~query].mean(axis=1))) / BITMAP_SIZE[1]
        mask_distances = np.abs(vectors - vector).mean(axis=1)
        best, mask_best = {}, {}
        for (entry, _), distance, mask_distance in zip(self.templates[kind], distances, mask_distances):
            if entry["red"] != feature["red"]:
                continue
            distance, mask_distance = float(distance), float(mask_distance)
            label = entry["label"]
            if label not in best or distance < best[label][0]:
                best[label] = distance, entry
            if label not in mask_best or mask_distance < mask_best[label]:
                mask_best[label] = mask_distance
        ranked = sorted(best.values(), key=lambda pair: (pair[0], pair[1]["id"]))
        if not ranked:
            return {**unknown, "reason": "no-colour-compatible-template"}
        distance, entry = ranked[0]
        other = ranked[1][0] if len(ranked) > 1 else None
        label = entry["label"]
        result = {**unknown, "distance": distance, "other_label_distance": other,
                  "mask_distance": mask_best[label]}
        # Compare distinct labels, including competitors with different dimensions.
        # Filtering competitors by size can create a misleadingly unique match.
        if other is None or other < DISTINCT_LABEL_RATIO * distance + DISTINCT_LABEL_GAP:
            result["reason"] = "ambiguous-distinct-label"
        elif distance > MAX_SHAPE_DISTANCE or mask_best[label] > MAX_MASK_DISTANCE:
            result["reason"] = "template-distance"
        elif min(mask_best, key=mask_best.get) != label:
            result["reason"] = "mask-shape-label-disagreement"
        elif not (0.7 <= feature["w"] / entry["w"] <= 1.35
                  and 0.7 <= feature["h"] / entry["h"] <= 1.35
                  and 0.8 <= (feature["w"] / feature["h"]) / (entry["w"] / entry["h"]) <= 1.25):
            result["reason"] = "template-size-mismatch"
        else:
            result.update(label=entry["label"], template_id=entry["id"],
                          label_source=entry["source"], reason="provisional-template-match")
            if "pixel_source" in entry:
                result["pixel_source"] = dict(entry["pixel_source"])
        return result

    def recognize_slots(self, images):
        if len(images) != 5:
            raise ValueError("exactly-five-board-slots-required")
        slots = []
        for index, image in enumerate(images, 1):
            feature = slot_features(image)
            slot = {key: value for key, value in feature.items() if key != "features"}
            slot.update(slot=index, card=None)
            if slot["state"] == "card_candidate":
                matches = {kind: self.match(kind, feature["features"][kind]) for kind in ("rank", "suit")}
                slot["matches"] = matches
                if all(m["label"] is not None for m in matches.values()):
                    slot["card"] = matches["rank"]["label"] + matches["suit"]["label"]
                else:
                    slot.update(state="unknown", reason="unmatched-card-ink")
            slot["status"] = "provisional" if slot["card"] else "empty" if slot["state"] == "empty_candidate" else "unknown"
            slots.append(slot)
        cards, reason = assemble_board(slots)
        return {"schema": "coinpoker-board-template-diagnostic/1", **MARKERS,
                "scope": "board-card-slots-only", "scene_verified": False,
                "candidate_cards": cards, "reason": reason, "slots": slots,
                "empty_board_supported": cards == [],
                "stage": {3: "flop", 4: "turn", 5: "river"}.get(len(cards)) if cards else None,
                "template_artifacts": dict(self.provenance),
                "match_rules": {"distance_metric": "dual-ink-chamfer",
                                "max_shape_distance": MAX_SHAPE_DISTANCE,
                                "max_mask_distance": MAX_MASK_DISTANCE,
                                "distinct_label_ratio": DISTINCT_LABEL_RATIO,
                                "distinct_label_gap": DISTINCT_LABEL_GAP}}

    def recognize_frame(self, image, regions):
        from PIL import Image

        if not isinstance(image, Image.Image) or min(image.size) < 8:
            raise ValueError("invalid-board-frame")
        if isinstance(regions, dict) and "regions" in regions:
            regions = regions["regions"]
        if not isinstance(regions, dict):
            raise ValueError("invalid-board-regions")
        bounds, previous = [], None
        for k in range(1, 6):
            roi = regions.get(f"board_slot_{k}")
            if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in roi)
                    or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1)):
                raise ValueError("invalid-board-regions")
            if previous is not None and (previous[2] > roi[0] or tuple(previous[1::2]) != tuple(roi[1::2])):
                raise ValueError("invalid-board-regions")
            bounds.append(laya_prep.box_px(roi, *image.size))
            previous = roi
        # Floor/ceil projection can share a boundary pixel at smaller scales.
        if any(b[0] >= b[2] or b[1] >= b[3] for b in bounds):
            raise ValueError("invalid-board-regions")
        result = self.recognize_slots([image.crop(box) for box in bounds])
        result.update(frame_dimensions=list(image.size), crop_bounds=[list(b) for b in bounds])
        import numpy as np
        for slot, box in zip(result["slots"], bounds):
            slot["crop_bounds"] = list(box)
            face = slot.get("card_bounds")
            evidence = [box[0] + face[0], box[1] + face[1], box[0] + face[2], box[1] + face[3]] if face else list(box)
            slot["evidence_bounds"] = evidence
            slot["evidence_pixel_sha256"] = hashlib.sha256(
                np.asarray(image.crop(evidence).convert("RGB")).tobytes()).hexdigest()
        pixels = np.asarray(image.convert("RGB"))
        result["frame_pixel_sha256"] = hashlib.sha256(pixels.tobytes()).hexdigest()
        if pixels.size == 0 or int(np.ptp(pixels, axis=(0, 1)).max()) < 4:
            result.update(candidate_cards=None, empty_board_supported=False, stage=None, reason="blank-frame")
            for slot in result["slots"]:
                slot.update(card=None, status="unknown", state="unknown", reason="blank-frame")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--bitmaps", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--extra-bank", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("images", type=Path, nargs="+")
    args = parser.parse_args()
    recognizer = BoardTemplateRecognizer.load(args.metadata, args.bitmaps,
        extra_bank_path=args.extra_bank, evidence_root=args.evidence_root)
    regions = _json(args.regions.read_bytes())
    from PIL import Image
    for path in args.images:
        with Image.open(path) as image:
            result = recognizer.recognize_frame(image, regions)
        print(json.dumps({"file": str(path), **result}, allow_nan=False))


if __name__ == "__main__":
    main()
