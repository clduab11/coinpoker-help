"""Independent CPU roster/role/profile observations from original table pixels.

Confirmation here is receipt/identity continuity, not an accuracy qualification.
No capture, model loading, mouse, gameplay, or local opponent-stat calculation.
"""

import base64
from collections import OrderedDict, deque
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import unicodedata


MAX_AGE_MS = 5000
MAX_NAME = 64
MAX_WORDS = 4096
MAX_CACHE = 64
MAX_EVENTS = 256
METRICS = {"vpip": "VPIP", "pfr": "PFR", "three_bet": "3-BET", "c_bet": "C-BET"}
REFERENCE_SIZE = (939, 714)
TITLE_HEIGHT = 28
GEOMETRY_SOURCE = {
    "path": ".local/captures/utc-1791942831-290126500-practice/frame-0000000177.png",
    "sha256": "a9c1ccff1d4d9d9f1b154e2c0ddc36331effdcf4149c6a0072597ece28e780bc",
    "dimensions": list(REFERENCE_SIZE), "human_reviewed": False,
    "regions": "crates/ingest/assets/laya/regions.json",
}
# Fixed physical slots measured on the genuine original above, never hero slots.
SEAT_BOUNDS = ((401, 51, 540, 194), (735, 107, 890, 252), (756, 391, 899, 545),
               (399, 522, 540, 665), (40, 391, 186, 536), (58, 107, 204, 253))
NAME_BOUNDS = ((405, 141, 535, 167), (741, 198, 876, 224), (762, 480, 894, 507),
               (404, 608, 535, 636), (45, 480, 179, 507), (64, 198, 198, 224))
CAPTION_BOUNDS = (27, 0, 410, 27)
CONTROLS_BOUNDS = (597, 648, 937, 713)
VACANT_TEXT = {"empty seat", "sit here", "take seat", "seat open", "available seat"}
RESERVED_TEXT = VACANT_TEXT | {"unknown", "fold", "check", "call", "bet", "raise", "all-in",
                               "all in", "sitting out", "sit out", "waiting", "vpip", "pfr"}


def scaled_bounds(bounds, size):
    width, height = size
    if any(type(n) is not int or n <= 0 for n in size) or height <= TITLE_HEIGHT:
        raise ValueError("invalid-context-geometry")
    box = [round(bounds[0] * width / REFERENCE_SIZE[0]),
           round(bounds[1] if bounds[1] < TITLE_HEIGHT else
                 TITLE_HEIGHT + (bounds[1] - TITLE_HEIGHT) * (height - TITLE_HEIGHT) / (REFERENCE_SIZE[1] - TITLE_HEIGHT)),
           round(bounds[2] * width / REFERENCE_SIZE[0]),
           round(bounds[3] if bounds[3] < TITLE_HEIGHT else
                 TITLE_HEIGHT + (bounds[3] - TITLE_HEIGHT) * (height - TITLE_HEIGHT) / (REFERENCE_SIZE[1] - TITLE_HEIGHT))]
    return _bounds(box, size)


def _bounds(box, size):
    if (not isinstance(box, (list, tuple)) or len(box) != 4 or
            any(type(n) not in (float, int) or not math.isfinite(n) for n in box)):
        raise ValueError("invalid-context-bounds")
    box = [math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])]
    if not 0 <= box[0] < box[2] <= size[0] or not 0 <= box[1] < box[3] <= size[1]:
        raise ValueError("invalid-context-bounds")
    return box


def _overlap(left, right):
    return left[0] < right[2] and left[2] > right[0] and left[1] < right[3] and left[3] > right[1]


def _inside(box, region):
    return (region[0] <= (box[0] + box[2]) / 2 < region[2] and
            region[1] <= (box[1] + box[3]) / 2 < region[3])


