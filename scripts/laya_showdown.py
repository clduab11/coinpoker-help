"""Provisional exposed seat-card reads from caller-supplied original pixels.

Search envelopes are physical seats, clockwise from the top, not hero slots.
They were measured on the 890x678 selected-source original (frame 1, SHA
4b2dddd4439028d3abf52ec1dba3c6d5efc0fc2b0035df1e51450e7add35a2ac) and
checked against the 939x714 tooltip/river originals. Those four initial originals
contain backs, NOT a qualified exposed pair. Fanned-card geometry was then
observed on manifest/SHA-bound selected-source originals 91 and 213. Face bounds,
the fanned pair's two sloping roofs, and glyph ROIs below are pixel-derived;
compatibility with a board template remains provisional.

No acquisition, OCR process, input, role inference, hand inference, history,
recommendation, or runtime side effects. A public face pair can precede showdown.
"""

import copy
import hashlib
import io
import json
import math
import re
import time
from pathlib import Path

try:
    from . import laya_board as board
    from .laya_prep import _components, box_px
except ImportError:
    import laya_board as board
    from laya_prep import _components, box_px


REFERENCE_SIZE = (890, 678)
TITLE_HEIGHT = 28
# Broad, agent-measured search areas, NOT hardcoded card or glyph rectangles.
SEAT_SEARCH_BOUNDS = ((359, 45, 530, 195), (686, 85, 853, 250),
                      (698, 350, 862, 520), (361, 475, 531, 637),
                      (30, 350, 196, 520), (47, 85, 215, 250))
MAX_PNG_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = 32768
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_COMPONENTS = 256
MAX_FACES_PER_SEAT = 6
MAX_OCCLUSIONS = 64
CARD = re.compile(r"[2-9TJQKA][cdhs]")


def _pixel_hash(image):
    return hashlib.sha256(("%dx%d:RGB:" % image.size).encode("ascii")
                          + image.convert("RGB").tobytes()).hexdigest()


