"""Synthetic continuity tests and explicitly enabled finite original OCR replay."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import laya_context as context

HAS_PIL = importlib.util.find_spec("PIL") is not None


def receipt(sequence=1, **changes):
    return {"service_instance_id": "service_a", "session_id": "feed_a", "capture_session_id": "capture_a",
            "source_id": "public_a", "native_source_id": 42, "epoch": 1, "sequence": sequence,
            "captured_at_ms": sequence * 250, "captured_at_unix_ms": 1791950000000 + sequence * 250,
            "sha256": "a" * 64, "width": 939, "height": 714, "timestamp_basis": "capture_call_start",
            **changes}


def word(text, bbox, line):
    return {"text": text, "bbox": list(bbox), "line": line}


def table_words(names=None, *, observer=False, vacant=(), caption="NLH 1554229 - 0.05/0.1"):
    names = names if names is not None else ["Alice", "Bob", "Carol", "David", "Emma", "Frank"]
    words = [word(caption, (32, 6, 230, 23), 0)] if caption is not None else []
    for index, (name, box) in enumerate(zip(names, context.NAME_BOUNDS), 1):
        if name is not None:
            words.append(word(name, (box[0] + 9, box[1] + 4, box[2] - 9, box[3] - 4), index))
        if index in vacant:
            b = context.SEAT_BOUNDS[index - 1]
            words.append(word("Empty Seat", (b[0] + 12, b[1] + 30, b[2] - 12, b[1] + 47), 20 + index))
    if observer:
        words.extend([word("Join Wait List", (642, 668, 779, 690), 40), word("Find Seat", (818, 668, 918, 690), 41)])
    return words


def profile_words(owner="Alice", literals=("12.5%", "0%", "-", "37.25%"), *, labels=None):
    labels = list(context.METRICS.values()) if labels is None else labels
    words = [word(owner, (240, 193, 315, 210), 100)] if owner is not None else []
    for index, label in enumerate(labels):
        y = 228 + index * 26
        words.append(word(label, (240, y, 291, y + 16), 101 + index))
        if index < len(literals) and literals[index] is not None:
            words.append(word(literals[index], (309, y, 368, y + 16), 101 + index))
    return words


class FakeOcr:
    def __init__(self):
        self.words, self.status, self.reason, self.calls = [], "ok", "synthetic_error", 0

    def read(self, image, regions):
        self.calls += 1
        return {"status": self.status, "reason": self.reason, "method": "synthetic_bbox_test_only",
                "words": copy.deepcopy(self.words)}


class PercentTests(unittest.TestCase):
    def test_decimal_zero_and_original_literal(self):
        for literal, expected in (("12.5%", 12.5), ("0%", 0), ("0.00%", 0), ("100%", 100), ("37.250001%", 37.250001)):
            parsed = context.parse_percent("VPIP", literal)
            self.assertEqual(parsed["percent"], expected)
            self.assertEqual(parsed["literal"], literal)
            self.assertEqual(parsed["status"], "accepted")

    def test_missing_dash_locale_range_and_unreadable_are_distinct(self):
        cases = [(None, "missing", "missing_value"), ("-", "dash", "literal_dash"),
                 ("12,5%", "invalid", "ambiguous_numeric_locale"),
                 ("101%", "invalid", "percentage_out_of_range"), ("-1%", "invalid", "percentage_out_of_range"),
                 ("12.5", "unreadable", "not_a_literal_percentage"), ("1e2%", "unreadable", "not_a_literal_percentage")]
        for literal, status, reason in cases:
            parsed = context.parse_percent("C-BET", literal)
            self.assertEqual((parsed["status"], parsed["reason"], parsed["percent"]), (status, reason, None))


@unittest.skipUnless(HAS_PIL and os.name == "nt", "Windows CPU adapter host required")
class OcrCoordinateTests(unittest.TestCase):
    def test_winrt_clockwise_overlay_rotation_before_original_mapping(self):
        response = {"status": "ok", "language": "en-US", "images": [{"id": "full", "width": 100, "height": 100,
                    "text_angle": 90, "words": [word("23%", [10, 20, 30, 40], 0)]}]}
        process = SimpleNamespace(returncode=0, stdout=json.dumps(response).encode(), stderr=b"")
        with patch.object(context.subprocess, "run", return_value=process):
            value = context.WindowsOcr(ROOT)._run_batch([{"id": "full", "png": "unused"}],
                                                       {"full": ([200, 300, 300, 400], (100, 100))}, (939, 714))
        self.assertEqual(value["words"][0]["bbox"], [260, 310, 280, 330])


@unittest.skipUnless(HAS_PIL, "Pillow is unavailable")
class ContextTests(unittest.TestCase):
    def setUp(self):
        self.ocr = FakeOcr()
        self.reader = context.ContextReader(ROOT, ocr=self.ocr)
        self.timeline = context.ContextTimeline()

    def read(self, sequence, words=None, *, image=None, reader=None, masks=(), **capture_changes):
        from PIL import Image
        if words is not None:
            self.ocr.words = words
        image = image if image is not None else Image.new("RGB", context.REFERENCE_SIZE, (14, 14, 14))
        image = image.copy()
        image.putpixel((0, 100), (sequence % 255, 14, 14))
        return (reader or self.reader).read(image, receipt(sequence, **capture_changes), occluded_regions=masks)

    def observe(self, sequence, words=None, **kwargs):
        return self.timeline.observe(self.read(sequence, words, **kwargs))

    def confirm(self, **kwargs):
        self.observe(1, table_words(), **kwargs)
        return self.observe(2, table_words(), **kwargs)

    def test_all_six_physical_seats_two_fresh_receipts(self):
        first = self.observe(1, table_words())
        self.assertEqual([s["occupancy"] for s in first["seats"]], ["occupied"] * 6)
        self.assertTrue(all(s["identity"] is None for s in first["seats"]))
        second = self.observe(2, table_words())
        self.assertEqual([s["identity"] for s in second["seats"]], ["Alice", "Bob", "Carol", "David", "Emma", "Frank"])
        self.assertEqual([s["seat"] for s in second["seats"]], list(range(1, 7)))
        self.assertTrue(all(s["occupant_epoch"] == 1 and s["continuity"] == "confirmed" for s in second["seats"]))
        self.assertFalse(second["quality_approved"])

    def test_same_receipt_cannot_confirm_or_renew(self):
        raw = self.read(1, table_words())
        first = self.timeline.observe(raw)
        repeated = self.timeline.observe(copy.deepcopy(raw))
        self.assertEqual(repeated["eventchanges"], [])
        self.assertEqual(repeated["capture"], first["capture"])
        self.assertTrue(all(s["identity"] is None for s in repeated["seats"]))
        conflict = copy.deepcopy(raw)
        conflict["seats"][0]["identity"] = "Replacement"
        self.assertEqual(self.timeline.observe(conflict)["rejection"], "old_or_conflicting_context_capture")

    def test_identical_pixels_cache_compute_not_receipt_confirmation(self):
        from PIL import Image
        self.ocr.words = table_words()
        image = Image.new("RGB", context.REFERENCE_SIZE)
        first = self.reader.read(image, receipt(1))
        second = self.reader.read(image, receipt(2))
        self.assertTrue(second["pixel_compute_reused"])
        self.assertEqual(self.ocr.calls, 1)
        self.timeline.observe(first)
        confirmed = self.timeline.observe(second)
        self.assertEqual(confirmed["seats"][0]["identity"], "Alice")
        self.assertEqual(second["capture"], receipt(2))

    def test_explicit_empty_and_folded_players_are_not_card_absence(self):
        words = table_words(["Alice", None, "Carol", "David", "Emma", "Frank"], vacant=(2,))
        words.append(word("FOLD", (60, 460, 97, 476), 51))
        self.observe(1, words)
        value = self.observe(2, words)
        self.assertEqual(value["seats"][1]["occupancy"], "empty")
        self.assertEqual(value["seats"][4]["occupancy"], "occupied")
        self.assertEqual(value["seats"][4]["participation"], "fold")
        self.assertIsNone(value["hero_seat"])

    def test_missing_name_cards_stack_and_wager_never_mean_empty(self):
        words = table_words([None] * 6)
        words.extend([word("0", (451, 173, 488, 191), 51), word("FOLD", (60, 460, 97, 476), 52)])
        value = self.observe(1, words)
        self.assertTrue(all(s["occupancy"] == "unknown" for s in value["seats"]))

    def test_numeric_ink_in_name_band_is_occupied_but_not_guessed_identity(self):
        from PIL import Image, ImageDraw
        image = Image.new("RGB", context.REFERENCE_SIZE, (20, 20, 20))
        box = context.NAME_BOUNDS[0]
        ImageDraw.Draw(image).text((box[0] + 30, box[1] + 5), "123456", fill=(120, 120, 120))
        value = self.read(1, table_words(["123456", None, None, None, None, None]), image=image)
        self.assertEqual((value["seats"][0]["occupancy"], value["seats"][0]["identity"]), ("occupied", None))
        self.assertEqual(value["seats"][0]["reason"], "numeric_name_identity_unqualified")
        self.assertTrue(all(s["occupancy"] == "unknown" for s in value["seats"][1:]))
        self.assertIsNone(value["hero_seat"])

    def test_empty_crop_ocr_falls_back_to_current_full_image_word_not_history(self):
        class EmptyCropOcr(FakeOcr):
            def read(self, image, regions):
                return {**super().read(image, regions), "regions": {"name_1": []}}
        ocr = EmptyCropOcr()
        ocr.words = table_words()
        reader = context.ContextReader(ROOT, ocr=ocr)
        value = self.read(1, reader=reader)
        self.assertEqual(value["seats"][0]["identity"], "Alice")
        ocr.words = table_words([None, "Bob", "Carol", "David", "Emma", "Frank"])
        missing = self.read(2, reader=reader)
        self.assertEqual((missing["seats"][0]["occupancy"], missing["seats"][0]["identity"]), ("unknown", None))

    def test_name_ink_excludes_plaque_border_and_colored_timer_but_detects_added_glyph(self):
        from PIL import Image, ImageDraw
        image = Image.new("RGB", context.REFERENCE_SIZE, (20, 20, 20))
        box = context.NAME_BOUNDS[0]
        draw = ImageDraw.Draw(image)
        draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), outline=(110, 110, 110))
        draw.text((box[0] + 40, box[1] + 5), "Player42", fill=(120, 120, 120))
        first = context._name_pixels(image, box)
        self.assertGreater(first["bounds"][0], box[0])
        self.assertLess(first["bounds"][2], box[2])
        changed = image.copy()
        changed.putpixel((box[0] + 3, box[1] + 3), (232, 200, 20))
        second = context._name_pixels(changed, box)
        self.assertEqual(first["ink_sha256"], second["ink_sha256"])
        self.assertEqual(context._pixel_hash(image.crop(first["bounds"])), context._pixel_hash(changed.crop(second["bounds"])))
        ImageDraw.Draw(changed).text((box[0] + 12, box[1] + 5), "X", fill=(120, 120, 120))
        self.assertNotEqual(context._name_pixels(changed, box)["ink_sha256"], first["ink_sha256"])

    def test_direct_replacement_advances_epoch_once(self):
        self.confirm()
        names = ["NewAlice", "Bob", "Carol", "David", "Emma", "Frank"]
        pending = self.observe(3, table_words(names))["seats"][0]
        self.assertEqual((pending["identity"], pending["occupant_epoch"]), (None, 1))
        replaced = self.observe(4, table_words(names))
        self.assertEqual((replaced["seats"][0]["identity"], replaced["seats"][0]["occupant_epoch"]), ("NewAlice", 2))
        self.assertEqual(sum(e["type"] == "occupant_replaced" for e in replaced["eventchanges"]), 1)
        self.assertEqual(self.observe(5, table_words(names))["seats"][0]["occupant_epoch"], 2)

    def test_departure_reoccupation_is_one_new_occupant_epoch(self):
        self.confirm()
        vacant = table_words([None, "Bob", "Carol", "David", "Emma", "Frank"], vacant=(1,))
        self.observe(3, vacant)
        empty = self.observe(4, vacant)["seats"][0]
        self.assertEqual((empty["occupancy"], empty["identity"], empty["occupant_epoch"]), ("empty", None, 1))
        self.observe(5, table_words())
        self.assertEqual(self.observe(6, table_words())["seats"][0]["occupant_epoch"], 2)

    def test_unknown_and_occlusion_preserve_epoch_but_detach_current_identity(self):
        self.confirm()
        value = self.observe(3, table_words(), masks=[context.NAME_BOUNDS[0]])
        self.assertEqual((value["seats"][0]["occupancy"], value["seats"][0]["identity"], value["seats"][0]["occupant_epoch"]), ("unknown", None, 1))
        self.observe(4, table_words())
        self.assertEqual(self.observe(5, table_words())["seats"][0]["occupant_epoch"], 1)

    def test_duplicate_truncated_clipped_overlong_identity(self):
        value = self.read(1, table_words(["Alice", "Alice", "Trunc...", "X" * 70, None, None]))
        self.assertTrue(all(s["identity"] is None for s in value["seats"]))
        self.assertEqual(value["seats"][0]["reason"], "duplicate_player_name")
        self.assertEqual(value["seats"][2]["reason"], "truncated_name")
        self.assertEqual(value["seats"][3]["reason"], "overlong_name")
        self.assertLessEqual(len(value["seats"][3]["raw_name"]), context.MAX_NAME)

    def test_ocr_failure_and_invalid_bboxes_are_unknown(self):
        self.ocr.status, self.ocr.reason = "unavailable", "windows-ocr-language-unavailable:test"
        value = self.read(1, table_words())
        self.assertEqual(value["ocr"]["reason"], self.ocr.reason)
        self.assertTrue(all(s["occupancy"] == "unknown" for s in value["seats"]))
        self.ocr.status = "ok"
        value = self.read(2, [word("Alice", (0, 0, 10000, 10000), 0)])
        self.assertEqual(value["ocr"]["status"], "unavailable")
        self.assertTrue(all(s["occupancy"] == "unknown" for s in value["seats"]))

    def test_observer_positive_controls_independent_of_board_pot(self):
        value = self.observe(1, table_words(observer=True))
        self.assertEqual((value["role"], value["hero_seat"]), ("observing", None))
        self.assertEqual(value["evidence"]["role"]["origin"], "observer_controls")
        self.assertEqual(self.observe(2, table_words())["role"], "uncertain")

    def test_role_waiting_and_enabled_own_controls_at_every_physical_seat(self):
        for hero in range(1, 7):
            for kind, expected in (("self_player", "seated_waiting"), ("own_action_controls", "your_turn")):
                names = ["Other%d" % n for n in range(1, 7)]
                names[hero - 1] = "ActualSelf"
                def own(image, capture):
                    return {"kind": kind, "enabled": True, "waiting": True,
                            "bounds": [610, 650, 790, 703], "capture": capture}
                reader = context.ContextReader(ROOT, ocr=self.ocr, self_name="ActualSelf", control_evidence=own)
                tracker = context.ContextTimeline()
                tracker.observe(self.read(1, table_words(names), reader=reader))
                value = tracker.observe(self.read(2, table_words(names), reader=reader))
                self.assertEqual((value["role"], value["hero_seat"]), (expected, hero))
                self.assertTrue(all(s["occupant_epoch"] == 1 for s in value["seats"]))

    def test_unconfigured_self_disabled_controls_and_showdown_never_assume_hero(self):
        own = lambda image, capture: {"kind": "own_action_controls", "enabled": False,
                                      "bounds": [610, 650, 790, 703], "capture": capture}
        reader = context.ContextReader(ROOT, ocr=self.ocr, self_name="Alice", control_evidence=own)
        self.assertEqual(self.read(1, table_words(), reader=reader)["role"], "uncertain")
        self.assertEqual(self.read(2, table_words())["role"], "uncertain")
        self.assertIsNone(self.read(3, table_words())["hero_seat"])

    def test_role_transition_does_not_restart_or_discard_table_history(self):
        first = self.observe(1, table_words(observer=True))
        second = self.observe(2, table_words(observer=True))
        old_table = second["table_context_id"]
        value = self.observe(3, table_words())
        self.assertEqual(value["table_context_id"], old_table)
        self.assertTrue(all(s["occupant_epoch"] == 1 for s in value["seats"]))
        self.assertNotEqual(first["role"], value["role"])
        self.assertTrue(any(e["type"] == "occupant_confirmed" for e in self.timeline.events))

    def test_table_caption_change_is_separate_from_role_and_partitions_roster(self):
        old = self.confirm()
        changed_words = table_words(observer=True, caption="NLH 9999999 - 0.05/0.1")
        candidate = self.observe(3, changed_words)
        self.assertEqual(candidate["role"], "observing")
        self.assertIsNone(candidate["table_context_id"])
        changed = self.observe(4, changed_words)
        self.assertNotEqual(changed["table_context_id"], old["table_context_id"])
        self.assertTrue(any(e["type"] == "table_context_change" for e in changed["eventchanges"]))
        self.assertEqual(len(self.timeline.profile_cache), 0)

    def test_profile_atomic_decimal_zero_dash_missing_and_closure_time(self):
        self.confirm()
        opened = self.observe(3, table_words() + profile_words(literals=("12.5%", "0%", "-", None)))
        stats = opened["seats"][0]["stats"]
        self.assertEqual(stats["source"], "client_profile_tooltip")
        self.assertEqual(set(stats["metrics"]), set(context.METRICS))
        self.assertEqual(stats["metrics"]["vpip"]["percent"], 12.5)
        self.assertEqual(stats["metrics"]["pfr"]["percent"], 0)
        self.assertEqual(stats["metrics"]["three_bet"]["status"], "dash")
        self.assertEqual(stats["metrics"]["c_bet"]["status"], "missing")
        closed = self.observe(4, table_words())["seats"][0]["stats"]
        self.assertEqual(closed["status"], "last_observed")
        self.assertEqual(closed["capture"], stats["capture"])
        self.assertEqual(closed["captured_at_unix_ms"], stats["capture"]["captured_at_unix_ms"])

    def test_new_profile_replaces_all_slots_without_old_metric_fill(self):
        self.confirm()
        self.observe(3, table_words() + profile_words())
        stats = self.observe(4, table_words() + profile_words(literals=(None, "0%", None, "-")))["seats"][0]["stats"]
        self.assertIsNone(stats["metrics"]["vpip"]["percent"])
        self.assertIsNone(stats["metrics"]["three_bet"]["percent"])
        self.assertEqual(stats["capture"]["sequence"], 4)

    def test_horizontal_labels_above_aligned_percent_words(self):
        self.confirm()
        panel = [word("Alice", [235, 180, 310, 197], 100)]
        for index, (label, literal) in enumerate(zip(context.METRICS.values(), ("23", "0", "7.5", "44"))):
            x = 235 + index * 75
            panel.append(word(label, [x, 220, x + 51, 234], 101))
            panel.append(word(literal, [x + 10, 255, x + 30, 271], 110))
            panel.append(word("%", [x + 31, 255, x + 40, 271], 110))
        stats = self.observe(3, table_words() + panel)["seats"][0]["stats"]
        self.assertIsNotNone(stats)
        self.assertEqual([m["percent"] for m in stats["metrics"].values()], [23, 0, 7.5, 44])

    def test_partial_duplicate_and_ownerless_panel_cannot_attach(self):
        self.confirm()
        for sequence, panel in enumerate((profile_words(labels=["VPIP", "PFR", "3-BET"]),
                                          profile_words(labels=["VPIP", "PFR", "3-BET", "VPIP"]),
                                          profile_words(owner=None), profile_words(owner="AbsentPlayer")), 3):
            value = self.observe(sequence, table_words() + panel)
            self.assertIsNone(value["seats"][0]["stats"])
            self.assertEqual(value["profile"]["status"], "rejected")

    def test_unchanged_rejected_panel_does_not_create_repeated_appearances(self):
        self.confirm()
        words = table_words() + profile_words(owner="AbsentPlayer")
        first = self.observe(3, words)
        second = self.observe(4, words)
        self.assertTrue(any(e["type"] == "profile_rejected" for e in first["eventchanges"]))
        self.assertFalse(any(e["type"] == "profile_rejected" for e in second["eventchanges"]))
        self.assertEqual(second["occluded_regions"], [])

    def test_unknown_detaches_stats_preserves_cache_then_replacement_fences_it(self):
        self.confirm()
        self.observe(3, table_words() + profile_words())
        unknown = table_words([None, "Bob", "Carol", "David", "Emma", "Frank"])
        self.assertIsNone(self.observe(4, unknown)["seats"][0]["stats"])
        self.assertEqual(len(self.timeline.profile_cache), 1)
        names = ["Replacement", "Bob", "Carol", "David", "Emma", "Frank"]
        self.observe(5, table_words(names))
        changed = self.observe(6, table_words(names))["seats"][0]
        self.assertEqual(changed["occupant_epoch"], 2)
        self.assertIsNone(changed["stats"])

    def test_A_to_B_delayed_result_is_rejected_without_rebinding(self):
        self.confirm()
        delayed_a = self.read(3, table_words() + profile_words("Alice"))
        self.observe(4, table_words() + profile_words("Bob", ("40%", "2%", "3%", "4%")))
        late = self.timeline.observe(delayed_a)
        self.assertEqual(late["rejection"], "old_or_conflicting_context_capture")
        self.assertTrue(all(s["stats"] is None for s in late["seats"]))
        next_value = self.observe(5, table_words())
        self.assertIsNone(next_value["seats"][0]["stats"])
        self.assertEqual(next_value["seats"][1]["stats"]["owner"], "Bob")

    def test_table_underlying_mask_does_not_mask_visible_profile(self):
        self.confirm()
        value = self.observe(3, table_words() + profile_words(), masks=[[235, 190, 380, 331]])
        self.assertEqual(value["seats"][0]["stats"]["owner"], "Alice")
        self.assertIn(value["profile"]["bounds"], value["occluded_regions"])

    def test_intermediate_source_change_tombstone_prevents_ABA_reattachment(self):
        self.confirm()
        opened = self.read(3, table_words() + profile_words())
        self.timeline.observe(opened)
        self.timeline.invalidate_fields([1], reason="intermediate-profile-cover")
        same_ticket = self.timeline.observe(copy.deepcopy(opened))
        self.assertIsNone(same_ticket["seats"][0]["identity"])
        self.assertIsNone(same_ticket["seats"][0]["stats"])
        first = self.observe(4, table_words())
        self.assertIsNone(first["seats"][0]["identity"])
        restored = self.observe(5, table_words())["seats"][0]
        self.assertEqual((restored["identity"], restored["occupant_epoch"]), ("Alice", 1))
        self.assertEqual(restored["stats"]["capture"]["sequence"], 3)

    def test_caption_ABA_requires_fresh_confirmation_without_changing_epochs(self):
        self.confirm()
        self.observe(3, table_words(caption="NLH 9999999"))
        first = self.observe(4, table_words())
        self.assertIsNone(first["table_context_id"])
        self.assertIsNone(first["seats"][0]["identity"])
        restored = self.observe(5, table_words())
        self.assertEqual(restored["seats"][0]["occupant_epoch"], 1)
        self.assertEqual(restored["seats"][0]["identity"], "Alice")

    def test_original_receipts_mutation_old_source_and_stale_result(self):
        raw = self.read(1, table_words())
        self.assertEqual(raw["capture"], receipt(1))
        self.timeline.observe(raw)
        raw["capture"]["sequence"] = 900
        self.assertEqual(self.timeline._capture["sequence"], 1)
        self.observe(2, table_words(), source_id="new_source")
        self.assertEqual(self.timeline.observe(self.read(3, table_words()))["rejection"], "retired_context_source")
        stale = self.read(4, table_words(), source_id="new_source")
        self.assertEqual(self.timeline.observe(stale, now_ms=stale["capture"]["captured_at_ms"] + 5000)["rejection"], "stale_context_capture")

    def test_capture_gap_needs_two_new_receipts_without_epoch_bump(self):
        self.confirm()
        gap = self.observe(30, table_words())
        self.assertTrue(any(e["type"] == "capture_gap" for e in gap["eventchanges"]))
        self.assertIsNone(gap["seats"][0]["identity"])
        self.assertEqual(self.observe(31, table_words())["seats"][0]["occupant_epoch"], 1)

    def test_invalid_receipt_seat_or_foreign_field_source_rejected_before_mutation(self):
        raw = self.read(1, table_words())
        raw["seats"][0]["capture"]["source_id"] = "foreign"
        with self.assertRaisesRegex(ValueError, "receipt-mismatch"):
            self.timeline.observe(raw)
        self.assertEqual(len(self.timeline.events), 0)
        for field, bad in (("sha256", "bad"), ("width", 1)):
            with self.assertRaises(ValueError):
                self.read(1, table_words(), **{field: bad})
        with self.assertRaises(ValueError):
            self.read(0, table_words())

    def test_popup_preserves_separate_receipt_and_rejects_foreign_parent(self):
        from PIL import Image
        self.confirm()
        raw = self.read(3, table_words())
        child = {**receipt(3), "parent_capture": copy.deepcopy(raw["capture"]), "non_atomic": True,
                 "width": 420, "height": 380, "sha256": "b" * 64,
                 "captured_at_ms": raw["capture"]["captured_at_ms"] + 2,
                 "captured_at_unix_ms": raw["capture"]["captured_at_unix_ms"] + 2,
                 "popup_index": 0, "popup_window": {"hwnd": 456}}
        self.ocr.words = profile_words()
        raw["profile"] = self.reader.read_popup(Image.new("RGB", (420, 380)), child, raw["seats"])
        value = self.timeline.observe(raw)
        stats = value["seats"][0]["stats"]
        self.assertIsNotNone(stats)
        self.assertEqual(stats["capture"], child)
        closed = self.observe(4, table_words())["seats"][0]["stats"]
        self.assertEqual(closed["capture"], child)
        foreign = {**child, "source_id": "foreign"}
        with self.assertRaisesRegex(ValueError, "parent-receipt"):
            self.reader.read_popup(Image.new("RGB", (420, 380)), foreign, raw["seats"])

    def test_default_self_identity_and_enabled_pixel_reference_producer(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".local/laya").mkdir(parents=True)
            bounds = [610, 650, 675, 693]
            image = Image.new("RGB", context.REFERENCE_SIZE, (14, 14, 14))
            crop = image.crop(bounds)
            target = root / ".local/laya/control.png"
            crop.save(target)
            settings = {"display_name": "Alice", "control_references": [{"kind": "own_action_controls", "label": "Fold",
                        "bounds": bounds, "frame_dimensions": list(image.size), "path": ".local/laya/control.png",
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}]}
            (root / ".local/laya/self-player.json").write_text(json.dumps(settings), encoding="utf-8")
            reader = context.ContextReader(root, ocr=self.ocr)
            words = table_words() + [word("Fold", [617, 660, 665, 677], 120)]
            self.assertEqual(self.read(1, words, reader=reader, image=image)["role"], "your_turn")
            image.putpixel((620, 660), (200, 200, 200))
            self.assertEqual(self.read(2, words, reader=reader, image=image)["role"], "uncertain")


@unittest.skipUnless(HAS_PIL and os.name == "nt" and os.environ.get("LAYA_CONTEXT_PRIVATE_REPLAY_PROOF") == "1",
                     "explicit finite Windows original replay is not enabled")
class OriginalOcrReplay(unittest.TestCase):
    def test_windows_builtin_reads_original_without_accuracy_qualification(self):
        from PIL import Image
        path = ROOT / context.GEOMETRY_SOURCE["path"]
        png = path.read_bytes()
        self.assertEqual(hashlib.sha256(png).hexdigest(), context.GEOMETRY_SOURCE["sha256"])
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        original = receipt(177, session_id="finite_replay", capture_session_id="utc_1791942831_290126500_practice",
                           source_id="finite_original_replay", native_source_id=3613075657761702206,
                           captured_at_ms=100590, captured_at_unix_ms=1791942931880,
                           sha256=context.GEOMETRY_SOURCE["sha256"])
        value = context.ContextReader(ROOT).read(image, original)
        self.assertEqual(value["ocr"]["status"], "ok", value["ocr"])
        self.assertEqual(value["capture"], original)
        self.assertEqual((value["role"], value["hero_seat"]), ("observing", None))
        self.assertEqual(len(value["seats"]), 6)
        self.assertFalse(value["quality_approved"])
        self.assertIsNone(value["profile"])
        print(json.dumps({"finite_original_cpu_replay": {"sha256": original["sha256"], "sequence": 177,
              "ocr": value["ocr"], "processing_ms": value["processing_ms"], "role": value["role"],
              "seats": [{k: s[k] for k in ("seat", "occupancy", "identity", "reason")} for s in value["seats"]],
              "accuracy_qualification": False, "genuine_tooltip": "NOT_AVAILABLE"}}, ensure_ascii=True))


@unittest.skipUnless(HAS_PIL and os.name == "nt" and os.environ.get("LAYA_CONTEXT_PRIVATE_PROFILE_PROOF") == "1",
                     "explicit saved genuine-profile Windows replay is not enabled")
class GenuineProfileReplay(unittest.TestCase):
    SHA = "25a9ed1a28dd3d3c613e1c49af0095f21ea260c3674e86211cd8346cbfdc1b52"
    DIRECTORY = ROOT / ".local/captures/utc-1791952251-581261300-practice"

    @classmethod
    def setUpClass(cls):
        from PIL import Image
        png = (cls.DIRECTORY / "frame-0000000001.png").read_bytes()
        if len(png) != 723011 or hashlib.sha256(png).hexdigest() != cls.SHA:
            raise AssertionError("genuine-profile-original-source-hash-or-size-mismatch")
        cls.intake = json.loads((cls.DIRECTORY / "intake.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((cls.DIRECTORY / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0])
        with Image.open(cls.DIRECTORY / "frame-0000000001.png") as opened:
            cls.image = opened.convert("RGB")
        cls.reader = context.ContextReader(ROOT)
        cls.raw_first = cls.reader.read(cls.image, cls.logic_receipt(1))
        cls.raw_second = cls.reader.read(cls.image, cls.logic_receipt(2))

    @classmethod
    def logic_receipt(cls, sequence):
        original = cls.intake["original_capture"]
        return receipt(sequence, service_instance_id="finite_saved_profile_logic", session_id="synthetic_logic_replay",
                       capture_session_id="standalone_intake", source_id="saved_genuine_profile",
                       native_source_id=original["native_source_id"], sha256=cls.SHA,
                       captured_at_ms=original["captured_at_monotonic_ms"] + (sequence - 1) * 250,
                       captured_at_unix_ms=original["source_utc_unix_ms"] + (sequence - 1) * 250,
                       original_capture=copy.deepcopy(original),
                       monotonic_clock_origin="synthetic_logic_replay_not_intake_or_monitor",
                       original_monotonic_clock_origin=cls.intake["monotonic_clock_origin"],
                       replay_kind="TWO_DISTINCT_SYNTHETIC_LOGIC_RECEIPTS_NOT_LIVE",
                       synthetic_receipt_clocks=True)

    def test_actual_owner_labels_literals_edges_and_logic_binding(self):
        self.assertEqual(self.manifest["sha256"], self.SHA)
        self.assertEqual(self.manifest["source_utc_unix_ms"], 1791952251555)
        self.assertEqual(self.manifest["captured_at_monotonic_ms"], 39)
        self.assertEqual(self.intake["monotonic_clock_origin"], "standalone_intake_test_process_local_Instant")
        profile = self.raw_first["profile"]
        self.assertEqual((profile["status"], profile["owner"], profile["seat"]), ("provisional", "BluffMi", 4))
        self.assertNotEqual(profile["owner"], "AV4T4R365")
        self.assertEqual(profile["title"]["literal"], "BluffMi")
        for key, label, literal, percent in (("vpip", "VPIP", "23%", 23), ("pfr", "PFR", "19%", 19),
                                            ("three_bet", "3-BET", "10%", 10), ("c_bet", "C-BET", "66%", 66)):
            self.assertEqual({k: profile["metrics"][key][k] for k in ("label", "literal", "percent", "status")},
                             {"label": label, "literal": literal, "percent": percent, "status": "accepted"})
        self.assertEqual(profile["bounds"], [294, 295, 645, 525])
        self.assertTrue(profile["panel_geometry_qualified"])
        self.assertEqual(profile["bounds_kind"], "pixel_verified_panel_border")
        self.assertTrue(all(ratio >= 0.7 for ratio in profile["geometry"]["edge_support"].values()))
        self.assertIn(profile["bounds"], self.raw_first["occluded_regions"])
        self.assertLess(profile["bounds"][0], profile["content_bounds"][0])
        self.assertGreater(profile["bounds"][3], profile["content_bounds"][3])
        self.assertIsNone(profile["sample_size"])
        self.assertIsNone(profile["scope"])
        self.assertEqual((self.raw_first["role"], self.raw_first["hero_seat"]), ("observing", None))
        tracker = context.ContextTimeline()
        first = tracker.observe(copy.deepcopy(self.raw_first))
        second = tracker.observe(copy.deepcopy(self.raw_second))
        self.assertIsNone(first["seats"][3]["stats"])
        self.assertEqual((second["seats"][3]["identity"], second["seats"][3]["occupant_epoch"]), ("BluffMi", 1))
        self.assertEqual(second["seats"][3]["stats"]["metrics"], profile["metrics"])
        self.assertTrue(self.raw_second["pixel_compute_reused"])
        self.assertTrue(second["capture"]["synthetic_receipt_clocks"])
        self.assertEqual(second["capture"]["original_capture"]["captured_at_monotonic_ms"], 39)
        self.assertEqual(second["capture"]["original_capture"]["source_utc_unix_ms"], 1791952251555)
        print(json.dumps({"genuine_saved_profile_fixture": {"sha256": self.SHA, "actual_owner": profile["owner"],
              "actual_metrics": profile["metrics"], "full_mask": profile["bounds"],
              "original_utc": 1791952251555, "original_intake_monotonic_ms": 39,
              "processing_ms": [self.raw_first["processing_ms"], self.raw_second["processing_ms"]],
              "two_receipts": "SYNTHETIC_LOGIC_REPLAY_ONLY", "live_confirmation": False,
              "broad_accuracy_qualification": False}}, ensure_ascii=True))

    def test_wrong_owner_metadata_and_delayed_source_cannot_bind_to_other_seat(self):
        tracker = context.ContextTimeline()
        tracker.observe(copy.deepcopy(self.raw_first))
        tracker.observe(copy.deepcopy(self.raw_second))
        bad = self.reader.read(self.image, self.logic_receipt(3))
        bad["profile"].update(owner="AV4T4R365", seat=5)
        wrong = tracker.observe(bad)
        self.assertEqual(wrong["profile"]["reason"], "profile_title_owner_mismatch")
        self.assertIsNone(wrong["seats"][4]["stats"])
        late = tracker.observe(copy.deepcopy(self.raw_first))
        self.assertEqual(late["rejection"], "old_or_conflicting_context_capture")
        self.assertTrue(all(s["stats"] is None for s in late["seats"]))

    def test_unchanged_roi_computation_reused_after_forced_full_scan(self):
        self.reader._pixels = None
        result = self.reader.read(self.image, self.logic_receipt(4))
        self.assertEqual(result["profile"]["metrics"], self.raw_first["profile"]["metrics"])
        self.assertEqual(len(self.reader._computed.get("region_compute_reused", [])), 8)
        self.assertEqual(result["capture"]["sequence"], 4)
        self.assertLess(result["processing_ms"], context.MAX_AGE_MS)
        print(json.dumps({"genuine_roi_cache_finite_timing": {"processing_ms": result["processing_ms"],
              "eight_text_rois_reused": True, "panel_value_pixels_reused": True,
              "live_under_load_performance": "NOT_QUALIFIED"}}, ensure_ascii=True))


@unittest.skipUnless(HAS_PIL and os.name == "nt" and os.environ.get("LAYA_CONTEXT_PRIVATE_RELOAD_PROOF") == "1",
                     "explicit archived 927x705 name replay is not enabled")
class ReloadNameReplay(unittest.TestCase):
    DIRECTORY = ROOT / ".local/captures/utc-1792003095-224479100-practice"
    EXPECTED = ["CKNA", "FoldEV", "motionless15324", "wqoue", "deadshotxxzz", "rukas"]
    SHA = {1: "bb0f781f151fdccacab2a8c1f4980bf7f9718b93df62cc26b4b82920131e1358",
           2: "9b8d0cb535602f7946f981ddbe4ef8e1fbbf467d0fc3f2ffbb63e1d603b3dfa5",
           3: "a50bea614a9912b5745399cd0d989ebb533ab3de3b71b17214efc30cac4b0e49",
           504: "3b25128e9f14b2a103e72f9b1c12af953c228a6ada7df23336495accc33679d2",
           505: "2011e519bf4c31794bb47180be7515d4c2812c4031663637fedd7d2d19b94252"}

    @classmethod
    def setUpClass(cls):
        from PIL import Image
        manifest = [json.loads(line) for line in (cls.DIRECTORY / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
        cls.results, cls.images, cls.observed = [], [], []
        reader, tracker = context.ContextReader(ROOT), context.ContextTimeline()
        for row in [*manifest[:3], *manifest[503:505]]:
            sequence = row["frame_index"]
            path = cls.DIRECTORY / ("frame-%010d.png" % sequence)
            png = path.read_bytes()
            if hashlib.sha256(png).hexdigest() != cls.SHA[sequence] or row["sha256"] != cls.SHA[sequence] or len(png) != row["png_bytes"]:
                raise AssertionError("reload-original-hash-size-mismatch")
            with Image.open(path) as opened:
                image = opened.convert("RGB")
            cap = receipt(sequence, session_id="fe530937b2d741d3bb8819bc36373f00", service_instance_id="finite_archived_reload",
                          capture_session_id="utc_1792003095_224479100_practice", source_id="archived_reload_source",
                          native_source_id=str(row["source_id"]), width=row["width"], height=row["height"],
                          captured_at_ms=row["captured_at_monotonic_ms"], captured_at_unix_ms=row["source_utc_unix_ms"],
                          sha256=row["sha256"], timestamp_basis=row["timestamp_basis"],
                          replay_kind="THREE_ACTUAL_ARCHIVED_CAPTURES_NOT_LIVE")
            result = reader.read(image, cap)
            cls.results.append(result)
            cls.images.append(image)
            cls.observed.append(tracker.observe(result))

    def test_actual_first_three_frames_exact_readable_names_and_original_clocks(self):
        for result in self.results[:3]:
            self.assertEqual([s["identity"] for s in result["seats"]], self.EXPECTED)
            self.assertEqual([s["occupancy"] for s in result["seats"]], ["occupied"] * 6)
            self.assertEqual((result["role"], result["hero_seat"]), ("observing", None))
            self.assertIsNone(result["profile"])
        self.assertTrue(all(s["identity"] is None for s in self.observed[0]["seats"]))
        for observed in self.observed[1:3]:
            self.assertEqual([s["identity"] for s in observed["seats"]], self.EXPECTED)
            self.assertTrue(all(s["occupant_epoch"] == 1 for s in observed["seats"]))
        self.assertEqual([r["capture"]["captured_at_unix_ms"] for r in self.results[:3]],
                         [1792003095328, 1792003095867, 1792003096428])
        self.assertEqual([r["capture"]["captured_at_ms"] for r in self.results[:3]], [104, 644, 1205])
        print(json.dumps({"reload_actual_name_replay": {"original_sha256": self.SHA, "names": self.EXPECTED,
              "processing_ms": [r["processing_ms"] for r in self.results],
              "bounds": [[s["bounds"] for s in r["seats"]] for r in self.results],
              "three_actual_originals": True, "current_live_confirmation": False}}, ensure_ascii=True))

    def test_tight_name_bounds_stable_and_exclude_nontext_margin_changes(self):
        from PIL import ImageDraw
        for result in self.results:
            for seat in result["seats"]:
                b, search = seat["bounds"], seat["name_search_bounds"]
                self.assertEqual(seat["bounds_kind"], "name_text_pixels")
                self.assertLess((b[2] - b[0]) * (b[3] - b[1]), (search[2] - search[0]) * (search[3] - search[1]) * 0.6)
        for number in range(6):
            self.assertEqual([r["seats"][number]["bounds"] for r in self.results[:3]],
                             [self.results[0]["seats"][number]["bounds"]] * 3)
        for seat in self.results[0]["seats"]:
            b, search = seat["bounds"], seat["name_search_bounds"]
            image = self.images[0]
            point = next((x, y) for x in range(search[0] + 1, search[2] - 1) for y in range(search[1] + 1, search[3] - 1)
                         if not b[0] <= x < b[2] or not b[1] <= y < b[3] if min(image.getpixel((x, y))) < 70)
            changed = image.copy()
            ImageDraw.Draw(changed).point(point, fill=(230, 170, 20))
            self.assertNotEqual(context._pixel_hash(image.crop(search)), context._pixel_hash(changed.crop(search)))
            self.assertEqual(context._pixel_hash(image.crop(b)), context._pixel_hash(changed.crop(b)))
            self.assertEqual(context._name_pixels(image, search)["ink_sha256"], context._name_pixels(changed, search)["ink_sha256"])

    def test_actual_tail_replacement_is_not_whitelisted_to_initial_name(self):
        expected = [*self.EXPECTED[:4], "chyori", self.EXPECTED[5]]
        for raw in self.results[3:]:
            self.assertEqual([s["identity"] for s in raw["seats"]], expected)
            self.assertEqual(raw["seats"][4]["occupancy"], "occupied")
        self.assertIsNone(self.observed[3]["seats"][4]["identity"])
        replacement = self.observed[4]["seats"][4]
        self.assertEqual((replacement["identity"], replacement["occupant_epoch"]), ("chyori", 2))
        self.assertEqual(self.results[-1]["capture"]["captured_at_unix_ms"], 1792003380418)
        self.assertEqual(self.results[-1]["capture"]["captured_at_ms"], 285195)


if __name__ == "__main__":
    unittest.main()
