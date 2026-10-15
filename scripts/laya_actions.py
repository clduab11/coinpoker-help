"""Fast, provisional reads of explicit action badges and visible wager literals.

No capture, model, gameplay, stack-delta, or hand-boundary side effects. Templates
come from source-bound visible crops, not color-to-action rules. Similarity scores
are not calibrated probabilities, and visible wagers are NOT commitments/costs.
"""

from collections import deque
import copy
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import time


ACTIONS = ("fold", "check", "bet", "call", "raise", "all_in")
BADGE_LITERALS = {"FOLD": "fold", "CHECK": "check", "BET": "bet", "CALL": "call",
                  "RAISE": "raise", "ALL-IN": "all_in"}
REFERENCE_SIZE = (900, 686)
# Agent-measured label strips, excluding names, stacks, avatars, and timer digits.
BADGE_BOUNDS = ((390, 114, 451, 134), (715, 169, 776, 190), (734, 442, 795, 462),
                (390, 563, 451, 585), (47, 442, 108, 462), (65, 169, 126, 190))
WAGER_BOUNDS = ((315, 172, 387, 232), (567, 199, 714, 295), (576, 376, 733, 473),
                (409, 422, 594, 506), (195, 376, 333, 473), (195, 199, 333, 295))
MAX_TEMPLATES = 256
MAX_EVENTS = 512
MAX_FIELD_AGE_MS = 1500
DEFAULT_INTERVAL_MS = 250
MAX_CAPTURE_GAP_MS = 1500