def _bounds(value, size):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(n) is not int for n in value)
            or not 0 <= value[0] < value[2] <= size[0]
            or not 0 <= value[1] < value[3] <= size[1]):
        raise ValueError("invalid-seat-card-bounds")
    return list(value)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _hull(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None


def _receipt(capture, size=None):
    if not isinstance(capture, dict):
        raise ValueError("seat-card-original-receipt-required")
    for key in ("session_id", "source_id"):
        if not isinstance(capture.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", capture[key]):
            raise ValueError("seat-card-source-identity-required")
    for key in ("epoch", "sequence", "captured_at_ms", "captured_at_unix_ms", "width", "height"):
        minimum = 0 if key == "captured_at_ms" else 1
        if type(capture.get(key)) is not int or not minimum <= capture[key] <= 2**53 - 1:
            raise ValueError("seat-card-original-clock-or-geometry-required")
    if not 100 <= capture["width"] <= 3000 or not 80 <= capture["height"] <= 3000:
        raise ValueError("seat-card-frame-size-unsupported")
    if size is not None and list(size) != [capture["width"], capture["height"]]:
        raise ValueError("seat-card-original-dimensions-mismatch")
    if not re.fullmatch(r"[a-f0-9]{64}", str(capture.get("sha256", ""))):
        raise ValueError("seat-card-original-sha256-required")
    try:
        encoded = json.dumps(capture, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("invalid-seat-card-receipt") from error
    if len(encoded.encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise ValueError("seat-card-receipt-too-large")
    for key in ("service_instance_id", "capture_session_id", "recording_session_id"):
        value = capture.get(key)
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)):
            raise ValueError("seat-card-invalid-source-crosswalk")
    native = capture.get("native_source_id")
    if native is not None and (type(native) not in (str, int) or not re.fullmatch(r"[0-9]{1,20}", str(native))
                               or not 1 <= int(native) <= 2**64 - 1):
        raise ValueError("seat-card-invalid-native-source")
    return capture


def _scaled_search(box, size):
    return _bounds([round(box[0] * size[0] / REFERENCE_SIZE[0]),
                    round(TITLE_HEIGHT + (box[1] - TITLE_HEIGHT) *
                          (size[1] - TITLE_HEIGHT) / (REFERENCE_SIZE[1] - TITLE_HEIGHT)),
                    round(box[2] * size[0] / REFERENCE_SIZE[0]),
                    round(TITLE_HEIGHT + (box[3] - TITLE_HEIGHT) *
                          (size[1] - TITLE_HEIGHT) / (REFERENCE_SIZE[1] - TITLE_HEIGHT))], size)


def _white(rgb):
    return (rgb.min(axis=2) >= 210) & (rgb.max(axis=2) - rgb.min(axis=2) <= 35)


def _roof(mask, start, end):
    """A fitted visible top edge, never an extrapolated hidden card edge."""
    import numpy as np
    xs = np.arange(start, end)
    if len(xs) < 8 or not mask[:, start:end].any(axis=0).all():
        return None
    ys = mask[:, start:end].argmax(axis=0)
    slope, intercept = np.polyfit(xs, ys, 1)
    if float(np.sqrt(np.mean((ys - slope * xs - intercept) ** 2))) > .85:
        return None
    return float(slope), float(intercept)


def _fan_seam(rgb, split, roof_slope):
    """Fit the front face's dark-to-white diagonal separator from pixels."""
    import numpy as np
    height, width = rgb.shape[:2]
    brightness = rgb.min(axis=2)
    white = _white(rgb)
    points = []
    for y in range(round(height * .18), round(height * .78)):
        centre = round(split - roof_slope * y)
        lo, hi = max(1, centre - 4), min(width - 3, centre + 3)
        options = [(int(brightness[y, x + 1] - brightness[y, x]), x)
                   for x in range(lo, hi + 1) if white[y, x + 2]]
        if options:
            contrast, x = max(options, key=lambda value: (value[0], -abs(value[1] - centre)))
            if contrast >= 25:
                points.append((y, x))
    if len(points) < max(8, round(height * .25)):
        return None
    ys, xs = np.asarray(points).T
    slope, intercept = np.polyfit(ys, xs, 1)
    if (abs(slope + roof_slope) > .045 or abs(intercept - split) > 4
            or float(np.sqrt(np.mean((xs - slope * ys - intercept) ** 2))) > 1.0):
        return None
    return float(slope), float(intercept)


def _faces(rgb, search, frame_size, *, with_geometry=False):
    """Tight white-face bounds, including a positively two-roof fanned pair.

    In a fan only visible portions are partitioned. Hidden overlapping edges
    are NOT reconstructed. A flat merged rectangle cannot be blindly halved.
    """
    import numpy as np
    x0, y0, x1, y1 = search
    white = _white(rgb[y0:y1, x0:x1])
    components = _components(white)
    if len(components) > MAX_COMPONENTS:
        return [], "white-component-limit"
    found = []
    scale_x = frame_size[0] / REFERENCE_SIZE[0]
    scale_y = (frame_size[1] - TITLE_HEIGHT) / (REFERENCE_SIZE[1] - TITLE_HEIGHT)
    for component in components:
        xa, ya, xb, yb = (component[k] for k in ("x0", "y0", "x1", "y1"))
        width, height = xb - xa, yb - ya
        if (28 * scale_x <= width <= 164 * scale_x and 24 * scale_y <= height <= 124 * scale_y
                and 1.18 <= width / height <= 1.60 and component["area"] / (width * height) >= .65
                and xa > 0 and ya > 0 and xb < white.shape[1] and yb < white.shape[0]):
            face = white[ya:yb, xa:xb]
            left = _roof(face, round(width * .10), round(width * .42))
            right = _roof(face, round(width * .58), round(width * .90))
            if left and right and -.16 <= left[0] <= -.025 and .025 <= right[0] <= .16:
                split = round((right[1] - left[1]) / (left[0] - right[0]))
                if .38 * width <= split <= .62 * width:
                    seam = _fan_seam(rgb[y0 + ya:y0 + yb, x0 + xa:x0 + xb], split, right[0])
                    yy, xx = np.indices(face.shape)
                    boundary = seam[0] * yy + seam[1] if seam else np.full(face.shape, split - 1)
                    fan_bounds = [x0 + xa, y0 + ya, x0 + xb, y0 + yb]
                    boxes = []
                    for side, visible in (("left", xx <= boundary), ("right", xx > boundary)):
                        ys, xs = np.nonzero(face & visible)
                        lo, top, hi, bottom = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
                        if not .55 <= (hi - lo) / (bottom - top) <= .85:
                            break
                        boxes.append({"bounds": [x0 + xa + lo, y0 + ya + top, x0 + xa + hi, y0 + ya + bottom],
                                      "visible_mask": visible[top:bottom, lo:hi],
                                      "fan_bounds": fan_bounds if seam else None,
                                      "geometry": {"kind": "pixel_roof_and_separator" if seam else "pixel_roofs_only",
                                                   "side": side, "separator": list(seam) if seam else None,
                                                   "separator_origin": [x0 + xa, y0 + ya]}})
                    if len(boxes) == 2:
                        found.extend(boxes)
                        continue
        if not 14 * scale_x <= width <= 82 * scale_x or not 24 * scale_y <= height <= 124 * scale_y:
            continue
        if not .59 <= width / height <= .80 or component["area"] / (width * height) < .62:
            continue
        # Border supports require the visible shape, not a white UI label or an
        # inferred hidden half-card. A search-edge truncation has no outer proof.
        if xa == 0 or ya == 0 or xb == white.shape[1] or yb == white.shape[0]:
            continue
        face = white[ya:yb, xa:xb]
        middle_x = slice(max(1, round(width * .18)), min(width - 1, round(width * .82)))
        middle_y = slice(max(1, round(height * .18)), min(height - 1, round(height * .82)))
        supports = [float(np.mean(face[:2, middle_x])), float(np.mean(face[-2:, middle_x])),
                    float(np.mean(face[middle_y, :2])), float(np.mean(face[middle_y, -2:]))]
        if min(supports) < .78:
            continue
        found.append({"bounds": [x0 + xa, y0 + ya, x0 + xb, y0 + yb],
                      "visible_mask": None, "fan_bounds": None, "geometry": {"kind": "white_portrait"}})
    found.sort(key=lambda b: (b["bounds"][0], b["bounds"][1]))
    if len(found) > MAX_FACES_PER_SEAT:
        return [], "face-candidate-limit"
    return (found if with_geometry else [c["bounds"] for c in found]), "white-face-candidates" if found else "no-supported-white-face"


def face_features(image, visible_mask=None):
    """Extract corner ink relative to a detected tight white portrait face.

    Only features compatible with the dependency's existing bitmap, color,
    size, aspect, shape-distance and distinct-label rules can later be read.
    This function never sends a seat search envelope through board slot ROIs.
    """
    import numpy as np
    from PIL import Image
    unknown = {"state": "unknown", "reason": "unsupported-face", "features": {}, "glyph_bounds": {}}
    if (not isinstance(image, Image.Image) or min(image.size) < 8
            or "A" in image.getbands() and np.asarray(image.getchannel("A")).min() != 255):
        return {**unknown, "reason": "invalid-face-pixels"}
    rgb = np.asarray(image.convert("RGB"), dtype="int16")
    height, width = rgb.shape[:2]
    if not .55 <= width / height <= .85 or float(_white(rgb).mean()) < .62:
        return unknown
    white = _white(rgb)
    if visible_mask is not None:
        if (not isinstance(visible_mask, np.ndarray) or visible_mask.dtype != bool
                or visible_mask.shape != white.shape):
            return {**unknown, "reason": "invalid-visible-face-mask"}
        white &= visible_mask
    roof = _roof(white, round(width * .15), round(width * .80))
    angle = math.degrees(math.atan(roof[0])) if roof and .025 <= abs(roof[0]) <= .16 else 0.0
    # A fanned face's axis-aligned bounds contain exterior shadow triangles.
    # Ink must be surrounded by the observed white silhouette in BOTH axes.
    yy, xx = np.indices(white.shape)
    interior = (white.any(axis=1)[:, None] & white.any(axis=0)[None, :]
                & (xx > white.argmax(axis=1)[:, None])
                & (xx < width - 1 - white[:, ::-1].argmax(axis=1)[:, None])
                & (yy > white.argmax(axis=0)[None, :])
                & (yy < height - 1 - white[::-1].argmax(axis=0)[None, :]))
    green = (rgb[..., 1] > rgb[..., 0] + 20) & (rgb[..., 1] > rgb[..., 2])
    ink = (rgb.min(axis=2) < 150) & ~green & interior
    cw, ch = math.ceil(width * .48), math.ceil(height * .68)
    corner = ink[:ch, :cw]
    components = [c for c in _components(corner) if c["area"] >= 6
                  and c["x0"] > 0 and c["y0"] > 0 and c["x1"] < cw and c["y1"] < ch]
    rank_candidates = [c for c in components if c["y0"] <= height * .20 and c["y1"] <= height * .46
                       and c["y1"] - c["y0"] >= max(5, height * .12) and c["x0"] <= width * .33]
    if not rank_candidates:
        return {**unknown, "reason": "missing-rank-ink"}
    first = min(rank_candidates, key=lambda c: (c["y0"], c["x0"]))
    rank_components = [c for c in rank_candidates if
                       min(first["y1"], c["y1"]) - max(first["y0"], c["y0"]) >=
                       .5 * min(first["y1"] - first["y0"], c["y1"] - c["y0"])]
    if len(rank_components) > 2:
        return {**unknown, "reason": "unsupported-rank-components"}
    rank_end = max(c["y1"] for c in rank_components)
    suit_components = [c for c in components if c["y0"] >= rank_end + max(2, round(height * .02))
                       and c["y1"] - c["y0"] >= 5 and c["x0"] <= width * .26
                       and (c["x0"] + c["x1"]) / 2 <= width * .30]
    if suit_components:
        first = min(suit_components, key=lambda c: (c["y0"], c["x0"]))
        suit_components = [c for c in suit_components if
                           min(first["y1"], c["y1"]) - max(first["y0"], c["y0"]) >=
                           .5 * min(first["y1"] - first["y0"], c["y1"] - c["y0"])]
    if len(suit_components) != 1:
        return {**unknown, "reason": "missing-or-unsupported-suit-components",
                "component_diagnostics": {"rank": rank_components, "corner": components}}
    features, boxes = {}, {}
    for kind, selected in (("rank", rank_components), ("suit", suit_components)):
        xa, ya, xb, yb = _hull([[c["x0"], c["y0"], c["x1"], c["y1"]] for c in selected])
        mask = ink[ya:yb, xa:xb]
        if yb - ya < 5 or xb - xa < 3 or mask.mean() > .85:
            return {**unknown, "reason": "unsupported-" + kind + "-ink"}
        red_fraction = float((rgb[..., 0] - rgb[..., 1] > 70)[ya:yb, xa:xb][mask].mean())
        if .05 < red_fraction < .95:
            return {**unknown, "reason": "mixed-" + kind + "-ink-colour"}
        # Same binary-ink normalization as the existing board glyph bank. The
        # dependency, not this reader, enforces size/aspect/distinct-label guards.
        raster = Image.fromarray(mask.astype("uint8") * 255)
        if angle:
            # Only the observed glyph mask is deskewed. Original face/glyph
            # bounds, pixel hashes and receipts remain in source coordinates.
            raster = raster.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=0)
            ys, xs = np.nonzero(np.asarray(raster) >= 128)
            if not len(xs):
                return {**unknown, "reason": "unsupported-deskewed-ink"}
            # Preserve interpolated coverage until the bank's own bitmap/shape
            # conversion; an extra hard threshold would discard edge pixels.
            raster = raster.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
        bitmap = np.asarray(raster.resize(board.BITMAP_SIZE, Image.Resampling.BILINEAR), dtype="float32") / 255
        features[kind] = {"bitmap": bitmap, "w": raster.width, "h": raster.height, "red": red_fraction >= .95}
        boxes[kind] = [xa, ya, xb, yb]
    if features["rank"]["red"] != features["suit"]["red"]:
        return {**unknown, "reason": "rank-suit-colour-disagreement"}
    if abs(boxes["rank"][0] - boxes["suit"][0]) > width * .20:
        return {**unknown, "reason": "unsupported-corner-alignment"}
    return {"state": "card_candidate", "reason": "bounds-relative-corner-ink",
            "features": features, "glyph_bounds": boxes, "deskew_degrees": round(angle, 5)}


def _pair_geometry(boxes):
    if len(boxes) != 2:
        return False
    a, b = boxes
    aw, ah, bw, bh = a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]
    return (a[2] <= b[0] and b[0] - a[2] <= max(aw, bw) * .65
            and abs(a[1] - b[1]) <= min(ah, bh) * .18
            and min(aw, bw) / max(aw, bw) >= .84 and min(ah, bh) / max(ah, bh) >= .87)


