"""Independent provisional numeric reads from already captured original pixels.

No acquisition, OCR subprocess, action/occupancy inference, or runtime changes.
The caller must validate the original PNG and source receipt before calling read.
Caches contain only computation, not receipts or leases. Draft template labels
and the agent-checked private references below are NOT accuracy certification.
"""

import copy
import hashlib
import io
import json
import math
import re
import time
from collections import OrderedDict
from pathlib import Path

try:
    from .laya_actions import CropTemplates, Template, _score, _normal_mask
    from .laya_prep import _components, _text_mask, box_px
except ImportError:
    from laya_actions import CropTemplates, Template, _score, _normal_mask
    from laya_prep import _components, _text_mask, box_px


VERSION = "numeric_cpu_v1"
MAX_CACHE = 192
MAX_PNG_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
REVIEW = ".local/laya/datasets/observing-20261010-v2-staging/human-review-20261010/labels.draft.json"
CURRENT = ".local/captures/utc-1792003095-224479100-practice"
EARLIER = ".local/captures/utc-1791991640-171220300-practice"
SOURCE_RECORDS = {
    CURRENT: (3235148086084101343, 134364766616945609),
    EARLIER: (4030215874350685307, 134364617596088162),
}
# Exact source-projected geometry of the annotations below. A caller's changed
# region config must not relabel some other same-length number as a donor.
REFERENCE_GEOMETRY = {
    (927, 705): "788dd5249fc7e6e6a96bac8350595cc7ffd30443c8752af907b8a84b49f0b82b",
    (890, 678): "b723079aebc3caa6eeb90d5756da26187252cde690354de27c4c65ff7ac4240c",
}

# Search envelopes measured on manifest-bound 927x705 frame10 (a41f838e...)
# and checked on 890x678 originals1/571. They do not include HUD counters,
# names, stakes, or the lower central chip-total pill. Actual text is segmented
# inside each envelope, and a dark numeric background is required for wagers.
WAGERS = ((.335, .246, .456, .304), (.660, .275, .790, .370),
          (.650, .560, .795, .686), (.540, .630, .640, .712),
          (.210, .576, .330, .680), (.220, .284, .345, .365))