def scaled_bounds(bounds, size):
    if len(size) != 2 or any(type(n) is not int or n <= 0 for n in size):
        raise ValueError("invalid-frame-size")
    box = tuple((n * size[i % 2] + REFERENCE_SIZE[i % 2] // 2) // REFERENCE_SIZE[i % 2]
                for i, n in enumerate(bounds))
    if not 0 <= box[0] < box[2] <= size[0] or not 0 <= box[1] < box[3] <= size[1]:
        raise ValueError("invalid-crop-bounds")
    return box


def parse_wager(literal):
    """Preserve the displayed denomination; never guess integer chip units."""
    if not isinstance(literal, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?", literal):
        return None
    return {"literal": literal, "decimal": str(Decimal(literal)), "units": "displayed_unknown"}


def _fingerprint(image):
    h = hashlib.sha256()
    h.update(("%dx%d:RGB:" % image.size).encode("ascii"))
    h.update(image.convert("RGB").tobytes())
    return h.hexdigest()


def _normal_mask(mask):
    import numpy as np
    from PIL import Image
    ys, xs = np.nonzero(mask)
    if len(xs) < 2:
        return None
    cut = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = cut.shape
    if h < 1 or w < 1:
        return None
    width = max(1, min(96, round(w * 20 / h)))
    resized = np.asarray(Image.fromarray(cut.astype("uint8") * 255).resize((width, 20), Image.Resampling.BILINEAR))
    canvas = np.zeros((24, 100), dtype="float32")
    canvas[2:22, 2:width + 2] = resized / 255
    padded = np.pad(canvas, 1)
    dilated = np.maximum.reduce([padded[dy:dy + 24, dx:dx + 100]
                                 for dy in range(3) for dx in range(3)])
    return canvas, w / h, dilated, float(canvas.sum())


def _badge_masks(image, polarity=None):
    import numpy as np
    from laya_prep import _components
    rgb = np.asarray(image.convert("RGB"), dtype="int16")
    # White live-label text and dark FOLD text are separate pixel hypotheses.
    # The full word mask must match a template; hue never selects an action.
    white = (rgb.min(axis=2) > 155) & (rgb.max(axis=2) - rgb.min(axis=2) < 55)
    dark = rgb.max(axis=2) < 38
    result = []
    for name, mask in (("white", white), ("dark", dark)):
        if polarity is not None and name != polarity:
            continue
        if name == "dark":
            mask = mask.copy()
            # The shorter FOLD pill ends before the long-action strip. Exclude
            # adjacent avatar shadows, not the letters inside the visible pill.
            mask[:, round(mask.shape[1] * .82):] = False
        components = _components(mask)
        clean = np.zeros(mask.shape, dtype=bool)
        for component in components:
            x0, y0, x1, y1 = (component[key] for key in ("x0", "y0", "x1", "y1"))
            if (x0 > 1 and x1 < mask.shape[1] - 1 and y0 > 1 and y1 < mask.shape[0] - 1
                    and component["area"] >= 2):
                clean[y0:y1, x0:x1] |= mask[y0:y1, x0:x1]
        mask = clean
        ys, xs = np.nonzero(mask)
        if not len(xs):
            continue
        h, w = int(ys.max() - ys.min() + 1), int(xs.max() - xs.min() + 1)
        if h < 5 or not 1.2 <= w / h <= 6.8 or len(xs) / (w * h) > .65:
            continue
        normal = _normal_mask(mask)
        if normal is not None:
            result.append(normal)
    return result


def _score(left, right):
    import numpy as np
    a, aspect_a, dilated_a, total_a = left
    b, aspect_b, dilated_b, total_b = right
    # One normalized pixel of two-way raster tolerance; preserve aspect and
    # require a distinct-word margin so scaling is not a closest-label guess.
    similarity = float((np.minimum(a, dilated_b).sum() / total_a
                        + np.minimum(b, dilated_a).sum() / total_b) * .5)
    return similarity * min(aspect_a, aspect_b) / max(aspect_a, aspect_b)


def _digit_mask(glyph):
    import numpy as np
    rgb = np.asarray(glyph.convert("RGB"), dtype="int16")
    # A decimal point can occupy <0.5% of a padded glyph. Percentile masks used
    # on whole text lines must not erase this explicit tiny glyph afterwards.
    return (rgb.min(axis=2) > 155) & (rgb.max(axis=2) - rgb.min(axis=2) < 55)


@dataclass(frozen=True)
class Template:
    label: str
    mask: object
    source: dict
    crop_sha256: str


class CropTemplates:
    def __init__(self, *, min_score=0.82, margin=0.08):
        if (not all(type(n) in (int, float) and math.isfinite(n) for n in (min_score, margin))
                or not 0 < min_score <= 1 or not 0 < margin < 1):
            raise ValueError("invalid-template-threshold")
        self.min_score, self.margin = min_score, margin
        self.badges, self.digits, self.absent = [], [], []

    def add_badge(self, label, image, source):
        if label not in ACTIONS or not isinstance(source, dict) or not source:
            raise ValueError("explicit-badge-source-required")
        masks = _badge_masks(image, "dark" if label == "fold" else "white")
        if not masks:
            raise ValueError("no-badge-text")
        mask = masks[0]
        self._add(self.badges, Template(label, mask, dict(source), _fingerprint(image)))

    def add_wager(self, literal, image, source):
        from laya_prep import segment_glyphs
        if parse_wager(literal) is None or not isinstance(source, dict) or not source:
            raise ValueError("visible-wager-source-required")
        glyphs, info = segment_glyphs(image, "white")
        if info["overflow"] or len(glyphs) != len(literal):
            return False
        candidates = [_normal_mask(_digit_mask(glyph)) for glyph in glyphs]
        if any(mask is None for mask in candidates):
            return False
        for label, mask in zip(literal, candidates):
            self._add(self.digits, Template(label, mask, dict(source), _fingerprint(image)))
        return True

    @staticmethod
    def _add(templates, template):
        if any(item.label == template.label and item.crop_sha256 == template.crop_sha256
               and _score(item.mask, template.mask) == 1 for item in templates):
            return
        if len(templates) >= MAX_TEMPLATES:
            raise ValueError("template-limit")
        templates.append(template)

    def _match(self, masks, templates):
        scores = {}
        for item in templates:
            score = max((_score(mask, item.mask) for mask in masks), default=0.0)
            if score > scores.get(item.label, (0, None))[0]:
                scores[item.label] = score, item
        ranked = sorted(scores.items(), key=lambda item: item[1][0], reverse=True)
        if not ranked:
            return None
        label, (score, template) = ranked[0]
        runner_up = ranked[1][1][0] if len(ranked) > 1 else 0.0
        if score < self.min_score or score - runner_up < self.margin:
            return None
        return {"value": label, "similarity": score, "margin": score - runner_up,
                "template_source": dict(template.source), "template_crop_sha256": template.crop_sha256}

    def badge(self, image):
        return self._match(_badge_masks(image), self.badges)

    def add_absent(self, image, source):
        import numpy as np
        from PIL import Image
        if not isinstance(source, dict) or not source:
            raise ValueError("visible-absence-source-required")
        if _badge_masks(image):
            return False
        pixels = np.asarray(image.convert("RGB").resize((64, 24), Image.Resampling.BILINEAR), dtype="float32") / 255
        if len(self.absent) >= MAX_TEMPLATES:
            return False
        digest = _fingerprint(image)
        if not any(item[2] == digest for item in self.absent):
            self.absent.append((pixels, dict(source), digest))
        return True

    def badge_absence(self, image):
        import numpy as np
        from PIL import Image
        if _badge_masks(image) or not self.absent:
            return None
        pixels = np.asarray(image.convert("RGB").resize((64, 24), Image.Resampling.BILINEAR), dtype="float32") / 255
        distance, source, digest = min(((float(np.abs(pixels - reference).mean()), source, digest)
                                        for reference, source, digest in self.absent), key=lambda item: item[0])
        if distance > .025:
            return None
        return {"basis": "visible_no_badge_crop", "pixel_distance": distance,
                "template_source": dict(source), "template_crop_sha256": digest,
                "provisional": True, "human_reviewed": False}

    def wager(self, image):
        from laya_prep import segment_glyphs
        glyphs, info = segment_glyphs(image, "white")
        if info["overflow"] or not glyphs:
            return None
        matched = []
        for glyph in glyphs:
            mask = _normal_mask(_digit_mask(glyph))
            item = self._match([mask] if mask is not None else [], self.digits)
            if item is None:
                return None
            matched.append(item)
        value = parse_wager("".join(item["value"] for item in matched))
        if value is None:
            return None
        return {**value, "similarity": min(item["similarity"] for item in matched),
                "glyph_sources": matched}

    @classmethod
    def from_draft_review(cls, path, root):
        """Finite, explicit opt-in to agent annotations. Does not certify labels."""
        from PIL import Image
        path, root = Path(path).resolve(), Path(root).resolve()
        if not path.is_relative_to(root / ".local") or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("bounded-private-review-required")
        data = json.loads(path.read_text(encoding="utf-8"))
        frames = data.get("frames")
        if not isinstance(frames, list) or not 0 < len(frames) <= 120:
            raise ValueError("invalid-review-frames")
        bank = cls()
        seen_frames = set()
        for frame in frames:
            source = frame["source"]
            source_path = (root / source["path"]).resolve()
            if not source_path.is_relative_to(root / ".local") or source_path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("invalid-template-source")
            raw = source_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise ValueError("template-source-hash-mismatch")
            if source["sha256"] in seen_frames:
                continue
            seen_frames.add(source["sha256"])
            with Image.open(source_path) as opened:
                image = opened.convert("RGB")
            if list(image.size) != source["dimensions"]:
                raise ValueError("template-source-size-mismatch")
            if frame["screen"]["value"] != "table":
                continue
            for seat in frame["seats"]:
                number = seat["physical_seat_id"]
                if type(number) is not int or not 1 <= number <= 6:
                    raise ValueError("invalid-template-seat")
                label = BADGE_LITERALS.get(seat["badge"]["value"])
                basis = {"path": source["path"], "frame_sha256": source["sha256"],
                         "frame_index": source["frame_index"], "physical_seat": number,
                         "annotation": "agent_generated", "human_reviewed": False}
                if label and len(bank.badges) < MAX_TEMPLATES:
                    bounds = scaled_bounds(BADGE_BOUNDS[number - 1], image.size)
                    try:
                        bank.add_badge(label, image.crop(bounds), {**basis, "crop_bounds": list(bounds)})
                    except ValueError as error:
                        if str(error) != "no-badge-text":
                            raise
                elif (seat["badge"]["value"] is None and seat["participation"]["value"]
                      in ("card_backs_visible", "no_cards_visible")):
                    bounds = scaled_bounds(BADGE_BOUNDS[number - 1], image.size)
                    bank.add_absent(image.crop(bounds), {**basis, "crop_bounds": list(bounds)})
                wager = seat["visible_wager"]
                if parse_wager(wager["value"]) and len(bank.digits) < MAX_TEMPLATES - 8:
                    bounds = tuple(wager["evidence"]["crop_xyxy"])
                    if not 0 <= bounds[0] < bounds[2] <= image.width or not 0 <= bounds[1] < bounds[3] <= image.height:
                        raise ValueError("invalid-wager-template-bounds")
                    bank.add_wager(wager["value"], image.crop(bounds), {**basis, "crop_bounds": list(bounds)})
        return bank


class ActionReader:
    def __init__(self, templates):
        self.templates = templates

    def read(self, image, capture):
        """Caller supplies original current pixels and source identity, not stacks."""
        _capture_key(capture)
        started = time.perf_counter()
        seats = []
        for number in range(1, 7):
            seat = {"seat": number}
            for field, bounds, recognizer in (("badge", BADGE_BOUNDS, self.templates.badge),
                                               ("visible_wager", WAGER_BOUNDS, self.templates.wager)):
                box = scaled_bounds(bounds[number - 1], image.size)
                crop = image.crop(box)
                match = recognizer(crop)
                absence = self.templates.badge_absence(crop) if field == "badge" and match is None else None
                seat[field] = {"value": match, "status": "provisional" if match else "unknown",
                               "source_capture": dict(capture), "crop_bounds": list(box),
                               "crop_sha256": _fingerprint(crop), "human_reviewed": False,
                               "expires_at_ms": capture["captured_at_ms"] + MAX_FIELD_AGE_MS}
                if absence:
                    seat[field].update(status="clear", absence_evidence=absence)
            seats.append(seat)
        return {"schema_version": 1, "method": "visible_crop_templates", "provisional": True,
                "human_reviewed": False, "capture": dict(capture), "seats": seats,
                "geometry_status": "agent_measured", "reference_dimensions": list(REFERENCE_SIZE),
                "processing_ms": (time.perf_counter() - started) * 1000}


def _capture_key(capture):
    if not isinstance(capture, dict):
        raise ValueError("capture-provenance-required")
    for field in ("session_id", "source_id"):
        if not isinstance(capture.get(field), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", capture[field]):
            raise ValueError("invalid-capture-identity")
    for field in ("epoch", "sequence", "captured_at_ms"):
        if type(capture.get(field)) is not int or not 0 <= capture[field] <= 2**53 - 1:
            raise ValueError("invalid-capture-clock")
    if not capture["epoch"] or not capture["sequence"]:
        raise ValueError("invalid-capture-clock")
    return capture["session_id"], capture["source_id"], capture["epoch"]


class ActionTimeline:
    """Bounded badge-occurrence diagnostics, not a complete betting ledger.

    Wager changes alone never emit an action. Unknown reads do not clear a badge;
    explicit disappearance may be supplied as status=clear by a pixel reader.
    Sampling order never becomes gameplay action order or a hand boundary.
    """

    def __init__(self):
        self.events = deque(maxlen=MAX_EVENTS)
        self._capture = None
        self._scope = None
        self._context = None
        self._badges = {}
        self._occurrence = 0
        self._signature = None

    def observe(self, result, *, hand_id=None, street=None, now_ms=None):
        capture = result["capture"]
        scope = _capture_key(capture)
        now = capture["captured_at_ms"] if now_ms is None else now_ms
        if (type(now) is not int or now < capture["captured_at_ms"]
                or now >= capture["captured_at_ms"] + MAX_FIELD_AGE_MS):
            return {"events": [], "gaps": ["stale_capture"]}
        if street not in (None, "preflop", "flop", "turn", "river", "showdown"):
            raise ValueError("invalid-street")
        if hand_id is not None and (not isinstance(hand_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", hand_id)):
            raise ValueError("invalid-hand-id")
        context = hand_id, street
        seats = result["seats"]
        if (len(seats) != 6 or any(type(item["seat"]) is not int for item in seats)
                or sorted(item["seat"] for item in seats) != list(range(1, 7))):
            raise ValueError("fixed-physical-seats-required")
        for seat in seats:
            reading = seat["badge"]
            if reading.get("source_capture") != capture:
                raise ValueError("badge-source-mismatch")
            if seat["visible_wager"].get("source_capture") != capture:
                raise ValueError("wager-source-mismatch")
            if (reading["status"] == "clear" and
                    reading.get("absence_evidence", {}).get("basis") != "visible_no_badge_crop"):
                raise ValueError("badge-absence-evidence-required")
        raw = json.dumps({"capture": capture, "seats": seats}, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(raw) > 128 * 1024:
            raise ValueError("action-result-too-large")
        signature = hashlib.sha256(raw).hexdigest()
        gaps = []
        if scope == self._scope:
            previous = self._capture
            if capture["sequence"] <= previous["sequence"]:
                return {"events": [], "gaps": [] if capture == previous and signature == self._signature
                        else ["conflicting_or_old_capture"]}
            if capture["captured_at_ms"] <= previous["captured_at_ms"]:
                return {"events": [], "gaps": ["capture_time"]}
            if (capture["sequence"] != previous["sequence"] + 1
                    or capture["captured_at_ms"] - previous["captured_at_ms"] > MAX_CAPTURE_GAP_MS):
                gaps.append("capture_gap")
        else:
            gaps.append("source_boundary" if self._scope else "partial_start")
            self._badges = {}
        if self._context != context and self._capture is not None:
            gaps.append("context_boundary")
        events = []
        for seat in seats:
            number, reading = seat["seat"], seat["badge"]
            if reading["status"] == "clear":
                self._badges.pop(number, None)
                continue
            match = reading["value"]
            if reading["status"] != "provisional" or match is None or match["value"] not in ACTIONS:
                continue
            label = match["value"]
            previous = self._badges.get(number)
            if previous and previous[0] == label:
                if previous[1] != context:
                    gaps.append("retained_badge_across_context")
                continue
            self._occurrence += 1
            self._badges[number] = label, context
            event = {"occurrence": self._occurrence, "seat": number, "action": label,
                     "capture": copy.deepcopy(capture), "badge_evidence": copy.deepcopy(reading),
                     "visible_wager": copy.deepcopy(seat["visible_wager"]), "hand_id": hand_id, "street": street,
                     "provisional": True, "human_reviewed": False, "action_sequence": None,
                     "order_status": "capture_order_only", "complete_prefix": False,
                     "boundary_uncertain": bool(gaps) or hand_id is None or street is None}
            events.append(event)
        if len(events) > 1:
            gaps.append("simultaneous_badges")
            for event in events:
                event["order_status"] = "simultaneous_ambiguous"
        self._scope, self._capture, self._context = scope, dict(capture), context
        self._signature = signature
        self.events.extend(events)
        return {"events": events, "gaps": sorted(set(gaps))}