def _current_evidence(image, capture, value, masks):
    """Check an external client-text reader's exact capture and pixel receipt."""
    if not isinstance(value, dict) or value.get("status") not in ("confirmed", "provisional"):
        return None
    if value.get("capture") != capture:
        return None
    try:
        bounds = _bounds(value.get("bounds"), image.size)
    except ValueError:
        return None
    if any(_overlap(bounds, mask) for mask in masks) or value.get("crop_sha256") != _pixel_hash(image.crop(bounds)):
        return None
    return copy.deepcopy(value)


class RevealedCardReader:
    def __init__(self, board_recognizer, regions):
        if not callable(getattr(board_recognizer, "match", None)) or not callable(getattr(board_recognizer, "recognize_frame", None)):
            raise ValueError("board-glyph-recognizer-required")
        if not isinstance(regions, dict):
            raise ValueError("seat-card-regions-required")
        self.board_recognizer = board_recognizer
        self.regions = copy.deepcopy(regions.get("regions", regions))

    def read(self, image, capture, occluded_regions=None, roster=None, table_context_id=None):
        """Read only this receipt; never renew or carry cards from earlier reads.

        ``roster`` accepts current ContextTimeline seats or its full result.
        Association requires a confirmed occupant on this exact receipt/table.
        Optional evidence.showdown from an independent client-text reader must
        include origin, literal, bounds, crop_sha256, status, and exact capture.
        No text recognizer is silently started here. Mere pairs/board length do
        NOT establish showdown. Known self-private cards are excluded unless a
        source-bound evidence.revealed_cards explicitly names that physical seat.
        """
        import numpy as np
        from PIL import Image
        started = time.perf_counter()
        if not isinstance(image, Image.Image):
            raise ValueError("seat-card-original-image-required")
        _receipt(capture, image.size)
        if table_context_id is not None and (not isinstance(table_context_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", table_context_id)):
            raise ValueError("invalid-seat-card-table-context")
        masks = occluded_regions if occluded_regions is not None else []
        if not isinstance(masks, (list, tuple)) or len(masks) > MAX_OCCLUSIONS:
            raise ValueError("invalid-seat-card-occlusions")
        masks = [_bounds(mask, image.size) for mask in masks]
        native_masks = capture.get("occluded_regions", [])
        if not isinstance(native_masks, list) or len(native_masks) > MAX_OCCLUSIONS:
            raise ValueError("invalid-seat-card-receipt-occlusions")
        masks += [_bounds(mask, image.size) for mask in native_masks if mask not in masks]
        if len(masks) > MAX_OCCLUSIONS:
            raise ValueError("invalid-seat-card-occlusions")
        board_boxes = []
        for number in range(1, 6):
            roi = self.regions.get("board_slot_%d" % number)
            if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                    or any(type(n) not in (int, float) or not math.isfinite(n) for n in roi)
                    or not 0 <= roi[0] < roi[2] <= 1 or not 0 <= roi[1] < roi[3] <= 1):
                raise ValueError("invalid-seat-card-board-region")
            board_boxes.append(_bounds(list(box_px(roi, *image.size)), image.size))
        search_boxes = []
        for number, reference in enumerate(SEAT_SEARCH_BOUNDS, 1):
            roi = self.regions.get("seat_%d_revealed_cards_search" % number)
            if roi is None:
                box = _scaled_search(reference, image.size)
            else:
                if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                        or any(type(n) not in (int, float) or not math.isfinite(n) for n in roi)
                        or not 0 <= roi[0] < roi[2] <= 1 or not 0 <= roi[1] < roi[3] <= 1):
                    raise ValueError("invalid-seat-card-search-region")
                box = _bounds(list(box_px(roi, *image.size)), image.size)
            search_boxes.append(box)
        context = roster if isinstance(roster, dict) else {}
        rows = context.get("seats", []) if isinstance(roster, dict) else roster or []
        if not isinstance(rows, list) or len(rows) > 6:
            raise ValueError("invalid-seat-card-roster")
        identities = [s.get("identity") for s in rows if isinstance(s, dict) and isinstance(s.get("identity"), str)]
        bindings = {}
        for row in rows:
            if not isinstance(row, dict) or type(row.get("seat")) is not int or not 1 <= row["seat"] <= 6:
                raise ValueError("invalid-seat-card-roster-seat")
            if row["seat"] in bindings:
                raise ValueError("duplicate-seat-card-roster-seat")
            bindings[row["seat"]] = row
        evidence = context.get("evidence", {})
        evidence = evidence if isinstance(evidence, dict) else {}
        phase_evidence = _current_evidence(image, capture, evidence.get("showdown"), masks)
        phase = "unknown"
        if phase_evidence:
            origin, literal = phase_evidence.get("origin"), phase_evidence.get("literal")
            if ((origin == "client_showdown" and literal == "SHOWDOWN")
                    or (origin == "client_winner" and literal == "WINNER")):
                phase = "showdown"
            else:
                phase_evidence = None
        public_reveal = _current_evidence(image, capture, evidence.get("revealed_cards"), masks)
        public_seats = public_reveal.get("seats", []) if public_reveal else []
        if (not isinstance(public_seats, list) or any(type(n) is not int or not 1 <= n <= 6 for n in public_seats)
                or public_reveal and (public_reveal.get("origin") != "client_revealed_cards"
                                     or public_reveal.get("literal") not in ("SHOWS", "REVEALED CARDS"))):
            public_seats = []
        role = evidence.get("role", {})
        hero = None
        if (isinstance(role, dict) and context.get("role") in ("your_turn", "seated_waiting")
                and role.get("status") in ("confirmed", "provisional")
                and role.get("origin") in ("own_action_controls", "self_player")
                and role.get("capture") == capture and type(context.get("hero_seat")) is int
                and role.get("hero_seat") == context["hero_seat"] and 1 <= context["hero_seat"] <= 6):
            hero = context["hero_seat"]
        rgb = np.asarray(image.convert("RGB"), dtype="int16")
        incomplete = "A" in image.getbands() and not bool(np.all(np.asarray(image.getchannel("A")) == 255))
        aspect = image.width / (image.height - TITLE_HEIGHT)
        geometry_supported = abs(aspect / (REFERENCE_SIZE[0] / (REFERENCE_SIZE[1] - TITLE_HEIGHT)) - 1) <= .045
        result = {"schema_version": 1, "source": "visible_seat_cards", "capture": copy.deepcopy(capture),
                  "table_context_id": table_context_id, "phase": phase, "phase_evidence": phase_evidence,
                  "phase_reason": "explicit_current_client_text" if phase_evidence else "no_explicit_current_showdown_evidence",
                  "seats": [], "quality_approved": False, "human_verified": False, "diagnostic_only": True,
                  "recognizer_version": "visible_seat_cards_v1", "frame_pixel_sha256": _pixel_hash(image),
                  "original_png_verification": "caller_required", "conflicts": [],
                  "geometry_status": "agent_measured_search;pixel_derived_face_bounds"}
        for number, search in enumerate(search_boxes, 1):
            seat = {"seat": number, "cards": [], "status": "unknown", "bounds": None,
                    "search_bounds": search, "capture": copy.deepcopy(capture), "identity": None,
                    "occupant_epoch": None, "association_status": "unknown", "readings": [],
                    "visible_face_count": 0, "face_bounds": [], "bounds_kind": "pixel_visible_face_hull",
                    "reason": "no-supported-white-face", "observation": "unknown"}
            result["seats"].append(seat)
            row = bindings.get(number, {})
            identity = row.get("identity")
            if (table_context_id is not None and row.get("table_context_id", context.get("table_context_id")) == table_context_id
                    and context.get("table_context_id", table_context_id) == table_context_id
                    and row.get("capture", context.get("capture")) == capture
                    and row.get("status") == "confirmed" and row.get("continuity") == "confirmed"
                    and row.get("occupancy") == "occupied" and isinstance(identity, str)
                    and 1 <= len(identity) <= 64 and not any(ord(c) < 32 for c in identity)
                    and identities.count(identity) == 1 and type(row.get("occupant_epoch")) is int
                    and 1 <= row["occupant_epoch"] <= 2**53 - 1):
                seat.update(identity=identity, occupant_epoch=row["occupant_epoch"], association_status="confirmed")
            if incomplete or not geometry_supported:
                seat["reason"] = "incomplete-frame-pixels" if incomplete else "unsupported-six-seat-geometry"
                continue
            faces, reason = _faces(rgb, search, image.size, with_geometry=True)
            # Board rectangles and cross-seat search ambiguity cannot become an
            # opponent's cards, even when they match the very same glyph bank.
            candidates = []
            for candidate in faces:
                face = candidate["bounds"]
                if any(_overlap(face, box) for box in board_boxes):
                    reason = "board-region-excluded"
                    continue
                owners = [n for n, box in enumerate(search_boxes, 1)
                          if box[0] <= face[0] < face[2] <= box[2] and box[1] <= face[1] < face[3] <= box[3]]
                if owners != [number]:
                    reason = "ambiguous-physical-seat"
                    continue
                candidates.append(candidate)
            seat.update(bounds=_hull([c["bounds"] for c in candidates]), reason=reason,
                        visible_face_count=len(candidates), face_bounds=[c["bounds"] for c in candidates])
            if any(_overlap(seat["bounds"] or search, mask) for mask in masks):
                seat.update(status="occluded", reason="occluded-seat-card-pixels")
                continue
            if hero == number and number not in public_seats:
                seat["reason"] = "known-self-private-cards-excluded"
                continue
            if len(candidates) > 2:
                seat["reason"] = "ambiguous-face-pair"
                continue
            for candidate in candidates:
                face = candidate["bounds"]
                crop = image.crop(face)
                feature = face_features(crop, candidate["visible_mask"])
                reading = {"card": None, "bounds": face, "crop_sha256": _pixel_hash(crop),
                           "capture": copy.deepcopy(capture), "reason": feature["reason"], "glyph_bounds": {},
                           "geometry": candidate["geometry"], "status": "unknown"}
                seat["readings"].append(reading)
                if feature["state"] != "card_candidate":
                    continue
                rank = self.board_recognizer.match("rank", feature["features"]["rank"])
                suit = self.board_recognizer.match("suit", feature["features"]["suit"])
                reading.update(rank_match=rank, suit_match=suit,
                               deskew_degrees=feature["deskew_degrees"],
                               glyph_bounds={kind: [face[0] + box[0], face[1] + box[1],
                                                   face[0] + box[2], face[1] + box[3]]
                                             for kind, box in feature["glyph_bounds"].items()})
                card = str(rank.get("label") or "") + str(suit.get("label") or "")
                if not CARD.fullmatch(card):
                    reading["reason"] = "unsupported-glyph-template:" + (rank.get("reason") or suit.get("reason") or "unknown")
                    continue
                reading.update(card=card, status="provisional", reason="provisional-bounds-relative-template-match")
                seat["cards"].append(card)
            if seat["cards"]:
                seat["observation"] = "revealed_cards"
            fan = (len(candidates) == 2 and candidates[0]["fan_bounds"] is not None
                   and candidates[0]["fan_bounds"] == candidates[1]["fan_bounds"])
            portraits = all(c["geometry"]["kind"] == "white_portrait" for c in candidates)
            if len(seat["cards"]) == 2 and (fan or portraits and _pair_geometry([c["bounds"] for c in candidates])):
                seat.update(status="provisional", reason="visible-face-pair;phase-not-inferred")
            elif candidates:
                seat["reason"] = "incomplete-or-unsupported-face-pair" if len(candidates) != 2 else "unreadable-or-unsupported-face-pair"
                if len(seat["cards"]) == 2:
                    seat.update(cards=[], observation="unknown", reason="unsupported-face-pair-geometry")
                    for reading in seat["readings"]:
                        reading.update(rejected_card=reading["card"], card=None, status="unknown",
                                       reason="unsupported-face-pair-geometry")
        locations = {}
        for seat in result["seats"]:
            for card in seat["cards"]:
                locations.setdefault(card, []).append("seat:%d" % seat["seat"])
        board_read = self.board_recognizer.recognize_frame(image, self.regions)
        for number, slot in enumerate(board_read.get("slots", []), 1):
            card = slot.get("card")
            if (isinstance(card, str) and CARD.fullmatch(card) and number <= len(board_boxes)
                    and not any(_overlap(board_boxes[number - 1], mask) for mask in masks)):
                locations.setdefault(card, []).append("board:%d" % number)
        conflicts = {card: places for card, places in locations.items() if len(places) > 1}
        result["conflicts"] = [{"card": card, "locations": places} for card, places in sorted(conflicts.items())]
        for seat in result["seats"]:
            if any(card in conflicts for card in seat["cards"]):
                seat.update(cards=[], status="unknown", observation="unknown", reason="scene-duplicate-card-conflict")
                for reading in seat["readings"]:
                    if reading["card"] in conflicts:
                        reading.update(rejected_card=reading["card"], card=None, status="unknown", reason="scene-duplicate-card-conflict")
        result["processing_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def read_original(self, png_path, manifest_path, capture, **kwargs):
        """Finite evidence intake: pin original bytes and match the native receipt.

        Use an already-recorded original when the user naturally reveals cards.
        This does not take a screenshot or control the client. No preview, newly
        encoded PNG, or synthetic replay clock can stand in for the native row.
        """
        from PIL import Image
        _receipt(capture)
        png_path, manifest_path = Path(png_path).resolve(), Path(manifest_path).resolve()
        if png_path.name != "frame-%010d.png" % capture["sequence"] or png_path.parent != manifest_path.parent:
            raise ValueError("seat-card-original-filename-mismatch")
        with png_path.open("rb") as handle:
            raw = handle.read(MAX_PNG_BYTES + 1)
        if not raw or len(raw) > MAX_PNG_BYTES or hashlib.sha256(raw).hexdigest() != capture["sha256"]:
            raise ValueError("seat-card-original-sha256-mismatch")
        with manifest_path.open("rb") as handle:
            manifest = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(manifest) > MAX_MANIFEST_BYTES:
            raise ValueError("seat-card-manifest-too-large")
        record = None
        for line in manifest.split(b"\n")[:-1]:
            if not line.strip():
                continue
            try:
                row = board._json(line)
            except (ValueError, UnicodeDecodeError) as error:
                raise ValueError("seat-card-invalid-manifest-row") from error
            if not isinstance(row, dict) or row.get("event") != "frame" or row.get("frame_index") != capture["sequence"]:
                continue
            if record is not None:
                raise ValueError("seat-card-duplicate-manifest-frame")
            record = row
        pairs = {"frame_index": "sequence", "source_utc_unix_ms": "captured_at_unix_ms",
                 "captured_at_monotonic_ms": "captured_at_ms", "width": "width", "height": "height", "sha256": "sha256"}
        if (record is None or any(record.get(key) != capture[field] for key, field in pairs.items())
                or any(type(record.get(key)) is not int for key in pairs if key != "sha256")):
            raise ValueError("seat-card-original-manifest-mismatch")
        if str(record.get("source_id")) != str(capture.get("native_source_id")) or record.get("png_bytes") != len(raw):
            raise ValueError("seat-card-original-native-source-mismatch")
        if capture.get("recording_session_id") is not None and capture["recording_session_id"] != png_path.parent.name:
            raise ValueError("seat-card-original-recording-session-mismatch")
        if record.get("occluded_regions", []) != capture.get("occluded_regions", []):
            raise ValueError("seat-card-original-occlusion-mismatch")
        with Image.open(io.BytesIO(raw)) as original:
            if original.format != "PNG" or list(original.size) != [capture["width"], capture["height"]]:
                raise ValueError("seat-card-original-image-mismatch")
            original.load()
            image = original.copy()
        result = self.read(image, capture, **kwargs)
        result.update(original_png_verification="sha256-and-native-manifest",
                      original_evidence={"file": str(png_path), "manifest": str(manifest_path),
                                         "record": copy.deepcopy(record), "png_bytes": len(raw)})
        return result