# Agent-visible annotations of exact originals, not guessed expected values.
# The loader checks the manifest, original bytes, geometry, and segmentation.
# Distinct held-out frames are tested separately; these donors are training.
REFERENCES = (
    (CURRENT, 1, "bb0f781f151fdccacab2a8c1f4980bf7f9718b93df62cc26b4b82920131e1358", (927, 705),
     (("stack", 1, "5.07"), ("stack", 2, "7.93"), ("stack", 3, "6.64"),
      ("stack", 4, "4.99"), ("stack", 5, "2.5"), ("stack", 6, "8.22"))),
    (CURRENT, 10, "a41f838ef94fba7c71fd7a69dfe84ea106351706b30ad59a6454e5d080fbc5b5", (927, 705),
     (("stack", 1, "5.02"), ("stack", 2, "7.93"), ("stack", 3, "6.64"),
      ("stack", 4, "5"), ("stack", 5, "2.5"), ("stack", 6, "8.2"),
      ("pot", 0, "0.07"), ("wager", 1, "0.05"), ("wager", 6, "0.02"))),
    (CURRENT, 21, "4704aeee5a8addbedecea87ddb67c71386ce5e4d5f1d0cbfb7f5b492e8132a50", (927, 705),
     (("pot", 0, "0.04"),)),
    (CURRENT, 50, "b3bbb2ff22d2ea6bc6ce138f6c35aa6c265bc0e0d7b26ffd6b0047b4f0ba8b63", (927, 705),
     (("stack", 1, "5.07"), ("stack", 2, "7.88"), ("stack", 3, "6.64"),
      ("stack", 4, "5"), ("stack", 5, "2.45"), ("stack", 6, "8.2"),
      ("pot", 0, "0.12"), ("wager", 1, "0.02"), ("wager", 2, "0.05"), ("wager", 5, "0.05"))),
    (CURRENT, 100, "3175486390a9cb3509edf84d7b3bc43489e5089aae787ab3b9600b72221a0f0c", (927, 705),
     (("stack", 1, "5.07"), ("stack", 2, "7.31"), ("stack", 3, "6.59"),
      ("stack", 4, "5"), ("stack", 5, "3.12"), ("stack", 6, "8.2"),
      ("pot", 0, "0.07"), ("wager", 2, "0.02"), ("wager", 3, "0.05"))),
    (CURRENT, 200, "6768752e7c0b40d496bc410a4638d7525e19f61288552c5b4c86855f9cee0aeb", (927, 705),
     (("stack", 1, "5.07"), ("stack", 2, "7.31"), ("stack", 3, "6.44"),
      ("stack", 4, "4.52"), ("stack", 6, "8.27"),
      ("pot", 0, "0.63"), ("wager", 3, "0.15"), ("wager", 4, "0.48"))),
    (CURRENT, 281, "53ec390a0f45ceb529762989e18542373de99b4d3b1d4f1568ee03921b3126e9", (927, 705),
     (("pot", 0, "0.52"),)),
    (CURRENT, 351, "78c0392f3a5427b4e019e91c9e2376124a3370e950c1bce7ae58dd42686b3386", (927, 705),
     (("pot", 0, "0.19"), ("stack", 4, "5.13"))),
    (EARLIER, 1, "4b2dddd4439028d3abf52ec1dba3c6d5efc0fc2b0035df1e51450e7add35a2ac", (890, 678),
     (("stack", 1, "6.89"), ("stack", 2, "5"), ("stack", 3, "7.26"),
      ("stack", 4, "5.03"), ("stack", 5, "13.77"), ("stack", 6, "4.77"),
      ("pot", 0, "0.67"))),
)


def parse_literal(literal):
    """Exact displayed decimal -> integer hundredths; no locale/rounding guess."""
    if not isinstance(literal, str) or not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,2})?", literal):
        return None
    whole, dot, fraction = literal.partition(".")
    return int(whole) * 100 + (int(fraction.ljust(2, "0")) if dot else 0)


def _hash(crop):
    return hashlib.sha256(crop.convert("RGB").tobytes()).hexdigest()


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _mask(crop, kind):
    import numpy as np
    rgb = np.asarray(crop.convert("RGB"), dtype=np.int16)
    r, g, b = rgb.transpose(2, 0, 1)
    if kind == "stack":
        # Includes dimmed gold without admitting grayscale names or white HUDs.
        return _text_mask(rgb, "gold") & (r >= g * 1.10) & (g >= b * 1.65) & (r - b >= 40)
    return (rgb.min(axis=2) >= 145) & (rgb.max(axis=2) - rgb.min(axis=2) <= 40)


def _parts(mask):
    return [[p["x0"], p["y0"], p["x1"], p["y1"], p["area"]] for p in _components(mask)]


def _signature(glyph):
    import numpy as np
    return _normal_mask(np.asarray(glyph.convert("L")) > 155)


def _numeric_score(left, right):
    import numpy as np
    # Badge tolerance alone conflates small 5/8 shapes. Retain its aspect/raster
    # checks, then require undilated ink with ONE consistent raster translation,
    # not independently dilated strokes. This accounts for subpixel font phase.
    padded = np.pad(left[0], 1)
    ink = max(float(2 * np.minimum(padded[dy:dy + 24, dx:dx + 100], right[0]).sum()
                    / (left[3] + right[3])) for dy in range(3) for dx in range(3))
    return _score(left, right) * ink