def _hull(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _pixel_hash(image):
    return hashlib.sha256(("%dx%d:RGB:" % image.size).encode() + image.convert("RGB").tobytes()).hexdigest()


def _receipt(capture):
    if not isinstance(capture, dict):
        raise ValueError("context-original-receipt-required")
    for field in ("session_id", "source_id"):
        if not isinstance(capture.get(field), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", capture[field]):
            raise ValueError("context-source-identity-required")
    for field in ("epoch", "sequence", "captured_at_ms", "captured_at_unix_ms", "width", "height"):
        minimum = 0 if field == "captured_at_ms" else 1
        if type(capture.get(field)) is not int or not minimum <= capture[field] <= 2**53 - 1:
            raise ValueError("context-original-clock-or-geometry-required")
    if any(capture[k] > 4096 for k in ("width", "height")):
        raise ValueError("context-frame-too-large")
    if not re.fullmatch(r"[a-f0-9]{64}", str(capture.get("sha256", ""))):
        raise ValueError("context-original-sha256-required")
    if len(json.dumps(capture, allow_nan=False)) > 32768:
        raise ValueError("context-receipt-too-large")
    for field in ("service_instance_id", "capture_session_id"):
        if capture.get(field) is not None and not isinstance(capture[field], str):
            raise ValueError("context-invalid-source-crosswalk")
    if capture.get("native_source_id") is not None and type(capture["native_source_id"]) not in (str, int):
        raise ValueError("context-invalid-native-source")
    return tuple(capture.get(k) for k in ("service_instance_id", "session_id", "capture_session_id",
                                         "source_id", "native_source_id", "epoch"))


def _name(literal):
    if not isinstance(literal, str):
        return None
    value = unicodedata.normalize("NFC", literal.strip())
    if (not 1 <= len(value) <= MAX_NAME or "..." in value or "\u2026" in value or
            value.casefold() in RESERVED_TEXT or not any(c.isalpha() for c in value) or
            not re.fullmatch(r"[\w][\w .'-]*", value, re.UNICODE)):
        return None
    return value


def parse_percent(label, literal):
    """Parse the client's literal percentage, independently of chip amounts."""
    result = {"label": label, "literal": literal, "percent": None, "status": "missing", "reason": "missing_value"}
    if literal is None:
        return result
    if not isinstance(literal, str) or len(literal) > 32:
        return {**result, "literal": None, "status": "unreadable", "reason": "unreadable_value"}
    value = literal.strip()
    if value in ("-", "--", "\u2013", "\u2014"):
        return {**result, "status": "dash", "reason": "literal_dash"}
    if "," in value:
        return {**result, "status": "invalid", "reason": "ambiguous_numeric_locale"}
    if not re.fullmatch(r"-?\d{1,3}(?:\.\d{1,6})?\s*%", value):
        return {**result, "status": "unreadable", "reason": "not_a_literal_percentage"}
    try:
        percent = Decimal(value[:-1].strip())
    except InvalidOperation:
        return {**result, "status": "invalid", "reason": "invalid_percentage"}
    if not 0 <= percent <= 100:
        return {**result, "status": "invalid", "reason": "percentage_out_of_range"}
    return {**result, "percent": float(percent), "status": "accepted", "reason": "literal_percentage"}


def _words(values, size):
    if not isinstance(values, list) or len(values) > MAX_WORDS:
        raise ValueError("invalid-ocr-words")
    result = []
    for index, word in enumerate(values):
        if (not isinstance(word, dict) or not isinstance(word.get("text"), str) or
                not 0 < len(word["text"]) <= 128 or any(unicodedata.category(c).startswith("C") for c in word["text"])):
            raise ValueError("invalid-ocr-word")
        result.append({"text": word["text"], "bbox": _bounds(word.get("bbox"), size),
                       "line": word.get("line", index)})
    return result


def _lines(words):
    groups = OrderedDict()
    for word in words:
        groups.setdefault(word["line"], []).append(word)
    result = []
    for row in groups.values():
        row = sorted(row, key=lambda w: w["bbox"][0])
        result.append({"text": " ".join(w["text"] for w in row), "bbox": _hull([w["bbox"] for w in row]), "words": row})
    return sorted(result, key=lambda r: (r["bbox"][1], r["bbox"][0]))


def _name_pixels(image, search):
    """Isolate neutral name ink, excluding plaque edges and colored chip text."""
    from PIL import ImageChops
    red, green, blue = image.crop(search).convert("RGB").split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    neutral = ImageChops.subtract(maximum, minimum).point(lambda n: 255 if n <= 24 else 0)
    ink = ImageChops.multiply(neutral, minimum.point(lambda n: 255 if n >= 70 else 0))
    cache_sha256 = hashlib.sha256(ink.tobytes()).hexdigest()
    pixels = ink.load()
    width, height = ink.size
    # Borders touch the search envelope; text itself must remain fully visible.
    pending = [(x, y) for x in range(width) for y in (0, height - 1)]
    pending.extend((x, y) for y in range(height) for x in (0, width - 1))
    while pending:
        x, y = pending.pop()
        if not 0 <= x < width or not 0 <= y < height or not pixels[x, y]:
            continue
        pixels[x, y] = 0
        pending.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    box = ink.getbbox()
    if box is None or box[3] - box[1] < 4 or ink.histogram()[255] < 8:
        return None
    bounds = [max(search[0], search[0] + box[0] - 1), max(search[1], search[1] + box[1] - 1),
              min(search[2], search[0] + box[2] + 1), min(search[3], search[1] + box[3] + 1)]
    gray = ImageChops.multiply(minimum, ink)
    return {"bounds": bounds, "ink": ink, "gray": gray,
            "ink_sha256": cache_sha256}


def _panel_geometry(image, label_boxes):
    """Find a closed neutral-dark panel from pixels, seeded only by its labels."""
    from PIL import ImageChops, ImageDraw, ImageFilter
    rgb = image.convert("RGB")
    red, green, blue = rgb.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    neutral = ImageChops.subtract(maximum, minimum).point(lambda n: 255 if n <= 18 else 0)
    dark = ImageChops.multiply(neutral, maximum.point(lambda n: 255 if n <= 55 else 0))
    hull = _hull(label_boxes)
    glyph = max(1, min(b[3] - b[1] for b in label_boxes))
    pixels = dark.load()
    center = ((hull[0] + hull[2]) // 2, (hull[1] + hull[3]) // 2)
    candidates = [center, *((x, y) for y in range(hull[1], hull[3], max(1, glyph // 2))
                            for x in range(hull[0], hull[2], max(1, glyph)))]
    seed = next(((x, y) for x, y in candidates if pixels[x, y] == 255), None)
    if seed is None:
        return None
    ImageDraw.floodfill(dark, seed, 128)
    component = dark.point(lambda n: 255 if n == 128 else 0)
    box = component.getbbox()
    if not box or box[0] == 0 or box[1] == 0 or box[2] == image.width or box[3] == image.height:
        return None
    width, height = box[2] - box[0], box[3] - box[1]
    count = component.histogram()[255]
    if (width * height > image.width * image.height * 0.6 or count < width * height * 0.65 or
            any(b[0] < box[0] or b[1] < box[1] or b[2] > box[2] or b[3] > box[3] for b in label_boxes)):
        return None
    rows = component.crop(box).tobytes()
    full_rows = [y for y in range(height) if rows[y * width:(y + 1) * width].count(255) >= width * 0.8]
    if not full_rows:
        return None
    body = [box[0], box[1] + full_rows[0], box[2], box[1] + full_rows[-1] + 1]
    radius = max(1, round(image.width / REFERENCE_SIZE[0])) * 2
    edge_floor = max(rgb.getpixel(seed)) + 12
    gray = ImageChops.multiply(neutral, maximum.point(lambda n: 255 if edge_floor <= n <= 210 else 0))
    edge_pixels = gray.load()
    supports = {}
    for side in ("left", "right", "top", "bottom"):
        ratios = []
        for distance in range(radius + 1):
            if side in ("left", "right"):
                x = body[0] - distance if side == "left" else body[2] + distance - 1
                points = [(x, y) for y in range(body[1] + glyph, body[3] - glyph)] if 0 <= x < image.width else []
            else:
                y = body[1] - distance if side == "top" else body[3] + distance - 1
                points = [(x, y) for x in range(body[0] + glyph, body[2] - glyph)] if 0 <= y < image.height else []
            ratios.append(sum(edge_pixels[x, y] == 255 for x, y in points) / len(points) if points else 0)
        supports[side] = round(max(ratios), 4)
    if any(ratio < 0.7 for ratio in supports.values()):
        return None
    # Include observed gray strokes/pointer, not an assumed padding expansion.
    border = ImageChops.multiply(gray, component.filter(ImageFilter.MaxFilter(radius * 2 + 1)))
    border_box = border.getbbox()
    if border_box is None:
        return None
    return {"bounds": _hull([box, border_box]), "component_bounds": list(box), "body_bounds": body,
            "method": "neutral_dark_component_closed_border_v1", "edge_support": supports,
            "filled_pixels": count, "source": "original_pixels", "provisional": True}


class WindowsOcr:
    """Bounded Windows OCR batch; pixels use stdin, never a mailbox path."""
    def __init__(self, root, *, language="en-US", timeout=30):
        self.script = Path(root).resolve() / "scripts/laya_ocr.ps1"
        self.language, self.timeout = language, timeout
        self._region_cache = OrderedDict()
        self._value_cache = OrderedDict()
        self._proc = None
        self._lock = threading.Lock()

    def _close_proc(self, proc, *, kill=False):
        if proc is None:
            return
        for stream in (proc.stdin, proc.stdout):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        try:
            if kill:
                proc.kill()
            else:
                proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=1)
            except Exception:
                pass

    def close(self):
        with self._lock:
            proc, self._proc = self._proc, None
            self._close_proc(proc)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _invoke_persistent(self, host, encoded):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._close_proc(self._proc)
                self._proc = subprocess.Popen(
                    [str(host), "-NoProfile", "-NonInteractive", "-File", str(self.script),
                     "-Language", self.language, "-Persistent"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), bufsize=0)
            proc = self._proc
            result_holder = []

            def worker():
                try:
                    proc.stdin.write(encoded + b"\n")
                    proc.stdin.flush()
                    line = proc.stdout.readline(1024 * 1024 + 1)
                    result_holder.append(("ok", line))
                except Exception as exc:
                    result_holder.append(("err", exc))

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            t.join(timeout=self.timeout)
            if t.is_alive():
                self._proc = None
                self._close_proc(proc, kill=True)
                raise subprocess.TimeoutExpired(str(host), self.timeout)
            if not result_holder or result_holder[0][0] == "err":
                self._proc = None
                self._close_proc(proc, kill=True)
                if result_holder:
                    raise result_holder[0][1]
                return b""
            line = result_holder[0][1]
            if not line:
                self._proc = None
                self._close_proc(proc, kill=True)
            return line

    def read(self, image, regions, *, full_scale=2):
        from PIL import Image, ImageOps
        images, transforms = [], {}
        hashes, reused = {}, {}
        for name, box in [("full", [0, 0, image.width, image.height]), *regions.items()]:
            crop = image.crop(box).convert("RGB")
            transform_box = box
            if name != "full":
                ink = _name_pixels(image, box) if name.startswith("name_") else None
                key = (name, tuple(box), ink["ink_sha256"] if ink else _pixel_hash(crop))
                hashes[name] = key
                if key in self._region_cache:
                    reused[name] = copy.deepcopy(self._region_cache[key])
                    self._region_cache.move_to_end(key)
                    continue
                if ink:
                    b = ink["bounds"]
                    tight = ink["gray"].crop((b[0] - box[0], b[1] - box[1], b[2] - box[0], b[3] - box[1]))
                    margin = 16
                    crop = ImageOps.expand(ImageOps.invert(ImageOps.autocontrast(tight)), margin, fill=255).convert("RGB")
                    transform_box = [b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin]
            scale = min(full_scale if name == "full" else 4, 2400 / crop.width, 2400 / crop.height)
            size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
            resized = crop.resize(size, Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format="PNG")
            images.append({"id": name, "png": base64.b64encode(buffer.getvalue()).decode("ascii")})
            transforms[name] = transform_box, size
        result = self._run_batch(images, transforms, image.size)
        if result.get("status") == "ok":
            for name, words in result.get("regions", {}).items():
                self._region_cache[hashes[name]] = copy.deepcopy(words)
                self._region_cache.move_to_end(hashes[name])
            while len(self._region_cache) > 32:
                self._region_cache.popitem(last=False)
            result["regions"].update(reused)
            result["region_compute_reused"] = list(reused)
        return result

    def _run_batch(self, images, transforms, image_size):
        if os.name != "nt":
            return {"status": "unavailable", "reason": "windows-ocr-requires-windows", "words": []}
        host = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if not host.is_file() or not self.script.is_file():
            return {"status": "unavailable", "reason": "windows-ocr-host-or-adapter-missing", "words": []}
        encoded = json.dumps({"images": images}, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 16000000:
            raise ValueError("windows-ocr-input-too-large")
        try:
            if subprocess.run is getattr(subprocess, "run", None) and subprocess.run.__module__ == "subprocess":
                stdout = self._invoke_persistent(host, encoded)
                returncode = 0 if stdout else 1
            else:
                process = subprocess.run([str(host), "-NoProfile", "-NonInteractive", "-File", str(self.script),
                                          "-Language", self.language], input=encoded, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, timeout=self.timeout, check=False,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                stdout = process.stdout
                returncode = process.returncode
            if len(stdout) > 1024 * 1024:
                raise ValueError("windows-ocr-output-too-large")
            data = json.loads(stdout.decode("utf-8-sig"))
            if returncode or data.get("status") != "ok":
                return {"status": "unavailable", "reason": str(data.get("reason", "windows-ocr-failed"))[:240], "words": []}
        except subprocess.TimeoutExpired:
            return {"status": "unavailable", "reason": "windows-ocr-process-timeout", "words": []}
        except (OSError, UnicodeError, ValueError) as error:
            return {"status": "unavailable", "reason": "windows-ocr-adapter:" + str(error)[:200], "words": []}
        output = {"status": "ok", "method": "windows_media_ocr_cpu", "language": data.get("language"),
                  "words": [], "regions": {}, "region_rejections": {}}
        seen = set()
        for item in data.get("images", []):
            name = item.get("id")
            if name not in transforms or name in seen:
                raise ValueError("windows-ocr-invalid-output-region")
            seen.add(name)
            box, size = transforms[name]
            if [item.get("width"), item.get("height")] != list(size):
                raise ValueError("windows-ocr-output-geometry")
            angle = item.get("text_angle", 0)
            if type(angle) not in (int, float) or not math.isfinite(angle):
                raise ValueError("windows-ocr-invalid-text-angle")
            words = _words(item.get("words"), size)
            for word in words:
                b = word["bbox"]
                if angle:
                    # WinRT requires a clockwise overlay rotation around center.
                    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                    cx, cy = size[0] / 2, size[1] / 2
                    corners = [(cx + (x - cx) * cosine - (y - cy) * sine,
                                cy + (x - cx) * sine + (y - cy) * cosine)
                               for x, y in ((b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]))]
                    b = [min(x for x, _ in corners), min(y for _, y in corners),
                         max(x for x, _ in corners), max(y for _, y in corners)]
                word["bbox"] = _bounds([box[0] + b[0] * (box[2] - box[0]) / size[0],
                                        box[1] + b[1] * (box[3] - box[1]) / size[1],
                                        box[0] + b[2] * (box[2] - box[0]) / size[0],
                                        box[1] + b[3] * (box[3] - box[1]) / size[1]], image_size)
            if name == "full":
                output["words"] = words
            else:
                output["regions"][name] = words
        if seen != set(transforms):
            raise ValueError("windows-ocr-incomplete-output")
        return output

    def read_region(self, image, bounds, *, text_only=False):
        bounds = _bounds(bounds, image.size)
        cropped = image.crop(bounds).convert("RGB")
        if text_only:
            from PIL import ImageChops, ImageOps
            red, green, blue = cropped.split()
            maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
            minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
            neutral = ImageChops.subtract(maximum, minimum).point(lambda n: 255 if n <= 24 else 0)
            light = minimum.point(lambda n: 255 if n >= 160 else 0)
            cropped = ImageOps.invert(ImageChops.multiply(neutral, light)).convert("RGB")
        result = self.read(cropped, {}, full_scale=4)
        result["preprocessing"] = "neutral_light_text_black_on_white" if text_only else "original_rgb"
        if result.get("status") == "ok":
            for word in result["words"]:
                b = word["bbox"]
                word["bbox"] = [b[0] + bounds[0], b[1] + bounds[1], b[2] + bounds[0], b[3] + bounds[1]]
        return result

    def read_values(self, image, profile):
        from PIL import Image, ImageChops, ImageOps
        cache_key = (tuple(profile["bounds"]), _pixel_hash(image.crop(profile["bounds"])))
        if cache_key in self._value_cache:
            self._value_cache.move_to_end(cache_key)
            return {**copy.deepcopy(self._value_cache[cache_key]), "pixel_compute_reused": True}
        labels = sorted(profile["label_bounds"].items(), key=lambda pair: pair[1][0] + pair[1][2])
        if max(b[1] for _, b in labels) - min(b[1] for _, b in labels) > max(b[3] - b[1] for _, b in labels):
            return {"status": "unavailable", "reason": "profile-value-layout-not-qualified", "words": []}
        centers = [(b[0] + b[2]) / 2 for _, b in labels]
        panel = profile["bounds"]
        images, transforms = [], {}
        for index, (key, label) in enumerate(labels):
            left = panel[0] if index == 0 else round((centers[index - 1] + centers[index]) / 2)
            right = panel[2] if index == len(labels) - 1 else round((centers[index] + centers[index + 1]) / 2)
            cell = _bounds([left, label[3], right, panel[3]], image.size)
            red, green, blue = image.crop(cell).convert("RGB").split()
            maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
            minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
            neutral = ImageChops.subtract(maximum, minimum).point(lambda n: 255 if n <= 24 else 0)
            light = ImageChops.multiply(neutral, minimum.point(lambda n: 255 if n >= 100 else 0))
            glyphs = light.getbbox()
            if glyphs is None:
                continue
            crop_box = list(glyphs)
            for version, (margin, resample) in enumerate(((80, Image.Resampling.LANCZOS),
                                                        (160, Image.Resampling.LANCZOS),
                                                        (80, Image.Resampling.BICUBIC))):
                crop = ImageOps.expand(ImageOps.invert(light.crop(crop_box)), margin, fill=255).convert("RGB")
                scale = min(2, 2400 / crop.width, 2400 / crop.height)
                size = max(1, round(crop.width * scale)), max(1, round(crop.height * scale))
                buffer = io.BytesIO()
                crop.resize(size, resample).save(buffer, format="PNG")
                name = key + "_" + str(version)
                images.append({"id": name, "png": base64.b64encode(buffer.getvalue()).decode("ascii")})
                # Blank OCR padding is virtual; map glyphs back to the source.
                transforms[name] = [cell[0] + crop_box[0] - margin, cell[1] + crop_box[1] - margin,
                                    cell[0] + crop_box[2] + margin, cell[1] + crop_box[3] + margin], size
        result = self._run_batch(images, transforms, image.size) if images else {"status": "ok", "words": [], "regions": {}}
        candidates = {key: [] for key in METRICS}
        for name, words in result.get("regions", {}).items():
            key = name.rsplit("_", 1)[0]
            for row in _lines(words):
                parsed = parse_percent(METRICS[key], row["text"])
                if parsed["status"] in {"accepted", "dash"} and _inside(row["bbox"], profile["bounds"]):
                    candidates[key].append((parsed["status"], parsed["percent"], row["words"]))
        result["value_rejections"] = {}
        for key, readings in candidates.items():
            if len({(status, percent) for status, percent, _ in readings}) > 1:
                result["value_rejections"][key] = "conflicting_cpu_value_reads"
            elif readings:
                for word in readings[0][2]:
                    word["line"] = (key, word["line"])
                    result["words"].append(word)
            else:
                result["value_rejections"][key] = "cpu_value_not_recognized"
        result["preprocessing"] = "pixel_isolated_neutral_light_values_black_on_white"
        if result.get("status") == "ok":
            self._value_cache[cache_key] = copy.deepcopy(result)
            while len(self._value_cache) > 8:
                self._value_cache.popitem(last=False)
        return result


class ContextReader:
    def __init__(self, root, *, ocr=None, self_name=None, control_evidence=None):
        self.root = Path(root).resolve()
        self.ocr = WindowsOcr(self.root) if ocr is None else ocr
        self._control_templates = []
        config = self.root / ".local/laya/self-player.json"
        if config.is_file():
            from PIL import Image
            raw = config.read_bytes()
            if len(raw) > 16384:
                raise ValueError("self-player-config-too-large")
            settings = json.loads(raw)
            if self_name is None:
                self_name = settings.get("display_name")
            templates = settings.get("control_references", [])
            if not isinstance(templates, list) or len(templates) > 6:
                raise ValueError("invalid-self-control-references")
            for template in templates:
                path = (self.root / template["path"]).resolve()
                if not path.is_relative_to(self.root / ".local") or path.stat().st_size > 1024 * 1024:
                    raise ValueError("invalid-self-control-reference-path")
                png = path.read_bytes()
                if hashlib.sha256(png).hexdigest() != template["sha256"]:
                    raise ValueError("self-control-reference-hash-mismatch")
                with Image.open(io.BytesIO(png)) as opened:
                    if opened.width > 512 or opened.height > 256:
                        raise ValueError("self-control-reference-too-large")
                    pixels = opened.convert("RGB")
                if (template.get("kind") not in {"own_action_controls", "self_player"} or
                        not isinstance(template.get("label"), str) or not 1 <= len(template["label"]) <= 64):
                    raise ValueError("invalid-self-control-reference")
                self._control_templates.append((copy.deepcopy(template), pixels.copy()))
        if self_name is not None and _name(self_name) != self_name:
            raise ValueError("actual-self-name-required")
        self.self_name, self.control_evidence = self_name, control_evidence
        self._pixels = self._computed = None

    def close(self):
        if hasattr(self.ocr, "close"):
            self.ocr.close()

    def read(self, image, capture, occluded_regions=()):
        scope = _receipt(capture)
        if image.size != (capture["width"], capture["height"]):
            raise ValueError("context-original-image-geometry-mismatch")
        masks = [_bounds(box, image.size) for box in occluded_regions]
        started = time.perf_counter()
        names = [scaled_bounds(b, image.size) for b in NAME_BOUNDS]
        seats = [scaled_bounds(b, image.size) for b in SEAT_BOUNDS]
        caption = scaled_bounds(CAPTION_BOUNDS, image.size)
        controls = scaled_bounds(CONTROLS_BOUNDS, image.size)
        geometry_ok = abs(image.width / (image.height - TITLE_HEIGHT) - 1.3677) < 0.06
        regions = {**{"name_%d" % (n + 1): box for n, box in enumerate(names)},
                   "caption": caption, "controls": controls}
        pixels = _pixel_hash(image)
        cached = pixels == self._pixels and self._computed is not None
        if cached:
            ocr = copy.deepcopy(self._computed)
        elif geometry_ok:
            try:
                ocr = self.ocr.read(image, regions)
                if not isinstance(ocr, dict) or ocr.get("status") != "ok":
                    reason = ocr.get("reason", "ocr-unavailable") if isinstance(ocr, dict) else "invalid-ocr-output"
                    ocr = {"status": "unavailable", "reason": str(reason)[:240], "words": []}
                else:
                    ocr = {**ocr, "words": _words(ocr.get("words", []), image.size),
                           "regions": {key: _words(value, image.size) for key, value in ocr.get("regions", {}).items()}}
                if ocr["status"] == "ok":
                    self._pixels, self._computed = pixels, copy.deepcopy(ocr)
            except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
                ocr = {"status": "unavailable", "reason": str(error)[:240], "words": []}
        else:
            ocr = {"status": "unavailable", "reason": "unvalidated-table-geometry", "words": []}
        full = ocr["words"]

        def words_in(key, box):
            selected = ocr.get("regions", {}).get(key)
            if not selected:
                return [w for w in full if _inside(w["bbox"], box)]
            return selected

        result = {"schema_version": 1, "method": ocr.get("method", "windows_media_ocr_cpu"),
                  "recognizer_version": "context_cpu_v3", "provisional": True, "human_reviewed": False,
                  "quality_approved": False, "capture": copy.deepcopy(capture),
                  "expires_at_ms": capture["captured_at_ms"] + MAX_AGE_MS,
                  "expires_at_unix_ms": capture["captured_at_unix_ms"] + MAX_AGE_MS,
                  "role": "uncertain", "hero_seat": None, "table_context_id": None,
                  "table_caption": None, "occluded_regions": masks, "seats": [], "profile": None,
                  "eventchanges": [], "evidence": {}, "geometry_source": copy.deepcopy(GEOMETRY_SOURCE),
                  "ocr": {k: ocr[k] for k in ("status", "reason", "language") if k in ocr},
                  "pixel_compute_reused": cached}
        for index, (name_box, seat_box) in enumerate(zip(names, seats), 1):
            words = words_in("name_%d" % index, name_box)
            rows = _lines(words)
            literal = rows[0]["text"] if len(rows) == 1 else None
            raw = literal[:MAX_NAME] if literal else None
            identity = _name(literal)
            clipped = any(w["bbox"][0] <= name_box[0] or w["bbox"][2] >= name_box[2] for w in words)
            vacant = [r for r in _lines([w for w in full if _inside(w["bbox"], seat_box)])
                      if r["text"].casefold().strip() in VACANT_TEXT]
            reason = "missing_or_ambiguous_name"
            occupancy = "unknown"
            bounds = name_box
            if identity:
                occupancy, reason = "occupied", "visible_player_name"
                if clipped:
                    identity, reason = None, "clipped_name"
                else:
                    ink = _name_pixels(image, name_box)
                    literal_bounds = _hull([w["bbox"] for w in words])
                    if ink and _overlap(ink["bounds"], literal_bounds):
                        bounds = ink["bounds"]
                    else:
                        bounds = [max(name_box[0], literal_bounds[0] - 1), max(name_box[1], literal_bounds[1] - 1),
                                  min(name_box[2], literal_bounds[2] + 1), min(name_box[3], literal_bounds[3] + 1)]
            elif raw and ("..." in raw or "\u2026" in raw):
                occupancy, reason = "occupied", "truncated_name"
            elif literal and len(literal) > MAX_NAME:
                occupancy, reason = "occupied", "overlong_name"
            elif literal and re.fullmatch(r"\d{1,64}", literal) and not clipped:
                ink = _name_pixels(image, name_box)
                if ink and _overlap(ink["bounds"], _hull([w["bbox"] for w in words])):
                    occupancy, reason, bounds = "occupied", "numeric_name_identity_unqualified", ink["bounds"]
            if vacant:
                if occupancy == "occupied" or len(vacant) != 1:
                    occupancy, identity, reason = "unknown", None, "contradictory_seat_evidence"
                else:
                    occupancy, identity, reason, bounds = "empty", None, "explicit_vacant_affordance", vacant[0]["bbox"]
            if any(_overlap(bounds, m) for m in masks):
                occupancy, identity, reason = "unknown", None, "occluded_identity_region"
            if ocr["status"] != "ok":
                occupancy, identity, reason = "unknown", None, ocr.get("reason", "ocr-unavailable")
            status_words = [w for w in full if _inside(w["bbox"], seat_box) and not any(_overlap(w["bbox"], m) for m in masks)]
            participation = next((r["text"].casefold().replace(" ", "_") for r in _lines(status_words)
                                  if r["text"].casefold() in {"fold", "sitting out", "all-in"}), None)
            result["seats"].append({"seat": index, "occupancy": occupancy, "identity": identity,
                                    "raw_name": raw, "occupant_epoch": 0, "continuity": "uncertain",
                                    "status": "provisional" if occupancy != "unknown" else "unknown",
                                    "reason": reason, "stats": None, "participation": participation,
                                    "bounds": bounds, "crop_sha256": _pixel_hash(image.crop(bounds)),
                                    "name_search_bounds": name_box,
                                    "bounds_kind": "name_text_pixels" if bounds != name_box and occupancy == "occupied" else "seat_search_region",
                                    "capture": copy.deepcopy(capture)})
        duplicates = {s["identity"] for s in result["seats"] if s["identity"] and
                      sum(t["identity"] == s["identity"] for t in result["seats"]) > 1}
        for seat in result["seats"]:
            if seat["identity"] in duplicates:
                seat.update(identity=None, reason="duplicate_player_name")
        if ocr["status"] == "ok" and not any(_overlap(caption, m) for m in masks):
            title = " ".join(r["text"] for r in _lines(words_in("caption", caption)))[:160]
            match = re.fullmatch(r"\s*(NLH|PLO[456]?)\s+([0-9]{3,12})\s*(?:-.*)?", title, re.IGNORECASE)
            if match:
                result["table_caption"] = {"literal": title, "key": match[1].upper() + " " + match[2],
                                           "bounds": caption, "capture": copy.deepcopy(capture), "status": "provisional"}
                result["table_context_id"] = hashlib.sha256(json.dumps([scope, result["table_caption"]["key"]]).encode()).hexdigest()[:32]
        if ocr["status"] == "ok":
            result["profile"] = self._profile(full, result, image, names, masks)
            panel = result["profile"]
            if (panel and panel.get("panel_geometry_qualified") and not ocr.get("panel_region_attempted") and
                    hasattr(self.ocr, "read_region")):
                cropped = (self.ocr.read_values(image, panel) if hasattr(self.ocr, "read_values") else
                           self.ocr.read_region(image, panel["bounds"], text_only=True))
                ocr["panel_region_attempted"] = True
                ocr["panel_region_status"] = cropped.get("status", "unavailable")
                ocr["panel_region_preprocessing"] = cropped.get("preprocessing")
                ocr["panel_value_rejections"] = cropped.get("value_rejections", {})
                if cropped.get("status") == "ok":
                    # Keep original title/labels; strip chart rings only for values.
                    numeric = lambda w: bool(re.fullmatch(r"(?:-?\d{1,3}(?:\.\d{1,6})?%?|%|--?|\u2013|\u2014)", w["text"]))
                    bottom = min(b[3] for b in panel["label_bounds"].values())
                    from_crop = [w for w in _words(cropped.get("words", []), image.size) if numeric(w) and w["bbox"][1] >= bottom]
                    full = [w for w in full if not (_inside(w["bbox"], panel["bounds"]) and numeric(w) and w["bbox"][1] >= bottom)] + from_crop
                    # Independent OCR images have independent line-number namespaces.
                    for word in full:
                        word["line"] = ("panel" if _inside(word["bbox"], panel["bounds"]) else "table", word["line"])
                    ocr["words"] = full
                    result["profile"] = self._profile(full, result, image, names, masks)
                    if result["profile"]:
                        result["profile"]["value_preprocessing"] = cropped["preprocessing"]
                else:
                    ocr["panel_region_rejection"] = cropped.get("reason", "profile-region-ocr-unavailable")
                self._computed = copy.deepcopy(ocr)
        panel = result["profile"]
        if panel and ocr.get("panel_region_preprocessing"):
            panel["value_preprocessing"] = ocr["panel_region_preprocessing"]
        if panel and ocr.get("panel_region_rejection"):
            panel["ocr_region_rejection"] = ocr["panel_region_rejection"]
        if panel:
            for key, reason in ocr.get("panel_value_rejections", {}).items():
                if panel["metrics"][key]["percent"] is None:
                    panel["metrics"][key].update(status="unreadable", reason=reason)
            if panel.get("owner") and panel.get("crop_sha256"):
                panel["revision"] = hashlib.sha256(json.dumps([panel["owner"], panel["metrics"], panel["crop_sha256"]], sort_keys=True).encode()).hexdigest()[:32]
        if panel and (panel.get("status") == "provisional" or panel.get("panel_geometry_qualified")) and panel.get("bounds"):
            panel_box = panel["bounds"]
            for seat in result["seats"]:
                if _overlap(seat["bounds"], panel_box):
                    seat.update(occupancy="unknown", identity=None, status="unknown", reason="profile_covers_identity")
            masks = [*masks, panel_box]
            result["occluded_regions"] = masks
        rows = _lines(words_in("controls", controls))
        text = " ".join(r["text"] for r in rows).casefold()
        observer = "find seat" in text and "join wait list" in text and not any(_overlap(controls, m) for m in masks)
        role_evidence = {"status": "unknown", "origin": None, "hero_seat": None,
                         "capture": copy.deepcopy(capture), "bounds": controls, "reason": "no_positive_role_evidence"}
        own = None
        if self.self_name and ocr["status"] == "ok":
            own = (self.control_evidence(image, copy.deepcopy(capture)) if self.control_evidence is not None
                   else self._own_controls(image, capture, full))
        own_seats = [s for s in result["seats"] if s["identity"] == self.self_name] if self.self_name else []
        if observer:
            result["role"] = "observing"
            role_evidence.update(status="provisional", origin="observer_controls", reason="find_seat_and_join_wait_list")
        if own and own.get("capture") == capture and len(own_seats) == 1:
            own_box = _bounds(own.get("bounds"), image.size)
            if not observer and not any(_overlap(own_box, m) for m in masks):
                role = ("your_turn" if own.get("enabled") is True and own.get("kind") == "own_action_controls" else
                        "seated_waiting" if own.get("waiting") is True and own.get("kind") == "self_player" else "uncertain")
                if role != "uncertain":
                    hero = own_seats[0]["seat"]
                    result.update(role=role, hero_seat=hero)
                    role_evidence.update(status="provisional", origin=own["kind"], hero_seat=hero,
                                         bounds=_hull([own_box, own_seats[0]["bounds"]]),
                                         reason="actual_self_name_and_current_controls")
            elif observer:
                result.update(role="uncertain", hero_seat=None)
                role_evidence.update(status="unknown", origin=None, reason="contradictory_observer_and_self_evidence")
        result["evidence"]["role"] = role_evidence
        for seat in result["seats"]:
            seat["table_context_id"] = result["table_context_id"]
        result["processing_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    def _own_controls(self, image, capture, words):
        # Exact known-enabled pixels plus their text, not color or absent cards.
        matches = []
        for template, pixels in self._control_templates:
            if template.get("frame_dimensions") != list(image.size):
                continue
            bounds = _bounds(template.get("bounds"), image.size)
            visible = " ".join(r["text"] for r in _lines([w for w in words if _inside(w["bbox"], bounds)]))
            crop = image.crop(bounds).convert("RGB")
            if visible.casefold() == template["label"].casefold() and crop.size == pixels.size and crop.tobytes() == pixels.tobytes():
                matches.append({"kind": template["kind"], "enabled": template["kind"] == "own_action_controls",
                                "waiting": template["kind"] == "self_player", "bounds": bounds,
                                "capture": copy.deepcopy(capture)})
        if not matches or len({m["kind"] for m in matches}) != 1:
            return None
        return {**matches[0], "bounds": _hull([m["bounds"] for m in matches])}

    def read_popup(self, image, popup_capture, roster):
        """Recognize visible popup pixels under their separate non-atomic receipt."""
        scope = _receipt(popup_capture)
        parent = popup_capture.get("parent_capture")
        if (_receipt(parent) != scope or popup_capture.get("non_atomic") is not True or
                image.size != (popup_capture["width"], popup_capture["height"])):
            raise ValueError("popup-original-parent-receipt-required")
        if not isinstance(roster, list) or len(roster) != 6:
            raise ValueError("popup-six-seat-roster-required")
        for seat in roster:
            if seat.get("capture") != parent:
                raise ValueError("popup-roster-parent-receipt-mismatch")
        tables = {s.get("table_context_id") for s in roster if s.get("table_context_id")}
        table = next(iter(tables)) if len(tables) == 1 else None
        ocr = self.ocr.read(image, {})
        if not isinstance(ocr, dict) or ocr.get("status") != "ok":
            return None
        result = {"capture": copy.deepcopy(popup_capture), "table_context_id": table, "seats": copy.deepcopy(roster)}
        profile = self._profile(_words(ocr.get("words", []), image.size), result, image, [], [])
        if profile:
            profile["non_atomic"] = True
        return profile

    @staticmethod
    def _profile(words, result, image, name_boxes, masks):
        labels = []
        used_labels = set()
        for row in _lines(words):
            tokens = row["words"]
            index = 0
            while index < len(tokens):
                found = False
                for count in range(1, min(3, len(tokens) - index) + 1):
                    segment = tokens[index:index + count]
                    text = " ".join(w["text"] for w in segment)
                    key = next((k for k, canonical in METRICS.items()
                                if re.sub(r"[\s-]", "", text.upper()) == canonical.replace("-", "")), None)
                    if key:
                        labels.append({"key": key, "label": text, "bbox": _hull([w["bbox"] for w in segment]),
                                       "tokens": segment, "row": row, "end": index + count})
                        used_labels.update(id(w) for w in segment)
                        index += count
                        found = True
                        break
                if not found:
                    index += 1
        if not labels:
            return None
        bounds = _hull([label["bbox"] for label in labels])
        profile = {"source": "client_profile_tooltip", "owner": None, "seat": None,
                   "occupant_epoch": None, "table_context_id": result["table_context_id"],
                   "capture": copy.deepcopy(result["capture"]),
                   "captured_at_unix_ms": result["capture"]["captured_at_unix_ms"],
                   "metrics": {k: parse_percent(v, None) for k, v in METRICS.items()},
                   "sample_size": None, "scope": None, "bounds": bounds,
                   "bounds_kind": "ocr_content_hull", "panel_geometry_qualified": False,
                   "status": "rejected", "reason": "incomplete_profile_labels", "provisional": True,
                   "human_reviewed": False, "quality_approved": False}
        keys = [label["key"] for label in labels]
        if len(labels) != 4 or set(keys) != set(METRICS):
            if len(set(keys)) != len(keys):
                profile["reason"] = "duplicate_profile_labels"
            return profile
        heights = sorted(label["bbox"][3] - label["bbox"][1] for label in labels)
        height = max(1, heights[2])
        if bounds[2] - bounds[0] > 40 * height or bounds[3] - bounds[1] > 20 * height:
            profile["reason"] = "incoherent_profile_labels"
            return profile
        profile["label_bounds"] = {label["key"]: label["bbox"] for label in labels}
        geometry = _panel_geometry(image, [label["bbox"] for label in labels])
        if geometry:
            profile.update(bounds=geometry["bounds"], bounds_kind="pixel_verified_panel_border",
                           panel_geometry_qualified=True, geometry=geometry)
        value_words, used_values = [], set()
        for label in labels:
            row = label["row"]["words"]
            remaining = []
            for word in row[label["end"]:]:
                if id(word) in used_labels:
                    break
                if word["bbox"][0] - label["bbox"][2] > 6 * height:
                    break
                remaining.append(word)
            if not remaining:
                center = (label["bbox"][0] + label["bbox"][2]) / 2
                remaining = [w for w in words if id(w) not in used_labels and
                             0 <= w["bbox"][1] - label["bbox"][3] <= (geometry["bounds"][3] - label["bbox"][3] if geometry else 2 * height) and
                             (not geometry or _inside(w["bbox"], geometry["bounds"])) and
                             abs((w["bbox"][0] + w["bbox"][2]) / 2 - center) < max(2 * height, (label["bbox"][2] - label["bbox"][0]) / 2)]
            literal = " ".join(w["text"] for w in remaining) if remaining else None
            parsed = parse_percent(label["label"], literal)
            if any(id(w) in used_values for w in remaining):
                parsed.update(percent=None, status="unreadable", reason="misaligned_or_shared_value")
                profile["reason"] = "misaligned_profile_values"
            used_values.update(id(w) for w in remaining)
            value_words.extend(remaining)
            profile["metrics"][label["key"]] = parsed
        content_bounds = _hull([bounds, *[w["bbox"] for w in value_words]])
        headers = [row for row in _lines(words) if row["bbox"][3] <= bounds[1] and
                   (geometry and _inside(row["bbox"], geometry["bounds"]) or bounds[1] - row["bbox"][3] <= 4 * height) and
                   content_bounds[0] - 2 * height <= row["bbox"][0] < content_bounds[2] and
                   row["bbox"][2] <= content_bounds[2] + 2 * height and
                   not any(_overlap(row["bbox"], box) for box in name_boxes)]
        owners = []
        for row in headers:
            blocks = [[]]
            for word in row["words"]:
                if blocks[-1] and word["bbox"][0] - blocks[-1][-1]["bbox"][2] > 2 * height:
                    blocks.append([])
                blocks[-1].append(word)
            for block in blocks:
                text = re.sub(r"^(?:Player|Profile)\s*:\s*", "", " ".join(w["text"] for w in block), flags=re.IGNORECASE)
                owner = _name(text)
                if owner:
                    owners.append((owner, {"bbox": _hull([w["bbox"] for w in block]),
                                           "literal": " ".join(w["text"] for w in block)}))
        if len(owners) != 1:
            profile["reason"] = "missing_or_ambiguous_profile_title"
            return profile
        owner, title = owners[0]
        profile.update(owner=owner, content_bounds=_hull([content_bounds, title["bbox"]]))
        profile["title"] = {"literal": title["literal"], "identity": owner, "bounds": title["bbox"]}
        if not geometry:
            profile["bounds"] = profile["content_bounds"]
        profile["crop_sha256"] = _pixel_hash(image.crop(profile["bounds"]))
        profile["revision"] = hashlib.sha256(json.dumps([owner, profile["metrics"], profile["crop_sha256"]], sort_keys=True).encode()).hexdigest()[:32]
        matches = [seat for seat in result["seats"] if seat["identity"] == owner and seat["occupancy"] == "occupied"]
        # Native masks describe the obscured table, not the visible owned panel.
        if len(matches) != 1 or result["table_context_id"] is None:
            profile["reason"] = "owner_not_unique_in_current_table"
        elif profile["reason"] != "misaligned_profile_values":
            profile.update(seat=matches[0]["seat"], status="provisional", reason="coherent_labels_and_exact_title")
        return profile


class ContextTimeline:
    """Two-receipt roster confirmation and owner/epoch/table-bound profile cache."""
    def __init__(self):
        self.events = deque(maxlen=MAX_EVENTS)
        self.profile_cache = OrderedDict()
        self._scope = self._capture = self._table = self._table_candidate = self._value = None
        self._table_count = 0
        self._seats = {n: {"identity": None, "occupancy": "unknown", "epoch": 0,
                           "candidate": None, "count": 0} for n in range(1, 7)}
        self._profile_revision = self._role = self._geometry = None
        self._profile_rejection = None
        self._retired_scopes = set()
        self._signature = None

    def invalidate_fields(self, seats, reason="source-region-changed"):
        if (not isinstance(seats, (list, tuple)) or
                any(type(seat) is not int or not 1 <= seat <= 6 for seat in seats) or
                not isinstance(reason, str) or not 1 <= len(reason) <= 160):
            raise ValueError("invalid-context-invalidation")
        for number in seats:
            self._seats[number].update(candidate=None, count=0)
            if self._value is not None:
                seat = next(s for s in self._value["seats"] if s["seat"] == number)
                seat.update(occupancy="unknown", identity=None, continuity="uncertain",
                            status="unknown", reason=reason, stats=None)
        if self._value is not None and self._value["hero_seat"] in seats:
            self._value.update(role="uncertain", hero_seat=None)
            self._value["evidence"]["role"].update(status="unknown", hero_seat=None, reason=reason)
        profile = self._value.get("profile") if self._value is not None else None
        if profile and profile.get("seat") in seats:
            self._value["profile"].update(status="rejected", reason=reason)
            self._profile_revision = None

    def observe(self, result, *, now_ms=None):
        capture = result["capture"]
        scope = _receipt(capture)
        seats = result.get("seats")
        if (not isinstance(seats, list) or len(seats) != 6 or
                any(type(s.get("seat")) is not int for s in seats) or
                sorted(s["seat"] for s in seats) != list(range(1, 7))):
            raise ValueError("context-six-physical-seats-required")
        for seat in seats:
            if seat.get("capture") != capture:
                raise ValueError("context-seat-original-receipt-mismatch")
            if seat.get("occupancy") not in {"occupied", "empty", "unknown"}:
                raise ValueError("context-invalid-occupancy")
            if seat.get("identity") is not None and _name(seat["identity"]) != seat["identity"]:
                raise ValueError("context-invalid-identity")
            _bounds(seat.get("bounds"), (capture["width"], capture["height"]))
        profile = result.get("profile")
        if profile and profile.get("capture") != capture:
            child = profile.get("capture") or {}
            if (child.get("parent_capture") != capture or child.get("non_atomic") is not True or
                    _receipt(child) != scope):
                raise ValueError("context-profile-original-receipt-mismatch")
        table = result.get("table_context_id")
        if table is not None and (not isinstance(table, str) or not re.fullmatch(r"[a-f0-9]{32}", table)):
            raise ValueError("invalid-table-context-id")
        role = result.get("evidence", {}).get("role", {})
        if role.get("capture") != capture:
            raise ValueError("context-role-original-receipt-mismatch")
        _bounds(role.get("bounds"), (capture["width"], capture["height"]))
        signature = hashlib.sha256(json.dumps({k: result.get(k) for k in
                                  ("seats", "table_context_id", "table_caption", "profile", "role", "hero_seat", "evidence")},
                                  sort_keys=True, allow_nan=False).encode()).hexdigest()
        if now_ms is not None and (type(now_ms) is not int or not 0 <= now_ms - capture["captured_at_ms"] < MAX_AGE_MS):
            return self._rejected(result, "stale_context_capture")
        if scope in self._retired_scopes:
            return self._rejected(result, "retired_context_source")
        if scope == self._scope and self._capture:
            previous = self._capture
            if capture["sequence"] <= previous["sequence"]:
                if capture == previous and signature == self._signature and self._value is not None:
                    value = copy.deepcopy(self._value)
                    value["eventchanges"] = []
                    value["rejection"] = "duplicate_capture"
                    return value
                return self._rejected(result, "old_or_conflicting_context_capture")
            if capture["captured_at_ms"] <= previous["captured_at_ms"] or capture["captured_at_unix_ms"] <= previous["captured_at_unix_ms"]:
                return self._rejected(result, "nonmonotonic_context_capture")
        value = copy.deepcopy(result)
        changes = []

        def event(kind, reason, **fields):
            item = {"kind": kind, "type": kind, "status": "confirmed", "reason": reason,
                    "capture": copy.deepcopy(capture), "table_context_id": self._table,
                    "provisional": True, "human_reviewed": False, **fields}
            item["event_id"] = hashlib.sha256(json.dumps(item, sort_keys=True, allow_nan=False).encode()).hexdigest()[:32]
            changes.append(item)

        if scope != self._scope:
            if self._scope is not None:
                self._retired_scopes.add(self._scope)
                if len(self._retired_scopes) > MAX_CACHE:
                    self._retired_scopes.pop()
            self._scope, self._table, self._table_candidate, self._table_count = scope, None, None, 0
            self._seats = {n: {"identity": None, "occupancy": "unknown", "epoch": 0,
                               "candidate": None, "count": 0} for n in range(1, 7)}
            self.profile_cache.clear()
            self._profile_revision = None
            self._profile_rejection = None
            self._capture = None
            event("source_boundary", "new_original_source")
        geometry = capture["width"], capture["height"]
        if self._geometry is not None and geometry != self._geometry:
            for state in self._seats.values():
                state.update(candidate=None, count=0)
            event("geometry_change", "old_crop_work_invalidated")
        if self._capture and scope == self._scope and capture["captured_at_ms"] - self._capture["captured_at_ms"] >= MAX_AGE_MS:
            for state in self._seats.values():
                state.update(candidate=None, count=0)
            self._table_candidate, self._table_count = None, 0
            event("capture_gap", "continuity_requires_new_confirmation")
        caption_changed = table != self._table_candidate
        if caption_changed:
            self._table_candidate, self._table_count = table, 1 if table is not None else 0
        elif table is not None:
            self._table_count += 1
        table_current = table is not None and table == self._table and self._table_count >= 2
        if caption_changed or table is None:
            for state in self._seats.values():
                state.update(candidate=None, count=0)
        if table is not None and self._table_count >= 2 and table != self._table:
            replacement = self._table is not None
            self._table = table
            if replacement:
                self._seats = {n: {"identity": None, "occupancy": "unknown", "epoch": 0,
                                   "candidate": None, "count": 0} for n in range(1, 7)}
                self.profile_cache.clear()
                self._profile_revision = None
            event("table_context_change" if replacement else "table_context_confirmed", "two_fresh_caption_receipts")
            table_current = True
        value["table_context_id"] = self._table if table_current else None
        counts = {s["identity"]: sum(t["identity"] == s["identity"] for t in seats) for s in seats if s["identity"]}
        for seat in value["seats"]:
            state = self._seats[seat["seat"]]
            identity = seat["identity"]
            occupancy = seat["occupancy"]
            qualified = False
            if identity and counts[identity] > 1:
                identity = None
                seat["reason"] = "duplicate_player_name"
            candidate = ((occupancy, identity) if (occupancy == "empty" or occupancy == "occupied" and identity)
                         and table is not None else None)
            if candidate is None:
                state.update(candidate=None, count=0)
            else:
                if candidate != state["candidate"]:
                    state.update(candidate=candidate, count=1)
                else:
                    state["count"] += 1
                if state["count"] >= 2 and table_current:
                    old_name, old_occupancy = state["identity"], state["occupancy"]
                    if occupancy == "occupied" and (identity != old_name or old_occupancy != "occupied"):
                        state["epoch"] += 1
                        kind = "occupant_replaced" if old_name and old_occupancy == "occupied" else "occupant_confirmed"
                        event(kind, "two_fresh_identity_receipts", seat=seat["seat"], identity=identity,
                              previous_identity=old_name, occupant_epoch=state["epoch"])
                    elif occupancy == "empty" and old_occupancy != "empty":
                        event("seat_empty", "two_fresh_vacant_receipts", seat=seat["seat"],
                              previous_identity=old_name, occupant_epoch=state["epoch"])
                    state.update(identity=identity, occupancy=occupancy)
                    qualified = True
            seat.update(identity=identity if qualified else None, occupant_epoch=state["epoch"],
                        continuity="confirmed" if qualified else "uncertain",
                        status="confirmed" if qualified else "provisional" if occupancy != "unknown" else "unknown", stats=None)
            if not qualified and candidate is not None:
                seat["reason"] = "awaiting_two_fresh_receipts" if table_current else "table_context_unconfirmed"
        current_role = value.get("role", "uncertain")
        hero = value.get("hero_seat")
        if current_role not in {"observing", "seated_waiting", "your_turn", "uncertain"}:
            raise ValueError("invalid-context-role")
        origins = {"observing": "observer_controls", "seated_waiting": "self_player", "your_turn": "own_action_controls"}
        if (current_role in origins and (role.get("origin") != origins[current_role] or
                                       role.get("status") not in {"provisional", "confirmed"})):
            current_role = "uncertain"
        if current_role in {"seated_waiting", "your_turn"}:
            if type(hero) is not int or not 1 <= hero <= 6 or not table_current or not any(
                    s["seat"] == hero and s["identity"] and s["continuity"] == "confirmed" for s in value["seats"]):
                current_role = "uncertain"
        if current_role in {"observing", "uncertain"}:
            hero = None
        value.update(role=current_role, hero_seat=hero)
        value["evidence"]["role"].update(hero_seat=hero, status="confirmed" if current_role != "uncertain" else "unknown")
        role_key = current_role, hero
        if role_key != self._role:
            event("role_change", "independent_role_evidence", role=current_role, hero_seat=hero)
            self._role = role_key
        if profile:
            owners = [s for s in value["seats"] if s["identity"] == profile.get("owner") and
                      s["seat"] == profile.get("seat") and s["continuity"] == "confirmed" and s["occupancy"] == "occupied"]
            coherent = (profile.get("source") == "client_profile_tooltip" and profile.get("status") == "provisional" and
                        len(owners) == 1 and table_current and profile.get("table_context_id") == table and
                        profile.get("title", {}).get("identity") == profile.get("owner") and
                        _name(re.sub(r"^(?:Player|Profile)\s*:\s*", "", profile.get("title", {}).get("literal", ""), flags=re.IGNORECASE)) == profile.get("owner") and
                        profile.get("occupant_epoch") in (None, owners[0]["occupant_epoch"]) and
                        isinstance(profile.get("metrics"), dict) and set(profile["metrics"]) == set(METRICS))
            if coherent:
                owner = owners[0]
                snapshot = copy.deepcopy(profile)
                snapshot.update(occupant_epoch=owner["occupant_epoch"], table_context_id=self._table)
                key = (self._table, owner["seat"], owner["occupant_epoch"], owner["identity"])
                self.profile_cache[key] = snapshot
                self.profile_cache.move_to_end(key)
                while len(self.profile_cache) > MAX_CACHE:
                    self.profile_cache.popitem(last=False)
                revision = (key, snapshot.get("revision"))
                if revision != self._profile_revision:
                    event("profile_import", "atomic_current_owner_snapshot", seat=owner["seat"],
                          identity=owner["identity"], occupant_epoch=owner["occupant_epoch"], revision=snapshot.get("revision"))
                self._profile_revision = revision
                self._profile_rejection = None
                value["profile"] = snapshot
            else:
                value["profile"] = {**profile, "status": "rejected", "reason": profile.get("reason")
                                    if profile.get("status") == "rejected" else "profile_owner_not_current_qualified_identity"}
                if profile.get("title", {}).get("identity") != profile.get("owner"):
                    value["profile"]["reason"] = "profile_title_owner_mismatch"
                rejection = (value["profile"]["reason"], json.dumps([profile.get("owner"), profile.get("metrics"), profile.get("bounds")], sort_keys=True))
                if rejection != self._profile_rejection:
                    event("profile_rejected", value["profile"]["reason"], status="rejected")
                self._profile_rejection = rejection
                self._profile_revision = None
        elif result.get("profile_rejection"):
            rejection = (result["profile_rejection"], "external_current_witness")
            if rejection != self._profile_rejection:
                event("profile_rejected", result["profile_rejection"], status="rejected")
            self._profile_rejection = rejection
            self._profile_revision = None
        elif self._profile_revision is not None and result.get("ocr", {}).get("status") == "ok":
            event("profile_closed", "retain_original_last_observed_time")
            self._profile_revision = None
        if not profile and not result.get("profile_rejection") and result.get("ocr", {}).get("status") == "ok":
            self._profile_rejection = None
        for seat in value["seats"]:
            if seat["continuity"] != "confirmed" or not seat["identity"] or not table_current:
                continue
            key = (self._table, seat["seat"], seat["occupant_epoch"], seat["identity"])
            cached_profile = self.profile_cache.get(key)
            proof = (cached_profile["capture"].get("parent_capture") or cached_profile["capture"]) if cached_profile else {}
            if cached_profile and (proof["width"], proof["height"]) == geometry:
                seat["stats"] = copy.deepcopy(cached_profile)
                if not profile or value["profile"].get("status") == "rejected" or value["profile"].get("seat") != seat["seat"]:
                    seat["stats"]["status"] = "last_observed"
        value["eventchanges"] = changes
        self.events.extend(copy.deepcopy(changes))
        self._capture, self._geometry = copy.deepcopy(capture), geometry
        self._signature = signature
        self._value = copy.deepcopy(value)
        return value

    @staticmethod
    def _rejected(result, reason):
        value = copy.deepcopy(result)
        value.update(role="uncertain", hero_seat=None, table_context_id=None, profile=None,
                     eventchanges=[], rejection=reason)
        for seat in value["seats"]:
            seat.update(occupancy="unknown", identity=None, stats=None, continuity="uncertain", status="unknown", reason=reason)
        value["evidence"]["role"].update(status="unknown", hero_seat=None, reason=reason)
        return value