def _lines(crop, kind):
    """Keep every tiny punctuation component, grouping only aligned text rows."""
    import numpy as np
    mask = _mask(crop, kind)
    parts = [b for b in _parts(mask) if b[4] >= 1]
    if len(parts) > 96:
        return []
    major = [b for b in parts if 6 <= b[3] - b[1] <= 32 and 2 <= b[2] - b[0] <= 25]
    groups = []
    for part in sorted(major, key=lambda b: (b[1], b[0])):
        group = next((g for g in groups if abs(g[0][1] - part[1]) <= 2
                      and abs(g[0][3] - part[3]) <= 2), None)
        if group is None:
            groups.append([part])
        else:
            group.append(part)
    lines = []
    rgb = np.asarray(crop.convert("RGB"), dtype=np.int16)
    for group in groups:
        y0, y1 = min(b[1] for b in group), max(b[3] for b in group)
        h = y1 - y0
        x0, x1 = min(b[0] for b in group), max(b[2] for b in group)
        # Include baseline punctuation beside/between digits, but never a
        # detached chip above the numeric line. No area-based decimal deletion.
        selected = [b for b in parts if b[1] >= y0 - 2 and b[1] <= y1 + 2
                    and b[3] <= y1 + max(4, h // 3)
                    and x0 - h <= b[0] < x1 + h]
        if not selected:
            continue
        selected.sort(key=lambda b: b[0])
        a, c = min(b[0] for b in selected), max(b[2] for b in selected)
        hull = [a, min(b[1] for b in selected), c, max(b[3] for b in selected)]
        if hull[0] <= 0 or hull[1] <= 0 or hull[2] >= crop.width or hull[3] >= crop.height:
            continue
        # A broad candidate may contain chip artwork. Values sit on a dark
        # pill/stack panel; green felt or chip-colored backgrounds are rejected.
        foreground = mask[y0:y1, a:c]
        background = rgb[y0:y1, a:c][~foreground]
        if len(background) < 8 or float(np.median(background.max(axis=1))) > 90:
            continue
        stray = False
        for part in parts:
            if (part in selected or part[3] - part[1] > max(4, round(h * .30))
                    or part[2] < a - h or part[0] > c + h
                    or part[3] < y0 - h * .75 or part[1] > y1 + h * .35):
                continue
            lo, top = max(0, part[0] - 2), max(0, part[1] - 2)
            hi, bottom = min(crop.width, part[2] + 2), min(crop.height, part[3] + 2)
            halo = rgb[top:bottom, lo:hi][~mask[top:bottom, lo:hi]]
            if len(halo) >= 4 and float(np.median(halo.max(axis=1))) <= 90:
                stray = True
                break
        if stray:
            continue
        if any(b[0] < a or b[2] > c for b in group):
            continue
        lines.append((mask, selected, hull))
    return lines


def _glyph(mask, bounds):
    from PIL import Image
    return Image.fromarray((mask[bounds[1]:bounds[3], bounds[0]:bounds[2]] * 255).astype("uint8")).convert("RGB")


def _punctuation(parts, height):
    # A period is tiny, square-ish and on the baseline. Tall/narrow commas and
    # detached dots do not silently become a decimal or get dropped.
    return [i for i, p in enumerate(parts) if p[3] - p[1] <= max(4, round(height * .30))]


def _annotated_glyphs(crop, kind, literal):
    lines = _lines(crop, kind)
    if len(lines) != 1:
        raise ValueError("numeric-reference-not-one-line")
    mask, parts, _ = lines[0]
    if len(parts) != len(literal):
        raise ValueError("numeric-reference-component-count-mismatch")
    height = max(p[3] - p[1] for p in parts)
    punctuation = _punctuation(parts, height)
    if punctuation != [i for i, ch in enumerate(literal) if ch == "."]:
        raise ValueError("numeric-reference-decimal-mismatch")
    return [(ch, _glyph(mask, part)) for ch, part in zip(literal, parts)]


def _original(root, directory, index, sha256, size):
    """Private bounded donor intake: never trust an annotation's path alone."""
    from PIL import Image
    source_record = SOURCE_RECORDS.get(directory)
    if source_record is None:
        raise ValueError("numeric-reference-source-unqualified")
    root = Path(root).resolve()
    directory = (root / directory).resolve()
    if directory.parent != root / ".local/captures":
        raise ValueError("numeric-reference-path-outside-captures")
    manifest = directory / "manifest.jsonl"
    if manifest.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("numeric-reference-manifest-too-large")
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    matches = [r for r in rows if r.get("event") == "frame" and r.get("frame_index") == index]
    if len(matches) != 1:
        raise ValueError("numeric-reference-manifest-ambiguous")
    row = matches[0]
    path = directory / ("frame-%010d.png" % index)
    with path.open("rb") as stream:
        png = stream.read(MAX_PNG_BYTES + 1)
    if (not 0 < len(png) <= MAX_PNG_BYTES or len(png) != row.get("png_bytes")
            or row.get("sha256") != sha256 or hashlib.sha256(png).hexdigest() != sha256
            or (row.get("width"), row.get("height")) != tuple(size)
            or row.get("pixel_source") != "visible_desktop_pixels"
            or (row.get("source_id"), row.get("source_process_created_at_100ns")) != source_record
            or row.get("timestamp_basis") != "capture_call_start"
            or row.get("readability") != "full" or row.get("occluded_regions")
            or type(row.get("source_utc_unix_ms")) is not int
            or type(row.get("captured_at_monotonic_ms")) is not int):
        raise ValueError("numeric-reference-original-mismatch")
    with Image.open(io.BytesIO(png)) as original:
        if original.format != "PNG" or original.size != tuple(size):
            raise ValueError("numeric-reference-dimensions-mismatch")
        image = original.convert("RGB")
    return image, row


class NumericReader:
    def __init__(self, root, regions=None, templates=None):
        self.root = Path(root).resolve()
        self.regions = copy.deepcopy(regions) if regions is not None else json.loads(
            (self.root / "crates/ingest/assets/laya/regions.json").read_bytes())
        configured = self.regions.get("regions", self.regions)
        for key in ["pot", *["seat_%d_stack" % seat for seat in range(1, 7)]]:
            roi = configured.get(key)
            if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                    or any(type(n) not in (float, int) or not math.isfinite(n) for n in roi)
                    or not 0 <= roi[0] < roi[2] <= 1 or not 0 <= roi[1] < roi[3] <= 1):
                raise ValueError("invalid-numeric-regions")
        self.templates = templates if templates is not None else (
            CropTemplates.from_draft_review(self.root / REVIEW, self.root)
            if (self.root / REVIEW).is_file() else CropTemplates())
        # Do not mutate a shared ActionReader bank during numeric-only bootstrap.
        self.digits = list(self.templates.digits)
        self.pot_labels = []
        self.reference_errors = []
        self.reference_count = 0
        self._cache = OrderedDict()
        self._glyph_cache = OrderedDict()
        if templates is None:
            self._load_references()
        # Numeric components cannot be wider than this support. Do not clip
        # malformed wide draft glyphs into an apparently valid digit template.
        self.digits = [t for t in self.digits if not t.mask[0][:, 36:].any()]
        if len(self.digits) > 768:
            raise ValueError("numeric-template-limit")
        import numpy as np
        unique = {}
        for template in self.digits:
            key = template.label, template.mask[1], template.mask[0].tobytes()
            unique.setdefault(key, template)
        self._match_digits = list(unique.values())
        self._font_data = (np.stack([t.mask[0][:, :36] for t in self._match_digits]),
                           np.asarray([t.mask[1] for t in self._match_digits]),
                           np.stack([t.mask[2][:, :36] for t in self._match_digits]),
                           np.asarray([t.mask[3] for t in self._match_digits])) if self._match_digits else None

    def _boxes(self, image):
        regions = self.regions.get("regions", self.regions)
        boxes = {"pot": box_px(regions["pot"], *image.size)}
        for seat in range(1, 7):
            boxes["stack%d" % seat] = box_px(regions["seat_%d_stack" % seat], *image.size)
            boxes["wager%d" % seat] = box_px(WAGERS[seat - 1], *image.size)
        return boxes

    def _load_references(self):
        for directory, index, sha256, size, annotations in REFERENCES:
            try:
                image, row = _original(self.root, directory, index, sha256, size)
                boxes = self._boxes(image)
                geometry = hashlib.sha256(json.dumps(boxes, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
                if geometry != REFERENCE_GEOMETRY.get(image.size):
                    raise ValueError("numeric-reference-annotation-geometry-mismatch")
                pending, labels = [], []
                for kind, seat, literal in annotations:
                    bounds = boxes[kind + str(seat) if seat else kind]
                    crop = image.crop(bounds)
                    if kind == "pot":
                        label = self._pot_label(crop)
                        if label is None:
                            raise ValueError("numeric-reference-pot-label-missing")
                        labels.append(Template("Pot", _signature(label), {"path": directory,
                            "sha256": sha256, "frame_index": index, "bounds": list(bounds),
                            "annotation": "agent_visible_original_not_human_ground_truth"}, _hash(label)))
                    evidence = {"path": directory, "frame_index": index, "sha256": sha256,
                        "manifest_source_utc_unix_ms": row["source_utc_unix_ms"],
                        "bounds": list(bounds), "literal": literal,
                        "annotation": "agent_visible_original_training_not_heldout"}
                    for char, glyph in _annotated_glyphs(crop, kind, literal):
                        signature = _signature(glyph)
                        if signature is None:
                            raise ValueError("numeric-reference-unreadable-glyph")
                        pending.append(Template(char, signature, copy.deepcopy(evidence), _hash(glyph)))
                self.digits.extend(pending)
                self.pot_labels.extend(labels)
                self.reference_count += 1
            except (OSError, ValueError, KeyError, TypeError):
                self.reference_errors.append({"directory": directory, "frame_index": index,
                                              "reason": "numeric-reference-unavailable-or-invalid"})

    @staticmethod
    def _pot_label(crop):
        import numpy as np
        from PIL import Image
        rgb = np.asarray(crop.convert("RGB"), dtype=np.int16)
        r, g, b = rgb.transpose(2, 0, 1)
        blue = (b >= 140) & (g >= 85) & (b - r >= 55) & (g - r >= 35)
        parts = [p for p in _parts(blue) if p[4] >= 3]
        if len(parts) != 3:
            return None
        parts.sort(key=lambda p: p[0])
        if any(abs(p[3] - parts[0][3]) > 2 for p in parts):
            return None
        x0, x1 = parts[0][0], parts[-1][2]
        y0, y1 = min(p[1] for p in parts), max(p[3] for p in parts)
        return Image.fromarray((blue[y0:y1, x0:x1] * 255).astype("uint8")).convert("RGB")

    def _match(self, glyph, *, punctuation=False):
        import numpy as np
        key = glyph.size, punctuation, _hash(glyph)
        if key in self._glyph_cache:
            self._glyph_cache.move_to_end(key)
            return self._glyph_cache[key]
        signature = _signature(glyph)
        if signature is None or signature[0][:, 36:].any():
            return None
        if self._font_data is None:
            return None
        canvas, aspects, dilated, totals = self._font_data
        tolerant = (np.minimum(dilated, signature[0][:, :36]).sum(axis=(1, 2)) / signature[3]
                    + np.minimum(canvas, signature[2][:, :36]).sum(axis=(1, 2)) / totals) * .5
        scores = tolerant * np.minimum(aspects, signature[1]) / np.maximum(aspects, signature[1])
        # Ink agreement is <= 1. Below this bound a template cannot win OR
        # violate the distinct-label margin. Skip only provably irrelevant work.
        indices = [i for i, template in enumerate(self._match_digits)
                   if (template.label == ".") == punctuation
                   and scores[i] >= self.templates.min_score - self.templates.margin]
        if not indices:
            self._glyph_cache[key] = None
            if len(self._glyph_cache) > MAX_CACHE:
                self._glyph_cache.popitem(last=False)
            return None
        padded = np.pad(signature[0][:, :36], 1)
        candidates = canvas[indices]
        raw = np.maximum.reduce([np.minimum(candidates, padded[dy:dy + 24, dx:dx + 36]).sum(axis=(1, 2))
                                 for dy in range(3) for dx in range(3)])
        scores = scores[indices] * 2 * raw / (totals[indices] + signature[3])
        by_label = {}
        for index, score in zip(indices, scores):
            template = self._match_digits[index]
            if score > by_label.get(template.label, (-1, None))[0]:
                by_label[template.label] = float(score), template
        ranked = sorted(by_label.items(), key=lambda item: item[1][0], reverse=True)
        label = None
        if (ranked and ranked[0][1][0] >= self.templates.min_score
                and (len(ranked) < 2 or ranked[0][1][0] - ranked[1][1][0] >= self.templates.margin)):
            label = ranked[0][0]
        self._glyph_cache[key] = label
        if len(self._glyph_cache) > MAX_CACHE:
            self._glyph_cache.popitem(last=False)
        return label

    def _compute(self, crop, kind):
        import numpy as np
        if kind == "pot":
            label = self._pot_label(crop)
            if label is None:
                return {"status": "unknown", "reason": "upper-pot-label-not-visible"}
            if self.pot_labels and max(_numeric_score(_signature(label), t.mask)
                                      for t in self.pot_labels) < self.templates.min_score:
                return {"status": "unknown", "reason": "upper-pot-label-unrecognized"}
            if not self.pot_labels:
                return {"status": "unknown", "reason": "upper-pot-label-template-unavailable"}
        lines = _lines(crop, kind)
        if not lines:
            rgb = np.asarray(crop.convert("RGB"), dtype=np.int16)
            r, g, b = rgb.transpose(2, 0, 1)
            felt = (g >= 45) & (g > r * 1.35) & (g > b * 1.12) & (r < 90) & (g < 150)
            if kind == "wager" and float(felt.mean()) >= .985 and not _mask(crop, kind).any():
                return {"status": "empty", "reason": "visible-felt-with-no-wager-line"}
            return {"status": "unknown", "reason": "numeric-line-unreadable-or-absent"}
        if len(lines) != 1:
            return {"status": "unknown", "reason": "multiple-numeric-line-candidates"}
        mask, parts, hull = lines[0]
        height = max(p[3] - p[1] for p in parts)
        punctuation = _punctuation(parts, height)
        if len(parts) > 12 or len(punctuation) > 1:
            return {"status": "unknown", "reason": "unsupported-numeric-format"}
        if any(right[0] - left[2] > max(4, round(height * .38)) for left, right in zip(parts, parts[1:])):
            return {"status": "unknown", "reason": "unsupported-numeric-spacing"}
        literal = ""
        for index, part in enumerate(parts):
            if index in punctuation:
                w, h = part[2] - part[0], part[3] - part[1]
                if (abs(w - h) > 1 or part[3] < hull[3] - 1 or part[1] < hull[3] - height * .35
                        or index == 0 or index == len(parts) - 1):
                    return {"status": "unknown", "reason": "unsupported-punctuation"}
            elif abs(part[3] - hull[3]) > 2 or part[3] - part[1] < height * .75:
                return {"status": "unknown", "reason": "misaligned-numeric-components"}
            char = self._match(_glyph(mask, part), punctuation=index in punctuation)
            if char is None:
                return {"status": "unknown", "reason": "unsupported-or-ambiguous-glyph"}
            literal += char
        value = parse_literal(literal)
        if value is None:
            return {"status": "unknown", "reason": "unsupported-numeric-format"}
        return {"status": "provisional", "literal": literal, "value": value,
                "reason": "visible-numeric-template-match"}

    def read(self, image, capture, occluded_regions=None):
        started = time.perf_counter()
        if not isinstance(capture, dict):
            raise ValueError("numeric-original-receipt-required")
        if (any(type(capture.get(key)) is not int for key in ("width", "height"))
                or (capture["width"], capture["height"]) != image.size
                or not 100 <= image.width <= 4096 or not 80 <= image.height <= 4096):
            raise ValueError("numeric-original-dimensions-mismatch")
        timestamp = capture.get("captured_at_unix_ms", capture.get("source_utc_unix_ms"))
        if type(timestamp) is not int or timestamp <= 0:
            raise ValueError("numeric-original-timestamp-required")
        if ("source_utc_unix_ms" in capture and capture["source_utc_unix_ms"] != timestamp):
            raise ValueError("numeric-original-clock-disagreement")
        if not re.fullmatch(r"[a-f0-9]{64}", str(capture.get("sha256", ""))):
            raise ValueError("numeric-original-png-sha-required")
        if len(json.dumps(capture, allow_nan=False).encode("utf-8")) > 32768:
            raise ValueError("numeric-original-receipt-too-large")
        capture = copy.deepcopy(capture)
        image = image.convert("RGB")
        boxes = self._boxes(image)
        masks = occluded_regions if occluded_regions is not None else []
        original_masks = capture.get("occluded_regions", [])
        mask_error = (not isinstance(masks, (list, tuple)) or not isinstance(original_masks, (list, tuple)))
        if not mask_error:
            masks = [*original_masks, *masks]
            mask_error = len(masks) > 64
        qualified_masks = []
        if not mask_error:
            for item in masks:
                if isinstance(item, dict):
                    item = item.get("bounds")
                if (not isinstance(item, (list, tuple)) or len(item) != 4
                        or any(type(n) is not int for n in item)
                        or not 0 <= item[0] < item[2] <= image.width
                        or not 0 <= item[1] < item[3] <= image.height):
                    mask_error = True
                    break
                qualified_masks.append(item)
        fields = {}
        geometry = json.dumps(self.regions, sort_keys=True, allow_nan=False)
        for name, bounds in boxes.items():
            kind = "pot" if name == "pot" else "stack" if name.startswith("stack") else "wager"
            crop = image.crop(bounds)
            digest = _hash(crop)
            field = {"status": "unknown", "literal": None, "value": None,
                     "capture": copy.deepcopy(capture), "bounds": list(bounds),
                     "crop_sha256": digest, "crop_hash_basis": "RGB-pixels",
                     "recognizer_version": VERSION}
            if mask_error or capture.get("readability") == "unknown":
                computed = {"status": "unknown", "reason": "invalid-occlusion-or-unreadable-source"}
            elif any(_overlap(bounds, mask) for mask in qualified_masks):
                computed = {"status": "occluded", "reason": "numeric-region-occluded"}
            else:
                key = kind, image.size, tuple(bounds), geometry, digest
                if key in self._cache:
                    self._cache.move_to_end(key)
                    computed = self._cache[key]
                else:
                    computed = self._compute(crop, kind)
                    self._cache[key] = copy.deepcopy(computed)
                    if len(self._cache) > MAX_CACHE:
                        self._cache.popitem(last=False)
            field.update(copy.deepcopy(computed))
            fields[name] = field
        return {"schema_version": 1, "source": "cpu-visible-numeric", "provisional": True,
                "quality_approved": False, "human_reviewed": False, "capture": capture,
                "expires_at_unix_ms": timestamp + 1500, "pot": fields["pot"],
                "seats": [{"seat": seat, "stack": fields["stack%d" % seat],
                           "wager": fields["wager%d" % seat]} for seat in range(1, 7)],
                "original_png_verification": "caller_required",
                "reference_count": self.reference_count, "reference_errors": copy.deepcopy(self.reference_errors),
                "processing_ms": round((time.perf_counter() - started) * 1000, 3)}
