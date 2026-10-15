"""Private, bounded Rust-feed projections for the loopback dashboard."""

import copy
import datetime as dt
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import threading
import time
import uuid

from laya_attach import DEFAULT_PROFILE, PracticeAttachment
import laya_capture as manual_capture

ROOT = Path(__file__).resolve().parent.parent
PORT = 18090
MAX_RECORD = 256 * 1024
MAX_EVENTS = 10_000
MAX_LEDGER_BYTES = 25 * 1024 * 1024
HEARTBEAT_MS = 2_500
RECORDING_STATES = ("disabled", "active", "count_limit", "disk_limit", "duration_limit", "io_failure")
RECORD_MAX_FRAMES = 7200
RECORD_MAX_BYTES = 1024 * 1024 * 1024
RECORD_INTERVAL_MS = 500
MAX_DIAGNOSTICS = 200
MAX_DIAGNOSTIC_BYTES = 1024 * 1024
ACTIONS = ("fold", "check", "call", "bet", "raise", "all_in")
NATIVE_ACTIONS = ("fold", "check", "call", "raise", "allin")
METRIC_FIELDS = ("hand_rank", "pot_odds", "draw", "equity_pct")
HAND_RANKS = ("High Card", "One Pair", "Two Pair", "Three of a Kind", "Straight",
              "Flush", "Full House", "Four of a Kind", "Straight Flush")
ROLES = ("observing", "seated_waiting", "your_turn", "uncertain")
VERIFIED_FIELDS = ("hero_seated", "action_required", "controls", "pot_size", "to_call",
                   "hero_chips", "min_raise_to", "max_raise_to", "acting_seat",
                   "acting_to_call", "wagers", "hero_seat")
PARTIAL_FIELDS = ("role", "hero_seated", "game_phase", "board_count", "pot_size",
                   *("board_slots." + str(n) for n in range(1, 6)),
                   *("seats." + str(n) + ".displayed_stack" for n in range(1, 7)),
                   *("seats." + str(n) + ".visible_wager" for n in range(1, 7)),
                    *("seats." + str(n) + "." + field for n in range(1, 7)
                      for field in ("occupied", "status", "badge", "dealer", "small_blind", "big_blind", "acting")))
READOUT_FIELDS = ("game_phase", "board_count", "pot_size",
                  *("board_slots." + str(n) for n in range(1, 6)),
                  *("seats." + str(n) + ".displayed_stack" for n in range(1, 7)))
SCENE_LABELS = {"occupied": ["occupied", "open", "unknown"],
                "status": ["active", "folded", "all_in", "sitting_out", "unknown"],
                "badge": ["none", "fold", "check", "call", "bet", "raise", "all_in", "small_blind", "big_blind", "unknown"],
                "dealer": ["dealer_here", "not_dealer", "unknown"],
                "small_blind": ["small_blind_here", "not_small_blind", "unknown"],
                "big_blind": ["big_blind_here", "not_big_blind", "unknown"], "acting": ["yes", "no", "unknown"]}
SEAT_FIELDS = ("occupied", "status", "displayed_stack", "visible_wager", "street_contribution",
               "dealer", "small_blind", "big_blind", "position", "position_group", "badge",
               "acting", "occupant_epoch")
CAPABILITY_FIELDS = ("role", "hero_seated", "game_phase", "board_count", "board_slot", "pot_size",
                     *SEAT_FIELDS)
DIAGNOSTIC_REASONS = ("accepted", "missing-answer", "below-floor", "truncated", "invalid-answer",
                      "invalid-floor", "dependency-unknown", "dependency-rejected", "non-table",
                      "lobby-geometry", "crop-too-small", "unsupported", "missing-segments",
                      "empty-segmentation", "segmentation-overflow", "invalid-amount",
                      "board-presence-unknown", "board-noncontiguous", "board-count-invalid",
                      "phase-board-mismatch", "duplicate-card", "role-contradiction",
                       "pass-unavailable", "awaiting-consensus", "invalid-capability", "unapproved-capability",
                       "identity-mismatch", "decision-deadline", "source-region-changed", "missing-source-witness",
                       "unknown-region", "explicit-unknown", "scene-contradiction", "occluded")
UNAVAILABLE_REASONS = ("missing-capability", "unsupported-layout", "below-floor", "stale",
                       "occluded", "insufficient-context")
FIELD_PATHS = tuple(dict.fromkeys((*PARTIAL_FIELDS, *VERIFIED_FIELDS, "hero_cards", "board", "scene",
                                  "center_chip", "pot_convention",
                                  *("seats." + str(n) + "." + field for n in range(1, 7) for field in SEAT_FIELDS))))
TRAINED_PATHS = ("role", "hero_seated", "game_phase", "board_count", "board", "pot_size",
                 *("board_slots." + str(n) for n in range(1, 6)),
                 *("seats." + str(n) + ".displayed_stack" for n in range(1, 7)), "pot_convention")
CODE = re.compile(r"^[a-z0-9_-]{1,80}$")
RANKS = dict(zip(("two", "three", "four", "five", "six", "seven", "eight", "nine",
                  "ten", "jack", "queen", "king", "ace"),
                 ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")))
SUITS = ("spades", "hearts", "diamonds", "clubs")
EXPERIMENTAL_BOUNDS = {
    "wager": ((315, 172, 387, 232), (567, 199, 734, 311), (576, 376, 743, 496),
              (409, 422, 594, 506), (157, 376, 333, 496), (157, 199, 333, 311)),
    "scene": ((360, 44, 558, 200), (666, 93, 882, 272), (684, 350, 891, 555),
              (342, 478, 558, 680), (9, 350, 225, 555), (18, 93, 234, 272))}
EXPERIMENTAL_GEOMETRY = ".local/laya/datasets/observing-20261010-v2-staging/human-review-20261010/crop-geometry.json#F001"
EXPERIMENTAL_MARKERS = {"diagnostic_only": True, "training": "unvalidated",
                        "geometry_status": "DRAFT", "human_review": "PENDING"}


def integer(value, maximum=9_007_199_254_740_991):
    return value if type(value) is int and 0 <= value <= maximum else None


def finite(value, minimum=0, maximum=100):
    return value if type(value) in (int, float) and minimum <= value <= maximum and math.isfinite(value) else None


def native_analysis_inputs(record, view):
    """Check the full native DTO, not a partial/legacy reading or a quality assertion.

    The owned native feed emits Observation only after parser/consensus admission.
    This validates its public subset; it does not certify the perception model.
    """
    fields = {"game_phase", "hero_cards", "board", "role", "hero_seated", "acting_seat",
              "pot_size", "to_call", "acting_to_call", "hero_chips", "min_raise_to", "max_raise_to",
              "available_actions", "controls", "action_required", "wagers", "metrics",
              "verified_fields", "quality_approved"}
    if (not fields.issubset(record) or "capabilities" in record or "board_slots" in record
            or "experimental" in record or type(record["quality_approved"]) is not bool
            or not isinstance(record["metrics"], dict) or set(record["metrics"]) != set(METRIC_FIELDS)
            or view["role"] == "uncertain" or not isinstance(record["controls"], list)
            or len(record["controls"]) != len(ACTIONS)
            or record["controls"] != view["controls"]
            or record["acting_seat"] != view["acting_seat"]
            or record["acting_seat"] is not None and integer(record["acting_seat"], 6) in (None, 0)
            or not isinstance(record["wagers"], list) or record["wagers"] != view["wagers"]
            or any(item["amount"] is not None and integer(item["amount"], 0xffffffff) is None for item in view["wagers"])):
        return False
    if any(set(card) != {"rank", "suit"} or card["rank"] not in ("2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A")
           for card in record["hero_cards"] + record["board"]):
        return False
    verified = record["verified_fields"]
    if (not isinstance(verified, list) or any(not isinstance(field, str) or field not in VERIFIED_FIELDS for field in verified)
            or len(set(verified)) != len(verified)
            or not {"pot_size", "hero_seated", "action_required"}.issubset(verified)):
        return False
    for field, value in view["amounts"].items():
        if record[field] is not None and (integer(record[field], 0xffffffff) is None or record[field] != value):
            return False
    if view["amounts"]["pot_size"] is None:
        return False
    actions = record["available_actions"]
    if view["role"] != "your_turn":
        return actions is None and all(item["enabled"] == "unknown" for item in view["controls"])
    if (not {"controls", "hero_chips", "to_call"}.issubset(verified)
            or not isinstance(actions, list) or not actions or any(action not in NATIVE_ACTIONS for action in actions)
            or len(set(actions)) != len(actions)
            or set("all_in" if action == "allin" else action for action in actions) != set(view["available_actions"])):
        return False
    pot, cost, stack = (view["amounts"][field] for field in ("pot_size", "to_call", "hero_chips"))
    if not pot or not stack or cost is None:
        return False
    if cost == 0:
        if "check" not in actions or "call" in actions or "fold" in actions:
            return False
    elif "fold" not in actions or "check" in actions or not ("call" in actions or "allin" in actions and stack <= cost):
        return False
    if "raise" in actions:
        low, high = view["amounts"]["min_raise_to"], view["amounts"]["max_raise_to"]
        if (not {"min_raise_to", "max_raise_to"}.issubset(verified)
                or low is None or high is None or not cost < low <= high):
            return False
    return True


def observation_metrics(raw, view):
    result = dict.fromkeys(METRIC_FIELDS)
    hero = view["hero_seated"] is True and len(view["hero_cards"]) == 2
    if hero:
        rank = raw.get("hand_rank")
        result["hand_rank"] = rank if isinstance(rank, str) and rank in HAND_RANKS and view["board"] else None
        result["equity_pct"] = finite(raw.get("equity_pct"))
        draw = raw.get("draw")
        unseen = 52 - 2 - len(view["board"])
        if isinstance(draw, dict) and view["game_phase"] in ("flop", "turn"):
            outs = integer(draw.get("outs"), unseen)
            next_card, river = finite(draw.get("next_card_pct")), finite(draw.get("by_river_pct"))
            if outs is not None and next_card is not None and river is not None and next_card <= river:
                result["draw"] = {"outs": outs, "next_card_pct": next_card, "by_river_pct": river}
    odds = raw.get("pot_odds")
    seat = view["acting_seat"] if view["role"] == "observing" else view["hero_seat"]
    cost = view["amounts"]["acting_to_call" if view["role"] == "observing" else "to_call"]
    pot = view["amounts"]["pot_size"]
    if hero and cost is not None and view["amounts"]["hero_chips"] is not None:
        cost = min(cost, view["amounts"]["hero_chips"])
    if (isinstance(odds, dict) and "seat" in odds and odds["seat"] == seat
            and (odds["seat"] is None or integer(odds["seat"], 6) not in (None, 0))
            and (view["role"] == "your_turn" or view["role"] == "observing" and seat is not None)
            and pot is not None and cost is not None and cost > 0):
        pct = finite(odds.get("required_equity_pct"))
        if pct is not None and math.isclose(pct, 100 * cost / (pot + cost), rel_tol=1e-6, abs_tol=1e-6):
            result["pot_odds"] = {"seat": seat, "required_equity_pct": pct}
    return result


def code(value, fallback="source-status"):
    return value if isinstance(value, str) and CODE.fullmatch(value) else fallback


def local_path(value, directory=".local"):
    if not isinstance(value, (str, Path)):
        raise ValueError("invalid private path")
    raw = str(value)
    windows = PureWindowsPath(raw)
    reserved = {"CON", "PRN", "AUX", "NUL", *("COM" + str(n) for n in range(1, 10)),
                *("LPT" + str(n) for n in range(1, 10))}
    if (not raw or len(raw) > 4096 or ".." in windows.parts
            or ":" in raw[len(windows.drive):] or raw.startswith(("\\\\?\\", "\\\\.\\"))
            or windows.drive and not windows.is_absolute()
            or any(ord(c) < 32 or ord(c) == 127 or 0xd800 <= ord(c) <= 0xdfff for c in raw)
            or any(part.endswith((".", " ")) or part.split(".", 1)[0].upper() in reserved
                   for part in windows.parts if part != windows.anchor)):
        raise ValueError("invalid private path")
    root = ROOT.resolve()
    base = root / directory
    supplied = root / value
    path = supplied.resolve()
    if base.resolve() != base or path != supplied or not path.is_relative_to(base) or path == base:
        raise ValueError("private path must remain under " + directory)
    return path


def cards(values, maximum):
    if not isinstance(values, list) or len(values) > maximum:
        raise ValueError("invalid cards")
    result = []
    for card in values:
        if not isinstance(card, dict):
            raise ValueError("invalid card")
        rank = card.get("rank")
        if not isinstance(rank, str):
            raise ValueError("invalid card")
        rank = RANKS.get(rank, rank)
        if rank == "T":
            rank = "10"
        suit = card.get("suit")
        if rank not in RANKS.values() or suit not in SUITS:
            raise ValueError("invalid card")
        result.append({"rank": rank, "suit": suit})
    return result


def unknown_controls():
    return [{"action": action, "presence": "unknown", "enabled": "unknown"} for action in ACTIONS]


def amount_text(value, amount):
    """Keep only literal numeric glyphs that agree exactly with the hundredths value."""
    if (amount is None or not isinstance(value, str) or not 1 <= len(value) <= 32
            or re.fullmatch(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?", value) is None):
        return None
    whole, _, fraction = value.replace(",", "").partition(".")
    return value if int(whole) * 100 + int(fraction.ljust(2, "0")) == amount else None


def field_statuses(values=None, supported=TRAINED_PATHS, reason="insufficient-context"):
    values = values or {}
    return {path: {"status": "accepted", "reason": None} if values.get(path) is not None
            else {"status": "unavailable", "reason": reason if path in supported else "missing-capability"}
            for path in FIELD_PATHS}


def unavailable_reason(reason, field=None):
    if reason in UNAVAILABLE_REASONS:
        return reason
    if reason in ("non-table", "lobby-geometry", "crop-too-small", "unknown-region"):
        return "unsupported-layout"
    if reason in ("unsupported", "unapproved-capability", "invalid-capability", "invalid-floor"):
        return "unsupported-layout" if field == "table_layout" else "missing-capability"
    if reason in ("decision-deadline", "source-region-changed", "missing-source-witness",
                  "identity-mismatch", "frame-changed", "feed-eof", "feed-read-failed",
                  "invalid-feed-record", "capture-identity-or-epoch-changed", "capture-not-fresh",
                  "obsolete-health-record", "obsolete-or-expired-partial", "obsolete-or-expired-observation",
                  "partial-observation-expired", "observation-expired", "capture-heartbeat-expired"):
        return "stale"
    return "insufficient-context"


def partial_view(record, *, readout_only=False):
    """Admit only the native Stage 2 allowlist; unsupported crops are never grants."""
    raw_verified = record.get("verified_fields")
    verified = (set(raw_verified) if isinstance(raw_verified, list) and len(raw_verified) <= len(PARTIAL_FIELDS)
                and all(isinstance(v, str) and v in PARTIAL_FIELDS for v in raw_verified) else set())
    if readout_only:
        verified.intersection_update(READOUT_FIELDS)
    capabilities = {}
    raw_capabilities = record.get("capabilities")
    if isinstance(raw_capabilities, list) and len(raw_capabilities) <= 96:
        for item in raw_capabilities:
            if not isinstance(item, dict):
                continue
            field, seat = item.get("field"), item.get("seat")
            if field not in CAPABILITY_FIELDS or (field in SEAT_FIELDS and not integer(seat, 6)
                                                or field not in SEAT_FIELDS and seat is not None):
                continue
            key = (field, seat)
            floor = item.get("acceptance_floor")
            minimum = {"role": .995, "hero_seated": .995, "game_phase": .995,
                       "board_count": 1.0, "board_slot": 1.0, "pot_size": .8,
                       "displayed_stack": .8}.get(field)
            valid = (item.get("training") == "trained_unapproved"
                     and minimum is not None and type(floor) in (int, float)
                     and minimum <= floor <= 1 and math.isfinite(floor)
                     and item.get("held_out_approved") is False and item.get("human_verified") is False
                      and item.get("provenance") == "it1-existing-pass")
            if field == "visible_wager" or field in SCENE_LABELS:
                valid = (item.get("training") == "read_only_approved"
                         and type(floor) in (int, float) and 0 < floor <= 1 and math.isfinite(floor)
                         and item.get("held_out_approved") is True and item.get("human_verified") is True
                         and item.get("provenance") == "observation-only-calibrated-pass")
            # Duplicate metadata cannot turn an unsupported or conflicting family on.
            capabilities[key] = valid if key not in capabilities else False

    def admitted(path, family, seat=None):
        return path in verified and capabilities.get((family, seat)) is True

    seated = record.get("hero_seated") if admitted("hero_seated", "hero_seated") else None
    seated = seated if type(seated) is bool else None
    role = record.get("role") if admitted("role", "role") else None
    # Partial evidence contains no offered-control/turn proof. It never creates a turn.
    role = role if role == "observing" and seated is False else "uncertain"
    phase = record.get("game_phase") if admitted("game_phase", "game_phase") else None
    phase = phase if isinstance(phase, str) and phase in ("preflop", "flop", "turn", "river", "showdown") else None
    board_count = integer(record.get("board_count"), 5) if admitted("board_count", "board_count") else None
    board_count = board_count if board_count in (0, 3, 4, 5) else None
    board = [None] * 5
    raw_board = record.get("board_slots")
    if isinstance(raw_board, list) and len(raw_board) == 5:
        for index, value in enumerate(raw_board):
            if value is not None and admitted("board_slots." + str(index + 1), "board_slot"):
                try:
                    board[index] = cards([value], 1)[0]
                except ValueError:
                    pass
    for card in board:
        if card is not None and board.count(card) > 1:
            duplicate = card
            board = [None if item == duplicate else item for item in board]
    expected = {"preflop": 0, "flop": 3, "turn": 4, "river": 5, "showdown": 5}
    if (phase is not None and board_count is not None and board_count != expected[phase]
            or phase is not None and any(board[expected[phase]:])):
        phase = None
    if board_count is not None and any(board[board_count:]):
        phase, board_count = None, None
    seats = [{"seat": n, **dict.fromkeys((*SEAT_FIELDS, "displayed_stack_text", "visible_wager_text")), "visible_wager_status": "unknown",
              "scene_fields": []} for n in range(1, 7)]
    raw_seats = record.get("seats")
    if (isinstance(raw_seats, list) and len(raw_seats) == 6
            and all(isinstance(item, dict) and type(item.get("seat")) is int for item in raw_seats)
            and sorted(item["seat"] for item in raw_seats) == list(range(1, 7))):
        for item in raw_seats:
            seat = item["seat"]
            path = "seats." + str(seat) + ".displayed_stack"
            if admitted(path, "displayed_stack", seat):
                seats[seat - 1]["displayed_stack"] = integer(item.get("displayed_stack"), 0xffffffff)
                seats[seat - 1]["displayed_stack_text"] = amount_text(item.get("displayed_stack_text"), seats[seat - 1]["displayed_stack"])
            if admitted("seats." + str(seat) + ".visible_wager", "visible_wager", seat):
                seats[seat - 1]["visible_wager"] = integer(item.get("visible_wager"), 0xffffffff)
                if seats[seat - 1]["visible_wager"] is not None:
                    seats[seat - 1]["visible_wager_status"] = "accepted"
                    seats[seat - 1]["visible_wager_text"] = amount_text(item.get("visible_wager_text"), seats[seat - 1]["visible_wager"])
            for field in SCENE_LABELS:
                if not admitted("seats." + str(seat) + "." + field, field, seat):
                    continue
                value = item.get(field)
                if field in ("occupied", "dealer", "small_blind", "big_blind", "acting"):
                    seats[seat - 1][field] = value if type(value) is bool else None
                elif field == "status":
                    seats[seat - 1][field] = value if value in ("active", "folded", "all_in", "sitting_out") else None
                else:
                    seats[seat - 1][field] = value if value in SCENE_LABELS["badge"] and value != "unknown" else None
            if seats[seat - 1]["occupied"] is False:
                for field in ("status", "badge", "acting"):
                    if seats[seat - 1][field] not in (None, "unknown", "none", False):
                        seats[seat - 1][field] = None
    for field in ("dealer", "small_blind", "big_blind", "acting"):
        if sum(seat[field] is True for seat in seats) > 1:
            for seat in seats:
                seat[field] = None
    pot = integer(record.get("pot_size"), 0xffffffff) if admitted("pot_size", "pot_size") else None
    for seat in seats:
        seat["scene_fields"] = [field for field in SCENE_LABELS if seat[field] is not None]
    values = {"role": role if role != "uncertain" else None, "hero_seated": seated,
              "game_phase": phase, "board_count": board_count, "pot_size": pot,
              "board": True if board_count is not None and all(board[:board_count]) else None,
              "scene": True if any(seat["scene_fields"] for seat in seats) else None,
              "wagers": True if any(seat["visible_wager"] is not None for seat in seats) else None}
    values.update({"board_slots." + str(i + 1): card for i, card in enumerate(board)})
    values.update({"seats." + str(seat["seat"]) + "." + field: seat[field] for seat in seats for field in SEAT_FIELDS})
    supported = {field if seat is None else "seats." + str(seat) + "." + field
                 for (field, seat), valid in capabilities.items() if valid}
    if capabilities.get(("board_slot", None)):
        supported.update("board_slots." + str(i) for i in range(1, 6))
        supported.add("board")
    if any(valid and field in SCENE_LABELS for (field, _), valid in capabilities.items()):
        supported.add("scene")
    if any(valid and field == "visible_wager" for (field, _), valid in capabilities.items()):
        supported.add("wagers")
    statuses = field_statuses(values, supported | {"pot_convention"})
    return {"role": role, "hero_seated": seated, "hero_seat": None, "game_phase": phase, "board_count": board_count,
            "board_slots": board, "pot_size": pot, "pot_size_text": amount_text(record.get("pot_size_text"), pot),
            "seats": seats, "experimental": True, "quality_approved": False, "field_statuses": statuses}


@lru_cache(maxsize=1)
def diagnostic_vocabulary(path):
    if path.stat().st_size > MAX_RECORD:
        raise ValueError("invalid diagnostic vocabulary")
    manifest = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    result = {item["id"]: {q["id"]: q for q in item["questions"]} for item in manifest["passes"]}
    # The additional wager IDs use only the already closed character vocabulary.
    # This grants private logging, not calibration or public field admission.
    for seat in range(1, 7):
        result["p6_seat_%d_wager" % seat] = result["p3_pot"]
        result["p7_seat_%d_scene" % seat] = {
            qid: {"id": qid, "type": "choice", "option_order": labels} for qid, labels in SCENE_LABELS.items()}
    return result


def private_perception(record):
    """Keep bounded closed answer diagnostics locally, without granting admission."""
    vocabulary = diagnostic_vocabulary(ROOT / "crates/ingest/assets/laya/question-set.json")
    width, height = integer(record.get("frame_width"), 16384), integer(record.get("frame_height"), 16384)
    if not width or not height or not isinstance(record.get("passes"), list) or len(record["passes"]) > 24:
        raise ValueError("invalid diagnostics")

    def number(value, maximum=60_000):
        return value if type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value) else None

    passes = []
    for item in record["passes"]:
        if not isinstance(item, dict) or item.get("pass") not in vocabulary:
            continue
        bounds, dimensions = item.get("crop_bounds"), item.get("crop_dimensions")
        if (not isinstance(bounds, list) or not isinstance(dimensions, list) or len(bounds) != len(dimensions)
                or len(bounds) > 8 or any(not isinstance(b, list) or len(b) != 4
                                         or any(integer(v, 16384) is None for v in b)
                                         or not (b[0] < b[2] <= width and b[1] < b[3] <= height) for b in bounds)
                or any(d != [b[2] - b[0], b[3] - b[1]] for b, d in zip(bounds, dimensions))):
            bounds, dimensions = [], []
        questions = []
        raw_questions = item.get("questions")
        if isinstance(raw_questions, list) and len(raw_questions) <= 64:
            for question in raw_questions:
                spec = vocabulary[item["pass"]].get(question.get("question")) if isinstance(question, dict) else None
                if spec is None:
                    continue
                answer, raw = None, question.get("answer")
                if isinstance(raw, dict) and raw.get("type") == spec["type"]:
                    value = raw.get("value")
                    if (spec["type"] == "noul" and type(value) is bool
                            or spec["type"] == "choice" and isinstance(value, str) and value in spec["option_order"]):
                        answer = {"type": spec["type"], "value": value}
                questions.append({"question": spec["id"], "answer": answer,
                                  "score": number(question.get("score"), 1),
                                  "effective_floor": number(question.get("effective_floor"), 1),
                                  "status": question.get("status") if question.get("status") in ("accepted", "unknown", "rejected") else "unknown",
                                  "reason": question.get("reason") if question.get("reason") in DIAGNOSTIC_REASONS else "invalid-answer",
                                  "truncated": question.get("truncated") is True})
        segments = item.get("segments")
        segments = ({"n": integer(segments.get("n"), 0xffffffff), "overflow": segments["overflow"]}
                    if isinstance(segments, dict) and integer(segments.get("n"), 0xffffffff) is not None
                    and type(segments.get("overflow")) is bool else None)
        passes.append({"pass": item["pass"], "crop_bounds": bounds, "crop_dimensions": dimensions,
                       "questions": questions, "segments": segments, "total_ms": number(item.get("total_ms"))})
    fields = []
    raw_fields = record.get("fields")
    if isinstance(raw_fields, list) and len(raw_fields) <= 256:
        for item in raw_fields:
            if not isinstance(item, dict) or item.get("field") not in (*CAPABILITY_FIELDS, "screen_kind", "table_layout", "readable"):
                continue
            fields.append({"field": item["field"], "seat": integer(item.get("seat"), 6) or None,
                           "board_slot": integer(item.get("board_slot"), 5) or None,
                           "status": item.get("status") if item.get("status") in ("accepted", "unknown", "rejected") else "unknown",
                           "reason": item.get("reason") if item.get("reason") in DIAGNOSTIC_REASONS else "invalid-answer",
                           "admission_status": item.get("admission_status") if item.get("admission_status") in ("accepted", "unknown", "rejected") else "unknown",
                           "admission_reason": item.get("admission_reason") if item.get("admission_reason") in DIAGNOSTIC_REASONS else "awaiting-consensus"})
    timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
    admission = record.get("admission")
    saved = {"frame_width": width, "frame_height": height, "passes": passes, "fields": fields,
            "source_current": record.get("source_current") if type(record.get("source_current")) is bool else None,
            "admission": admission if admission in ("candidate", "source_current", "obsolete_observation",
                                                    "observation_expired", "decision_budget_expired") else None,
            "timing": {key: number(timing.get(key)) for key in ("capture_ms", "preprocess_ms", "encode_ms", "queue_ms",
                                                                "inference_ms", "assembly_ms", "publish_ms", "render_ms")}}
    if record.get("experimental") is not None:
        try:
            experimental_view(record, require_core=False)
            saved["experimental"] = copy.deepcopy(record["experimental"])
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            pass
    return saved


def experimental_view(record, *, require_core=True):
    """Validate draft transfer diagnostics, never capability or action admission."""
    proof = record.get("experimental")
    keys = {*EXPERIMENTAL_MARKERS, "descriptor", "donor_pass", "inherited_cutoff", "geometry_source",
            "crop_bounds", "crop_dimensions", "core_accepted"}
    if (not isinstance(proof, dict) or set(proof) != keys or type(proof.get("core_accepted")) is not bool
            or require_core and proof["core_accepted"] is not True):
        raise ValueError("invalid-experimental-proof")
    if any(type(proof[key]) is not type(value) or proof[key] != value for key, value in EXPERIMENTAL_MARKERS.items()):
        raise ValueError("invalid-experimental-markers")
    descriptor = proof.get("descriptor")
    if not isinstance(descriptor, dict) or set(descriptor) != {*EXPERIMENTAL_MARKERS, "version", "pass", "seat", "region"}:
        raise ValueError("invalid-experimental-descriptor")
    seat = integer(descriptor.get("seat"), 6)
    family = next((family for family in EXPERIMENTAL_BOUNDS
                   if descriptor.get("pass") == f"p{6 if family == 'wager' else 7}_seat_{seat}_{family}"), None)
    if (not seat or family is None or type(descriptor.get("version")) is not int or descriptor["version"] != 1
            or any(type(descriptor[key]) is not type(value) or descriptor[key] != value for key, value in EXPERIMENTAL_MARKERS.items())):
        raise ValueError("invalid-experimental-descriptor")
    region = descriptor.get("region")
    expected = {"id": f"seat_{seat}_{family}", "reference_dimensions": [900, 686],
                "bounds": list(EXPERIMENTAL_BOUNDS[family][seat - 1])}
    if (not isinstance(region, dict) or region != expected or set(region) != set(expected)
            or any(type(v) is not int for v in (*region["reference_dimensions"], *region["bounds"]))
            or proof.get("geometry_source") != EXPERIMENTAL_GEOMETRY):
        raise ValueError("invalid-experimental-geometry")
    width, height = integer(record.get("frame_width"), 16384), integer(record.get("frame_height"), 16384)
    if not width or not height:
        raise ValueError("invalid-experimental-geometry")
    bounds = [(v * size + reference // 2) // reference for v, size, reference in
              zip(region["bounds"], (width, height, width, height), (900, 686, 900, 686))]
    dimensions = [bounds[2] - bounds[0], bounds[3] - bounds[1]]
    if (proof.get("crop_bounds") != bounds or proof.get("crop_dimensions") != dimensions
            or any(type(v) is not int for v in (*proof["crop_bounds"], *proof["crop_dimensions"]))
            or min(dimensions) < 8 or bounds[2] > width or bounds[3] > height):
        raise ValueError("invalid-experimental-geometry")
    cutoff = proof.get("inherited_cutoff")
    if family == "wager":
        if (proof.get("donor_pass") != "p5_seat_1_stack" or type(cutoff) not in (int, float)
                or not math.isfinite(cutoff) or not .8 <= cutoff <= 1):
            raise ValueError("invalid-experimental-donor")
    elif proof.get("donor_pass") is not None or cutoff is not None:
        raise ValueError("invalid-experimental-floor")
    passes = record.get("passes")
    if not isinstance(passes, list) or len(passes) > 24:
        raise ValueError("invalid-experimental-pass")
    selected = [item for item in passes if isinstance(item, dict) and item.get("pass") == descriptor["pass"]]
    if len(selected) != 1:
        raise ValueError("invalid-experimental-pass")
    selected = selected[0]
    if selected.get("crop_bounds") != [bounds] or selected.get("crop_dimensions") != [dimensions]:
        raise ValueError("invalid-experimental-pass-geometry")
    questions = selected.get("questions")
    if not isinstance(questions, list) or len(questions) > 8:
        raise ValueError("invalid-experimental-questions")
    vocab = diagnostic_vocabulary(ROOT / "crates/ingest/assets/laya/question-set.json")[descriptor["pass"]]
    answers = {}
    for question in questions:
        if (not isinstance(question, dict) or set(question) != {"question", "answer", "score", "effective_floor", "status", "reason", "truncated"}
                or question.get("question") not in vocab or question["question"] in answers
                or question.get("effective_floor") is not None or question.get("status") not in ("unknown", "rejected")
                or question.get("reason") not in DIAGNOSTIC_REASONS or question["reason"] == "accepted"
                or type(question.get("truncated")) is not bool):
            raise ValueError("invalid-experimental-question-proof")
        score = question.get("score")
        if score is not None and (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError("invalid-experimental-score")
        raw = question.get("answer")
        guess = (raw["value"] if isinstance(raw, dict) and set(raw) == {"type", "value"} and raw.get("type") == "choice"
                 and isinstance(raw.get("value"), str) and raw["value"] in vocab[question["question"]]["option_order"] else None)
        safe = (guess if question["status"] == "unknown" and question["reason"] == "unapproved-capability"
                and not question["truncated"] and score is not None else None)
        answers[question["question"]] = (safe, score)
    result = {**EXPERIMENTAL_MARKERS, "quality_approved": False, "seat": seat, "kind": family,
              "donor_pass": proof["donor_pass"], "inherited_cutoff": cutoff, "fitted_floor": None,
              "numeric_text": None, "glyph_scores": [], "scene": [], "reason": "unapproved-capability"}
    if family == "wager":
        segments = selected.get("segments")
        n = integer(segments.get("n"), 8) if isinstance(segments, dict) else None
        fields = record.get("fields")
        evidence = [f for f in fields if isinstance(f, dict) and f.get("field") == "visible_wager" and f.get("seat") == seat] if isinstance(fields, list) else []
        field_valid = (len(evidence) == 1 and evidence[0].get("status") == "unknown"
                       and evidence[0].get("reason") == "unapproved-capability"
                       and evidence[0].get("admission_status") != "accepted")
        if n is None or not isinstance(segments, dict) or type(segments.get("overflow")) is not bool:
            result["reason"] = "missing-segments"
        elif segments["overflow"]:
            result["reason"] = "segmentation-overflow"
        elif n == 0:
            result["reason"] = "empty-segmentation"
        else:
            glyphs = [answers.get(f"g{i}", (None, None)) for i in range(1, n + 1)]
            text = "".join(label for label, _ in glyphs if label is not None)
            if any(score is not None and score < cutoff for _, score in glyphs):
                result["reason"] = "below-floor"
            elif (not field_valid or any(label not in "0123456789.," for label, _ in glyphs if label is not None)
                    or any(label is None or score is None for label, score in glyphs)
                    or re.fullmatch(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?", text) is None):
                result["reason"] = "invalid-answer"
            else:
                whole, _, fraction = text.replace(",", "").partition(".")
                amount = int(whole) * 100 + int(fraction.ljust(2, "0"))
                if amount <= 0xffffffff:
                    result.update(numeric_text=text, glyph_scores=[score for _, score in glyphs])
                else:
                    result["reason"] = "invalid-amount"
    else:
        fields = record.get("fields")
        if not isinstance(fields, list):
            raise ValueError("invalid-experimental-fields")
        evidence = [field for field in fields if isinstance(field, dict) and field.get("seat") == seat
                    and field.get("field") in SCENE_LABELS]
        if any(field.get("status") == "accepted" or field.get("admission_status") == "accepted" for field in evidence):
            raise ValueError("invalid-experimental-field-proof")
        result["scene"] = [{"field": field, "guess": answers.get(field, (None, None))[0],
                            "score": answers.get(field, (None, None))[1], "fitted_floor": None}
                           for field in SCENE_LABELS]
    return result


class PrivateLedger:
    def __init__(self, path=None, max_events=MAX_EVENTS, max_bytes=MAX_LEDGER_BYTES):
        self.path = path
        self.max_events, self.max_bytes = max_events, max_bytes
        self.count = self.bytes = 0
        self.complete = True
        self.stream = None

    def append(self, record):
        if self.path is None or not self.complete:
            return
        try:
            data = (json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self.complete = False
            return
        if self.count >= self.max_events or self.bytes + len(data) > self.max_bytes:
            self.complete = False
            return
        try:
            if self.stream is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.stream = self.path.open("xb")
            if self.stream.write(data) != len(data):
                raise OSError("incomplete private record")
            self.stream.flush()
            self.count += 1
            self.bytes += len(data)
        except OSError:
            self.complete = False

    def close(self):
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                self.complete = False
            finally:
                self.stream = None


class DashboardState:
    def __init__(self, alias, checkpoint=None, *, monotonic=time.monotonic, wall=time.time,
                 experimental_bet_action=False, service_instance_id=None):
        self.lock = threading.RLock()
        self.monotonic, self.wall = monotonic, wall
        if type(experimental_bet_action) is not bool:
            raise ValueError("invalid-experimental-service-flag")
        self.experimental_bet_action, self.service_instance_id = experimental_bet_action, service_instance_id
        self.experimental_receipt = self.experimental_budget = None
        self.experimental_approved = False
        self.experimental_candidates = self.experimental_deadline = self.experimental_source = None
        self.experimental_watermark = self.experimental_tombstone = None
        self.session_id = uuid.uuid4().hex
        self.event_seq = 0
        self.source = "idle"
        self.model = {"model_state": "disabled", "model_error": None, "alias": alias,
                      "checkpoint": None, "temperature_calibration_loaded": False,
                      "acceptance_floors_loaded": False,
                      "quality_gate": "failed", "advice_ready": False, "inference_busy": False}
        self.capture = {"state": "idle", "fresh_capture": False, "frames": 0,
                         "recorded_frames": 0, "recording_enabled": False,
                         "recorded_bytes": 0, "recording_status": "disabled", "recording_complete": False,
                         "width": None, "height": None, "epoch": None, "last_heartbeat_unix_ms": None}
        self.observation = None
        self.observation_ticket = self.observation_source = None
        self.analysis_inputs = False
        self.advice = self.advice_deadline = self.decision_seen = None
        self.partial_observation = self.partial_deadline = None
        self.partial_source = self.partial_source_deadline = None
        self.partial_ticket = self.invalidated_partial_ticket = None
        self.field_statuses = field_statuses()
        self.status_source = self.status_deadline = self.status_expires = None
        self.deadline = self.last_heartbeat = None
        self.version = (0, 0)
        self.invalidated_version = None
        self.target = None
        self.identity_configured = False
        self.recording_incomplete = False
        self.message = "Waiting for a visible CoinPoker table."
        self.history = {"state": "unavailable", "events": [], "counts": {}, "gaps": 0,
                        "ledger": {"enabled": False, "complete": True}}
        self.ledger = PrivateLedger()
        self.diagnostics = PrivateLedger(max_events=MAX_DIAGNOSTICS, max_bytes=MAX_DIAGNOSTIC_BYTES)
        self.readouts = PrivateLedger(max_events=4000, max_bytes=4 * 1024 * 1024)

    def set_model(self, state, error=None, calibrated=False, floors_loaded=False):
        with self.lock:
            self.model.update(model_state=state, model_error=error,
                              temperature_calibration_loaded=bool(calibrated),
                              acceptance_floors_loaded=bool(floors_loaded))
            if state != "ready":
                self._clear_analysis()
            self.event_seq += 1

    def set_busy(self, value):
        with self.lock:
            self.model["inference_busy"] = bool(value)

    def begin_stream(self, ledger_path=None):
        with self.lock:
            self.ledger.close()
            self.diagnostics.close()
            self.readouts.close()
            self.session_id = uuid.uuid4().hex
            self.event_seq = 0
            self.source = "live"
            self.target = None
            self.version = (0, 0)
            self.invalidated_version = None
            self.observation_ticket = self.observation_source = self.decision_seen = None
            self.last_heartbeat = None
            self.partial_source = self.partial_source_deadline = None
            self.partial_ticket = self.invalidated_partial_ticket = None
            self.field_statuses = field_statuses()
            self.status_source = self.status_deadline = self.status_expires = None
            self.identity_configured = False
            self.recording_incomplete = False
            self.experimental_receipt = self.experimental_budget = None
            self.experimental_approved = False
            self.experimental_watermark = self.experimental_tombstone = None
            self.capture.update(state="starting", fresh_capture=False, frames=0, recorded_frames=0,
                                 recording_enabled=False, recorded_bytes=0, recording_status="disabled",
                                  recording_complete=False, epoch=None, last_heartbeat_unix_ms=None)
            self.history = {"state": "unavailable", "events": [], "counts": {}, "gaps": 0,
                            "ledger": {"enabled": ledger_path is not None, "complete": True}}
            if ledger_path is True:
                ledger_path = local_path(".local/history/" + self.session_id + "/ledger.jsonl")
            self.ledger = PrivateLedger(ledger_path)
            self.diagnostics = PrivateLedger(ledger_path.with_name("perception.jsonl") if ledger_path else None,
                                              max_events=MAX_DIAGNOSTICS, max_bytes=MAX_DIAGNOSTIC_BYTES)
            self.readouts = PrivateLedger(ledger_path.with_name("readouts.jsonl") if ledger_path else None,
                                         max_events=4000, max_bytes=4 * 1024 * 1024)
            self._invalidate("stream-started")

    def end_stream(self, reason="feed-eof", *, session_id=None):
        with self.lock:
            if session_id is not None and session_id != self.session_id:
                return
            self.capture.update(state="disconnected", fresh_capture=False, epoch=None, recording_complete=False)
            self.recording_incomplete = True
            self._invalidate(reason)
            self.ledger.close()
            self.diagnostics.close()
            self.readouts.close()

    def attach_blocked(self, reason):
        with self.lock:
            if self.capture["state"] == "blocked" and self.message == reason:
                return
            self.capture.update(state="blocked", fresh_capture=False, epoch=None, recording_complete=False)
            self._invalidate(code(reason, "attachment-unavailable"))
            self.event_seq += 1

    def _invalidate(self, reason, *, version=None):
        self.invalidated_version = max(self.invalidated_version or (0, 0),
                                       self.version if version is None else version)
        self._clear_analysis()
        self.observation = self.observation_ticket = self.deadline = None
        self.partial_observation = self.partial_deadline = None
        self.partial_ticket = None
        if (reason not in ("partial-observation-expired", "observation-expired")
                and (version is None or self.experimental_source is None or version >= self.experimental_source[:2])):
            self._clear_experimental()
        unavailable = unavailable_reason(reason)
        for value in self.field_statuses.values():
            if value["status"] == "accepted" or unavailable == "stale" and value["reason"] != "missing-capability":
                value.update(status="unavailable", reason=unavailable)
        if unavailable == "stale":
            self.status_deadline = self.status_expires = None
        self.message = reason

    def _clear_analysis(self):
        self.advice = self.advice_deadline = None
        self.analysis_inputs = False
        self.model["advice_ready"] = False
        if self.observation is not None:
            self.observation["metrics"] = dict.fromkeys(METRIC_FIELDS)

    def _clear_experimental(self):
        if self.experimental_source is not None:
            self.experimental_tombstone = self.experimental_source
        self.experimental_candidates = self.experimental_deadline = self.experimental_source = None

    def set_experimental_receipt(self, receipt, *, approved=False, deadline=None, session_id=None):
        with self.lock:
            if session_id is not None and session_id != self.session_id:
                return
            if (self.experimental_receipt is not None and isinstance(receipt, dict)
                    and self.experimental_receipt.get("session_id") != receipt.get("session_id")):
                self._clear_experimental()
            self.experimental_receipt = copy.deepcopy(receipt) if isinstance(receipt, dict) else None
            self.experimental_approved = approved is True
            self.experimental_budget = deadline
            if not self._experimental_allowed():
                self._clear_experimental()

    def _experimental_allowed(self):
        receipt = self.experimental_receipt or {}
        now = int(self.wall() * 1000)
        updated = integer(receipt.get("updated_at_unix_ms"))
        return (self.experimental_bet_action is True and self.experimental_approved
                and isinstance(self.service_instance_id, str) and re.fullmatch(r"[0-9a-f]{32}", self.service_instance_id) is not None
                and self.source == "live" and self.model["model_state"] == "ready" and self.capture["fresh_capture"]
                and self.last_heartbeat is not None and (self.monotonic() - self.last_heartbeat) * 1000 < HEARTBEAT_MS
                and self.experimental_budget is not None and self.monotonic() < self.experimental_budget
                and receipt.get("source_policy") == "automatic-bounded" and receipt.get("status") == "capturing"
                and isinstance(receipt.get("session_id"), str) and re.fullmatch(r"[0-9a-f]{32}", receipt["session_id"]) is not None
                and receipt.get("mode") == "inference-enabled" and receipt.get("inference_enabled") is True
                and receipt.get("experimental_bet_action") is True and receipt.get("activity_state") in ("verifying", "active")
                and updated is not None and updated <= now + 500 and now - updated < 3000
                and (integer(receipt.get("remaining_ms")) or 0) > 0
                and integer(receipt.get("recorded_frames")) is not None and integer(receipt.get("max_frames")) is not None
                and receipt["recorded_frames"] < receipt["max_frames"])

    def _experimental_projection(self, record):
        ticket = self._ticket(record.get("observation"))
        if ticket is None:
            self._clear_experimental()
            return
        source = (*ticket[:3], integer(record.get("captured_at_unix_ms")))
        if source[3] is None:
            self._clear_experimental()
            return
        old = self.experimental_watermark
        if old is not None and (source[0] < old[0] or source[1] < old[1] or source[2] < old[2]
                                or source[3] is not None and old[3] is not None and source[3] < old[3]):
            return
        if (not self._experimental_allowed() or record.get("service_instance_id") != self.service_instance_id
                or record.get("source_policy") != "automatic-bounded" or record.get("experimental_bet_action") is not True
                or record.get("source_current") is not True or record.get("admission") != "source_current"
                or record.get("quality_approved") is not None and record.get("quality_approved") is not False):
            self._clear_experimental()
            self.experimental_watermark = self.experimental_tombstone = source
            return
        lease = self._partial_lease(record)
        if lease is not None and lease[4] > min(source[3], ticket[3] if ticket[3] is not None else source[3]) + 5000:
            lease = None
        if (lease is None or ticket[4] != self.target or ticket[1] != self.capture["epoch"]
                or (record.get("frame_width"), record.get("frame_height")) != (self.capture["width"], self.capture["height"])
                or self.invalidated_version is not None and ticket[:2] <= self.invalidated_version
                or self.experimental_tombstone is not None and source <= self.experimental_tombstone):
            self._clear_experimental()
            self.experimental_watermark = self.experimental_tombstone = source
            return
        try:
            view = experimental_view(record)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            self._clear_experimental()
            self.experimental_watermark = self.experimental_tombstone = source
            return
        gen, epoch, captured_mono, captured, expires, remaining = lease
        deadline = self.monotonic() + remaining / 1000
        if self.experimental_candidates is not None and source == self.experimental_source:
            deadline = min(deadline, self.experimental_deadline)
            expires = min(expires, self.experimental_candidates["expires_at_unix_ms"])
        self.experimental_candidates = {"version": 1, **view, "generation": gen, "epoch": epoch,
                                         "captured_at_unix_ms": captured, "expires_at_unix_ms": expires,
                                         "remaining_ms": max(0, int((deadline - self.monotonic()) * 1000))}
        self.experimental_source = self.experimental_watermark = source
        self.experimental_deadline = deadline

    def _target(self, value):
        if not isinstance(value, dict):
            return None
        pid = integer(value.get("process_id"), 0xffffffff)
        encoded = value.get("hwnd")
        hwnd = (int(encoded, 16) if isinstance(encoded, str)
                and re.fullmatch(r"0x[0-9a-fA-F]{1,16}", encoded) else None)
        exe = value.get("exe_name")
        if not pid or not hwnd or not isinstance(exe, str) or not exe or len(exe) > 256:
            return None
        text = json.dumps([self.session_id, pid, hwnd, exe], separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _recording(self, record, frames, fresh):
        fields = {"recording_enabled", "recorded_frames", "recorded_bytes",
                  "recording_status", "recording_complete"}
        present = fields.intersection(record)
        # Old schema-2 feeds without a recorder are normally disabled, not failed.
        if not present and self.capture["recording_status"] == "disabled":
            return
        recorded = integer(record.get("recorded_frames"), 20000)
        recorded_bytes = integer(record.get("recorded_bytes"), 2 * 1024 * 1024 * 1024)
        status = record.get("recording_status")
        enabled, complete = record.get("recording_enabled"), record.get("recording_complete")
        previous_frames, previous_bytes = self.capture["recorded_frames"], self.capture["recorded_bytes"]
        terminal = self.capture["recording_status"] in ("count_limit", "disk_limit", "duration_limit", "io_failure")
        valid = (present == fields and type(enabled) is bool and type(complete) is bool
                 and isinstance(status, str) and status in RECORDING_STATES
                 and frames is not None and recorded is not None and recorded_bytes is not None
                 and previous_frames <= recorded <= frames and previous_bytes <= recorded_bytes
                 and bool(recorded) == bool(recorded_bytes)
                 and (recorded > previous_frames) == (recorded_bytes > previous_bytes)
                 and (enabled and status != "disabled"
                      or not enabled and status == "disabled" and recorded == recorded_bytes == 0)
                 and (not complete or enabled and status == "active")
                 and (status != "active" or recorded < 20000 and recorded_bytes < 2 * 1024 * 1024 * 1024)
                 and (not terminal or status == self.capture["recording_status"]
                      and recorded == previous_frames and recorded_bytes == previous_bytes))
        if not valid:
            self.recording_incomplete = True
            self.capture.update(recording_status="io_failure", recording_complete=False)
            return
        if enabled and (not complete or status != "active"):
            self.recording_incomplete = True
        self.capture.update(recording_enabled=enabled, recorded_frames=recorded,
                            recorded_bytes=recorded_bytes, recording_status=status,
                            recording_complete=enabled and complete and fresh and not self.recording_incomplete)

    def _ticket(self, ticket):
        if not isinstance(ticket, dict):
            return None
        gen, epoch = integer(ticket.get("generation")), integer(ticket.get("epoch"))
        captured_mono = integer(ticket.get("captured_at_ms"))
        captured = integer(ticket.get("captured_at_unix_ms"))
        target = self._target(ticket.get("identity"))
        if (None in (gen, epoch, captured_mono, target)
                or "captured_at_unix_ms" in ticket and captured is None):
            return None
        return gen, epoch, captured_mono, captured, target

    def _partial_lease(self, record):
        ticket = self._ticket(record.get("observation"))
        if ticket is None:
            return None
        gen, epoch, captured_mono, source_utc, target = ticket
        valid = integer(record.get("valid_for_ms"), 5000)
        emitted = integer(record.get("emitted_at_unix_ms"))
        expires = integer(record.get("expires_at_unix_ms"))
        captured = integer(record.get("captured_at_unix_ms"))
        now = int(self.wall() * 1000)
        if (gen is None or epoch is None or captured_mono is None
                or gen < self.version[0] or epoch < self.version[1]
                or target is None or target != self.target or not self.capture["fresh_capture"]
                or self.last_heartbeat is None or (self.monotonic() - self.last_heartbeat) * 1000 >= HEARTBEAT_MS
                or not valid or emitted is None or expires is None or captured is None
                or source_utc is not None and source_utc != captured
                or emitted > now or captured > emitted or expires <= now or expires > emitted + valid
                or expires > captured + 5000):
            return None
        return gen, epoch, captured_mono, captured, expires, min(valid, expires - now)

    def _diagnostic_statuses(self, record, diagnostics):
        """Same-source reasons only: diagnostics can never grant a value or a lease."""
        if diagnostics["source_current"] is not True or diagnostics["admission"] != "source_current":
            return
        ticket = self._ticket(record.get("observation"))
        invalidated = self.invalidated_partial_ticket
        if ticket is not None and invalidated is not None and (ticket[:2] <= invalidated[:2]
                or ticket[4] == invalidated[4] and ticket[2] <= invalidated[2]):
            return
        lease = self._partial_lease(record)
        if lease is None:
            return
        gen, epoch, captured_mono, captured, expires, remaining = lease
        source = (gen, epoch, captured_mono, captured)
        reading = self.partial_observation or self.observation
        if reading is not None and (gen, epoch, captured) != (reading["generation"], reading["epoch"], reading["captured_at_unix_ms"]):
            return
        if reading is not None and self.status_source != source:
            return
        if (self.status_source is not None and (gen < self.status_source[0] or epoch < self.status_source[1]
                or captured_mono < self.status_source[2] or captured < self.status_source[3]
                or captured_mono == self.status_source[2] and captured != self.status_source[3])):
            return
        if self.invalidated_version is not None and (gen, epoch) <= self.invalidated_version:
            return
        deadline = self.monotonic() + remaining / 1000
        if self.status_source is not None and self.status_source[2:] == source[2:]:
            if self.status_deadline is None or self.status_deadline <= self.monotonic():
                return
            deadline = min(deadline, self.status_deadline)
        statuses = copy.deepcopy(reading["field_statuses"]) if reading else field_statuses()
        seen = set()
        for field in diagnostics["fields"]:
            name, seat, slot = field["field"], field["seat"], field["board_slot"]
            if name in ("screen_kind", "table_layout", "readable"):
                if field["status"] != "accepted":
                    reason = unavailable_reason(field["reason"], name)
                    for path, status in statuses.items():
                        if status["status"] != "accepted" and path in TRAINED_PATHS:
                            status["reason"] = reason
                continue
            if name == "board_slot" and slot is not None and seat is None:
                path = "board_slots." + str(slot)
            elif name in SEAT_FIELDS and seat is not None and slot is None:
                path = "seats." + str(seat) + "." + name
            elif seat is None and slot is None:
                path = name
            else:
                continue
            if path not in statuses or statuses[path]["status"] == "accepted":
                continue
            reason = (field["admission_reason"] if field["admission_status"] == "rejected"
                      else field["reason"] if field["status"] != "accepted" else "awaiting-consensus")
            statuses[path]["reason"] = ("insufficient-context" if path in seen
                                        else unavailable_reason(reason, name))
            seen.add(path)
        for aggregate, paths in (("board", ["board_slots." + str(n) for n in range(1, 6)]),
                                 ("scene", ["seats." + str(n) + "." + field for n in range(1, 7) for field in SCENE_LABELS]),
                                 ("wagers", ["seats." + str(n) + ".visible_wager" for n in range(1, 7)])):
            if statuses[aggregate]["status"] != "accepted":
                reasons = [statuses[path]["reason"] for path in paths]
                statuses[aggregate]["reason"] = next((r for r in ("stale", "occluded", "below-floor", "unsupported-layout",
                                                                   "insufficient-context", "missing-capability") if r in reasons),
                                                        "insufficient-context")
        self.field_statuses = statuses
        self.status_source, self.status_deadline, self.status_expires = source, deadline, expires
        if reading is not None:
            reading["field_statuses"] = copy.deepcopy(statuses)

    def ingest(self, record, *, session_id=None):
        with self.lock:
            if session_id is not None and session_id != self.session_id:
                return
            self.event_seq += 1
            if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
                    or record["schema_version"] != 2):
                if isinstance(record, dict) and record.get("event") == "partial_observation_invalidated":
                    return
                self._invalidate("invalid-feed-record")
                return
            event = record.get("event")
            activity_pending = (record.get("source_policy") in manual_capture.AUTOMATIC_POLICIES
                                and record.get("activity_state") != "active")
            if activity_pending and (event in ("observation", "table", "history", "decision", "recommendation")
                    or event == "partial_observation" and record.get("activity_state") != "verifying"):
                return
            if event in ("partial_observation", "observation") and self.invalidated_partial_ticket is not None:
                ticket = self._ticket(record.get("observation"))
                invalidated = self.invalidated_partial_ticket
                # A scoped replay cannot tombstone newer health or reuse changed pixels.
                if ticket is not None and (ticket[:2] <= invalidated[:2]
                        or ticket[4] == invalidated[4] and ticket[2] <= invalidated[2]):
                    return
            saved = {"event": code(event), "sequence": self.event_seq,
                     "recorded_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            if event == "configuration":
                self.identity_configured = record.get("identity_configured") is True
                self.message = "Awaiting capture heartbeat; model quality remains unapproved."
                saved["identity_configured"] = self.identity_configured
            elif event == "capture_health":
                gen, epoch = integer(record.get("generation")), integer(record.get("epoch"))
                target = self._target(record.get("identity"))
                emitted = integer(record.get("emitted_at_unix_ms"))
                captured = integer(record.get("captured_at_unix_ms"))
                now = int(self.wall() * 1000)
                width = integer(record.get("frame_width"), 16384)
                height = integer(record.get("frame_height"), 16384)
                if (gen is None or epoch is None or gen < self.version[0] or epoch < self.version[1]
                        or emitted is None or emitted > now or now - emitted >= HEARTBEAT_MS):
                    self.capture["recording_complete"] = False
                    self.capture["epoch"] = None
                    self._invalidate("obsolete-health-record")
                    return
                if (target != self.target or epoch != self.version[1]
                        or self.capture["width"] is not None and
                        (width, height) != (self.capture["width"], self.capture["height"])):
                    self._invalidate("capture-identity-or-epoch-changed")
                elif (gen, epoch) != self.version:
                    self._clear_analysis()
                self.target = target
                self.version = (gen, epoch)
                fresh = (record.get("fresh_capture") is True and target is not None
                          and captured is not None and captured <= emitted and now - captured < 1000)
                frames = integer(record.get("frame_count"))
                if not width or not height:
                    fresh = False
                if frames is None or frames < self.capture["frames"]:
                    frames = None
                    fresh = False
                if not frames:
                    fresh = False
                heartbeat = self.monotonic() - (now - emitted) / 1000
                if self.capture["last_heartbeat_unix_ms"] == emitted and self.last_heartbeat is not None:
                    heartbeat = min(heartbeat, self.last_heartbeat)
                self.last_heartbeat = heartbeat
                self.capture.update(state="active" if fresh else "unavailable", fresh_capture=fresh,
                                    frames=frames if frames is not None else self.capture["frames"],
                                      width=width, height=height,
                                      epoch=epoch if target is not None and width and height and frames else None,
                                      last_heartbeat_unix_ms=emitted)
                self._recording(record, frames, fresh)
                if not fresh:
                    self._invalidate("capture-not-fresh")
                saved.update(self.capture)
                saved["target_id"] = target
            elif event == "perception_diagnostics":
                # Historical/late diagnostics retain their original source without
                # entering admission, consensus, capture health or public field state.
                if record.get("experimental") is not None:
                    self._experimental_projection(record)
                ticket = record.get("observation")
                if not isinstance(ticket, dict):
                    return
                gen, epoch = integer(ticket.get("generation")), integer(ticket.get("epoch"))
                captured_mono = integer(ticket.get("captured_at_ms"))
                captured = integer(record.get("captured_at_unix_ms"))
                emitted = integer(record.get("emitted_at_unix_ms"))
                expires = integer(record.get("expires_at_unix_ms"))
                valid = integer(record.get("valid_for_ms"), 5000)
                target = self._target(ticket.get("identity"))
                if (None in (gen, epoch, captured_mono, captured, emitted, expires, valid)
                        or target is None or captured > emitted):
                    return
                try:
                    diagnostics = private_perception(record)
                except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
                    self.diagnostics.complete = False
                    return
                source_record = {**saved, **{k: record[k] for k in ("schema_version", "service_instance_id") if k in record},
                                 "generation": gen, "epoch": epoch,
                                 "target_id": target, "captured_at_ms": captured_mono,
                                 "captured_at_unix_ms": captured, "emitted_at_unix_ms": emitted,
                                 "expires_at_unix_ms": expires, "valid_for_ms": valid}
                self.diagnostics.append({**source_record, "diagnostics": diagnostics})
                numeric = [p for p in diagnostics["passes"] if p["pass"].startswith(("p3_", "p5_"))]
                if numeric:
                    # Keep original source clocks and raw numeric choices after
                    # the verbose diagnostic budget ends, without admitting them.
                    self.readouts.append({**source_record, "diagnostics": {
                        "frame_width": diagnostics["frame_width"], "frame_height": diagnostics["frame_height"],
                        "passes": [{**p, "questions": [{k: q[k] for k in ("question", "answer", "score")}
                                                          for q in p["questions"] if p["pass"] != "p0_full"
                                                          or q["question"] in ("screen_kind", "ev_table_layout", "ev_readable", "ev_pot")]}
                                   for p in diagnostics["passes"] if p["pass"] == "p0_full" or p in numeric],
                        "fields": [f for f in diagnostics["fields"] if f["field"] in ("pot_size", "displayed_stack")],
                        "admission": diagnostics["admission"], "source_current": diagnostics["source_current"]}})
                self._diagnostic_statuses(record, diagnostics)
                return
            elif event == "partial_observation":
                lease = self._partial_lease(record)
                if lease is None:
                    self._invalidate("obsolete-or-expired-partial")
                    return
                gen, epoch, captured_mono, captured, expires, remaining = lease
                if (self.invalidated_version is not None and (gen, epoch) <= self.invalidated_version
                        or self.partial_source is not None
                        and (captured_mono < self.partial_source[0] or captured < self.partial_source[1]
                             or captured_mono == self.partial_source[0] and captured != self.partial_source[1])):
                    self._invalidate("obsolete-or-expired-partial")
                    return
                if (self.partial_observation is not None and (gen, epoch) ==
                        (self.partial_observation["generation"], self.partial_observation["epoch"])):
                    return
                # Replace the complete field bundle. Never fill holes from an older hand/capture.
                view = partial_view(record, readout_only=activity_pending)
                deadline = self.monotonic() + remaining / 1000
                if self.partial_source == (captured_mono, captured):
                    deadline = min(deadline, self.partial_source_deadline)
                    remaining = max(0, int((deadline - self.monotonic()) * 1000))
                if not remaining:
                    self._invalidate("partial-observation-expired")
                    return
                self._clear_analysis()
                self.observation = self.observation_ticket = self.deadline = None
                self.version = (gen, epoch)
                self.partial_source = (captured_mono, captured)
                self.partial_ticket = self._ticket(record["observation"])
                self.partial_deadline = self.partial_source_deadline = deadline
                self.partial_observation = {**view, "generation": gen, "epoch": epoch,
                                             "captured_at_unix_ms": captured, "expires_at_unix_ms": expires,
                                             "remaining_ms": remaining}
                original = record.get("original_capture")
                if isinstance(original, dict):
                    sequence = integer(original.get("frame_index"))
                    width, height = integer(original.get("width"), 16384), integer(original.get("height"), 16384)
                    digest = original.get("sha256")
                    native_id = original.get("native_source_id")
                    recording_id, owner_id = original.get("recording_session_id"), original.get("capture_session_id")
                    if (type(original.get("schema_version")) is int and original["schema_version"] == 1 and sequence is not None
                            and original.get("captured_at_monotonic_ms") == captured_mono
                            and original.get("source_utc_unix_ms") == captured
                            and (width, height) == (self.capture.get("width"), self.capture.get("height"))
                            and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                            and isinstance(recording_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", recording_id)
                            and (owner_id is None or isinstance(owner_id, str) and re.fullmatch(r"[0-9a-f]{32}", owner_id))
                            and (native_id is None or isinstance(native_id, str) and re.fullmatch(r"[0-9]{1,20}", native_id))):
                        capture = {"session_id": self.session_id, "source_id": self.target, "epoch": epoch,
                            "sequence": sequence, "captured_at_ms": captured_mono, "captured_at_unix_ms": captured,
                            "width": width, "height": height, "sha256": digest,
                            "native_source_id": native_id, "recording_session_id": recording_id,
                            "capture_session_id": owner_id,
                            "service_instance_id": self.model.get("instance_id")}
                        self.partial_observation["capture"] = capture
                        self.partial_observation["field_captures"] = {path: copy.deepcopy(capture)
                            for path, status in view["field_statuses"].items() if status["status"] == "accepted"}
                self.field_statuses = copy.deepcopy(view["field_statuses"])
                self.status_source = (gen, epoch, captured_mono, captured)
                self.status_deadline, self.status_expires = deadline, expires
                self.message = "Partial reading; action context incomplete."
                saved["partial_observation"] = self.partial_observation
            elif event == "partial_observation_invalidated":
                ticket = self._ticket(record.get("observation"))
                emitted = integer(record.get("emitted_at_unix_ms"))
                captured = record.get("captured_at_unix_ms")
                fields = record.get("fields")
                reason = record.get("reason")
                if "fields" in record and (not isinstance(fields, list) or not 1 <= len(fields) <= len(PARTIAL_FIELDS)
                        or any(not isinstance(field, str) or field not in PARTIAL_FIELDS for field in fields)
                        or len(set(fields)) != len(fields)):
                    return
                if (type(record.get("schema_version")) is not int or ticket is None
                        or self.partial_observation is None or ticket != self.partial_ticket
                        or reason not in ("source-region-changed", "observation-expired")
                        or integer(record.get("generation")) != ticket[0]
                        or integer(record.get("epoch")) != ticket[1]
                        or self._target(record.get("identity")) != ticket[4]
                        or "captured_at_unix_ms" not in record or captured != ticket[3]
                        or captured is not None and integer(captured) is None
                        or emitted is None or emitted > int(self.wall() * 1000)
                        or emitted < self.partial_source[1]
                        or "valid_for_ms" in record or "expires_at_unix_ms" in record):
                    return
                if reason == "observation-expired":
                    if fields is not None or emitted < self.partial_observation["expires_at_unix_ms"]:
                        return
                elif (self.partial_deadline is None or self.monotonic() >= self.partial_deadline
                        or int(self.wall() * 1000) >= self.partial_observation["expires_at_unix_ms"]):
                    return
                if fields is not None:
                    view = self.partial_observation
                    statuses = view["field_statuses"]
                    # Verifying mode may have withheld native role/scene fields already.
                    removed = [field for field in fields if statuses[field]["status"] == "accepted"]
                    if not removed:
                        return
                    for field in removed:
                        parts = field.split(".")
                        if parts[0] == "board_slots":
                            view["board_slots"][int(parts[1]) - 1] = None
                        elif parts[0] == "seats":
                            seat, name = view["seats"][int(parts[1]) - 1], parts[2]
                            seat[name] = None
                            if name in ("displayed_stack", "visible_wager"):
                                seat[name + "_text"] = None
                            if name == "visible_wager":
                                seat["visible_wager_status"] = "unknown"
                            if name in seat["scene_fields"]:
                                seat["scene_fields"].remove(name)
                        else:
                            view[field] = "uncertain" if field == "role" else None
                            if field == "pot_size":
                                view["pot_size_text"] = None
                        statuses[field].update(status="unavailable", reason="stale")
                    # Derived display summaries may lose support, never gain it here.
                    for field, supported in (
                            ("role", view["role"] != "uncertain" and view["hero_seated"] is False),
                            ("board", view["board_count"] is not None and all(view["board_slots"][:view["board_count"]])),
                            ("scene", any(seat["scene_fields"] for seat in view["seats"])),
                            ("wagers", any(seat["visible_wager"] is not None for seat in view["seats"]))):
                        if not supported and statuses[field]["status"] == "accepted":
                            statuses[field].update(status="unavailable", reason="stale")
                            if field == "role":
                                view["role"] = "uncertain"
                    self.field_statuses = copy.deepcopy(statuses)
                self.invalidated_partial_ticket = ticket
                if fields is None or not any(self.field_statuses[field]["status"] == "accepted" for field in PARTIAL_FIELDS):
                    self._invalidate(reason, version=ticket[:2])
                else:
                    self.message = reason
                if not activity_pending:
                    self.history["gaps"] += 1
                if fields is not None:
                    saved["fields"] = fields
                saved.update(reason=self.message, generation=ticket[0], epoch=ticket[1],
                             captured_at_ms=ticket[2], captured_at_unix_ms=ticket[3],
                             target_id=ticket[4], emitted_at_unix_ms=emitted)
            elif event == "observation":
                ticket = record.get("observation")
                parsed_ticket = self._ticket(ticket)
                if parsed_ticket is None:
                    self._invalidate("invalid-observation")
                    return
                gen, epoch, captured_mono, source_utc, target = parsed_ticket
                valid = integer(record.get("valid_for_ms"), 5000)
                emitted = integer(record.get("emitted_at_unix_ms"))
                expires = integer(record.get("expires_at_unix_ms"))
                now = int(self.wall() * 1000)
                if (gen is None or epoch is None or gen < self.version[0] or epoch < self.version[1]
                        or self.invalidated_version is not None and (gen, epoch) <= self.invalidated_version
                        or target is None or target != self.target or not self.capture["fresh_capture"]
                        or epoch != self.capture["epoch"]
                        or self.last_heartbeat is None or (self.monotonic() - self.last_heartbeat) * 1000 >= HEARTBEAT_MS
                        or not valid or emitted is None or expires is None or emitted > now
                        or expires <= now or expires > emitted + valid):
                    self._invalidate("obsolete-or-expired-observation")
                    return
                if (self.partial_observation is not None and (gen, epoch) ==
                        (self.partial_observation["generation"], self.partial_observation["epoch"])):
                    # A complete sibling cannot refill fields withheld by the
                    # authoritative per-field source/consistency admission.
                    return
                try:
                    hero = cards(record.get("hero_cards"), 2)
                    board = cards(record.get("board"), 5)
                    pairs = [(c["rank"], c["suit"]) for c in hero + board]
                    if len(set(pairs)) != len(pairs):
                        raise ValueError("duplicate cards")
                except ValueError:
                    self._invalidate("invalid-observation-cards")
                    return
                if (self.observation is not None and (gen, epoch) ==
                        (self.observation["generation"], self.observation["epoch"])):
                    return
                phase = record.get("game_phase")
                captured = integer(record.get("captured_at_unix_ms"))
                if phase not in ("preflop", "flop", "turn", "river", "showdown"):
                    self._invalidate("unknown-observation-phase")
                    return
                if len(hero) not in (0, 2) or len(board) != {"preflop": 0, "flop": 3, "turn": 4,
                                                          "river": 5, "showdown": 5}[phase]:
                    self._invalidate("invalid-observation-cards")
                    return
                if (captured is None or captured > emitted or expires > captured + 5000
                        or source_utc is not None and source_utc != captured):
                    self._invalidate("invalid-observation-age")
                    return
                source = (target, epoch, captured_mono, captured)
                if self.observation_source is not None and source[:2] == self.observation_source[:2]:
                    if captured_mono <= self.observation_source[2]:
                        # Relabelling the same pixels cannot add evidence or renew a lease.
                        return
                    if captured < self.observation_source[3]:
                        self._invalidate("obsolete-or-expired-observation")
                        return
                if (self.partial_source is not None and captured_mono <= self.partial_source[0]
                        and captured <= self.partial_source[1]):
                    return
                # Per-field admission is not model quality approval. Legacy placeholders
                # and an empty hero-card list cannot establish seating or a turn.
                verified = record.get("verified_fields")
                verified = (set(verified) if isinstance(verified, list) and len(verified) <= len(VERIFIED_FIELDS)
                            and all(isinstance(v, str) and v in VERIFIED_FIELDS for v in verified) else set())
                seated = record.get("hero_seated") if "hero_seated" in verified else None
                seated = seated if type(seated) is bool else None
                required = record.get("action_required") if "action_required" in verified else None
                required = required if type(required) is bool else None
                amounts = {field: integer(record.get(field)) if field in verified else None
                           for field in ("pot_size", "to_call", "hero_chips", "min_raise_to",
                                         "max_raise_to", "acting_to_call")}
                acting = integer(record.get("acting_seat"), 6) if "acting_seat" in verified else None
                acting = acting if acting else None
                if acting is None:
                    amounts["acting_to_call"] = None
                controls, controls_valid = unknown_controls(), False
                raw_controls = record.get("controls")
                if "controls" in verified and isinstance(raw_controls, list) and len(raw_controls) <= len(ACTIONS):
                    known = {}
                    for item in raw_controls:
                        if (not isinstance(item, dict) or item.get("action") not in ACTIONS
                                or item["action"] in known or item.get("presence") not in ("present", "absent", "unknown")
                                or item.get("enabled") not in ("enabled", "disabled", "unknown")
                                or item["presence"] != "present" and item["enabled"] != "unknown"):
                            break
                        known[item["action"]] = {k: item[k] for k in ("action", "presence", "enabled")}
                    else:
                        controls = [known.get(item["action"], item) for item in controls]
                        controls_valid = True
                enabled = [item["action"] for item in controls if item["enabled"] == "enabled"]
                present = any(item["presence"] == "present" for item in controls)
                seating_contradiction = seated is False and (bool(hero) or required is True or present)
                contradiction = ("controls" in verified and not controls_valid
                                 or seating_contradiction
                                 or required is False and bool(enabled)
                                 or "check" in enabled and ("call" in enabled or "fold" in enabled)
                                 or amounts["to_call"] == 0 and ("call" in enabled or "fold" in enabled)
                                 or amounts["to_call"] is not None and amounts["to_call"] > 0 and "check" in enabled
                                 or amounts["min_raise_to"] is not None and amounts["max_raise_to"] is not None
                                 and amounts["min_raise_to"] > amounts["max_raise_to"])
                role = "uncertain"
                if not contradiction:
                    if seated is False and required is False and not hero:
                        role = "observing"
                    elif seated is True and required is False:
                        role = "seated_waiting"
                    elif (seated is True and required is True and len(hero) == 2 and controls_valid
                          and enabled and phase != "showdown"):
                        role = "your_turn"
                if record.get("role") not in ROLES or record["role"] != role:
                    role = "uncertain"
                if role == "uncertain":
                    required = None
                    controls = unknown_controls()
                    if seating_contradiction:
                        seated = None
                if seated is not True:
                    amounts["hero_chips"] = None
                hero_seat = integer(record.get("hero_seat"), 6) if "hero_seat" in verified and seated is True else None
                hero_seat = hero_seat or None
                if role != "your_turn":
                    for field in ("to_call", "min_raise_to", "max_raise_to"):
                        amounts[field] = None
                wagers = []
                raw_wagers = record.get("wagers")
                if "wagers" in verified and isinstance(raw_wagers, list) and len(raw_wagers) <= 6:
                    seen = set()
                    for item in raw_wagers:
                        seat = integer(item.get("seat"), 6) if isinstance(item, dict) else None
                        if not seat or seat in seen:
                            wagers = []
                            break
                        seen.add(seat)
                        wagers.append({"seat": seat, "amount": integer(item.get("amount"))})
                metrics = dict.fromkeys(METRIC_FIELDS)
                remaining = min(valid, expires - now)
                previous_version = self.version
                self.version = (gen, epoch)
                deadline = self.monotonic() + remaining / 1000
                if (gen, epoch) == previous_version and self.deadline is not None:
                    deadline = min(deadline, self.deadline)
                self.deadline = deadline
                self._clear_analysis()
                self.observation_ticket, self.observation_source = parsed_ticket, source
                if self.partial_observation is not None and (gen, epoch) != (self.partial_observation["generation"], self.partial_observation["epoch"]):
                    self.partial_observation = self.partial_deadline = None
                    self.partial_ticket = None
                self.observation = {"session_id": self.session_id, "source_id": target,
                                    "generation": gen, "epoch": epoch, "game_phase": phase,
                                    "captured_at_unix_ms": captured,
                                    "hero_cards": hero, "board": board,
                                    "role": role, "hero_seated": seated, "hero_seat": hero_seat, "acting_seat": acting,
                                    "amounts": amounts, "wagers": wagers, "metrics": metrics,
                                    "available_actions": enabled if role == "your_turn" else None,
                                    "controls": controls, "action_required": required,
                                    "experimental": True, "quality_approved": False,
                                    "expires_at_unix_ms": expires, "remaining_ms": remaining}
                self.analysis_inputs = self.model["model_state"] == "ready" and native_analysis_inputs(record, self.observation)
                if self.analysis_inputs:
                    self.observation["metrics"] = observation_metrics(record["metrics"], self.observation)
                raw_texts = record.get("amount_texts")
                raw_texts = raw_texts if isinstance(raw_texts, dict) else {}
                self.observation["amount_texts"] = {field: amount_text(raw_texts.get(field), amount)
                                                    for field, amount in amounts.items()}
                values = {**amounts, "role": role if role != "uncertain" else None, "hero_seated": seated,
                          "hero_seat": hero_seat, "acting_seat": acting, "action_required": required,
                          "hero_cards": True if hero else None, "board": True, "game_phase": phase,
                          "board_count": len(board), "controls": True if controls_valid and role != "uncertain" else None}
                values.update({"board_slots." + str(i + 1): card for i, card in enumerate(board)})
                self.field_statuses = field_statuses(values, set(TRAINED_PATHS) | verified)
                self.observation["field_statuses"] = copy.deepcopy(self.field_statuses)
                self.status_source = (gen, epoch, integer(ticket.get("captured_at_ms")) or 0, captured)
                self.status_deadline, self.status_expires = deadline, expires
                self.message = "Experimental full-state analysis." if self.analysis_inputs else "Observation received; analysis inputs unavailable."
                saved["observation"] = self.observation
            elif event == "clear" and self.partial_observation is not None:
                # Advice rejection does not invalidate independent field evidence.
                self._clear_analysis()
                self.observation = self.observation_ticket = self.deadline = None
                saved["reason"] = code(record.get("reason"), "advice-cleared")
            elif event in ("observation_invalidated", "clear", "discarded"):
                gen, epoch = integer(record.get("generation")), integer(record.get("epoch"))
                if event == "discarded" and gen is not None and (gen < self.version[0]
                        or epoch is not None and epoch < self.version[1]):
                    return
                if gen is not None:
                    self.version = (max(gen, self.version[0]), max(epoch or 0, self.version[1]))
                self._invalidate(code(record.get("reason"), "observation-invalidated"))
                if not activity_pending:
                    self.history["gaps"] += 1
                saved["reason"] = self.message
            elif event == "status":
                state = code(record.get("state"), "unavailable")
                if state not in ("analyzing", "capturing_table", "candidate_table", "verifying"):
                    self.capture.update(state="unavailable", fresh_capture=False, epoch=None)
                    self._invalidate(code(record.get("reason"), state))
                saved["state"] = state
            elif event == "history":
                summary = record.get("summary", {})
                if not isinstance(summary, dict):
                    self._invalidate("invalid-history-record")
                    return
                events = summary.get("events", [])
                sanitized = []
                if isinstance(events, list):
                    for item in events[-200:]:
                        if isinstance(item, dict):
                            kind = item.get("event")
                            kind = kind if isinstance(kind, str) else None
                            detail = item.get("action") if isinstance(item.get("action"), dict) else item
                            action = detail.get("kind") if kind == "action" else None
                            seat = integer(detail.get("seat"), 5)
                            ordinal = integer(detail.get("preflop_raise_ordinal"), MAX_EVENTS)
                            if (ordinal is None or ordinal < 2 or action not in ("bet", "raise")
                                    or item.get("street") != "preflop" or detail.get("trusted") is not True
                                    or detail.get("full_raise") is not True or detail.get("forced") != "voluntary"):
                                ordinal = None
                            sanitized.append({"kind": {"action": "action", "hand_started": "boundary",
                                                       "movement": "boundary", "hand_outcome": "hand"}.get(kind, "gap"),
                                              "reason": code(item.get("reason"), "unknown-evidence"),
                                              "sequence": integer(item.get("event_sequence")),
                                              "seat": seat + 1 if seat is not None else None,
                                               "amount": integer(detail.get("amount")),
                                               "all_in": detail.get("all_in") if type(detail.get("all_in")) is bool else None,
                                               "preflop_raise_ordinal": ordinal,
                                               "action": action if action in ACTIONS else None})
                counts = summary.get("counts", {})
                if not isinstance(counts, dict):
                    counts = {}
                fields = ("folds", "checks", "calls", "bets", "raises")
                values = [integer(counts.get(field), MAX_EVENTS) for field in fields]
                normalized_counts = {"observed_actions": sum(values) if all(v is not None for v in values) else None,
                                      "eligible_hands": None}
                normalized_counts.update(zip(fields, values))
                occupants = summary.get("occupants", [])
                if isinstance(occupants, list) and len(occupants) <= 6:
                    hands = [integer(o.get("eligible_hands"), MAX_EVENTS) for o in occupants if isinstance(o, dict)]
                    if len(hands) == len(occupants) and all(h is not None for h in hands):
                        normalized_counts["eligible_hands"] = sum(hands)
                for field in ("three_bets", "four_bets", "incomplete_raises"):
                    normalized_counts[field] = integer(counts.get(field), MAX_EVENTS)
                self.history.update(state="partial", events=sanitized,
                                    counts=normalized_counts,
                                    gaps=max(self.history["gaps"], integer(summary.get("gaps")) or 0))
                saved["history"] = {"state": "partial", "events": sanitized,
                                    "counts": normalized_counts,
                                    "gaps": self.history["gaps"]}
            elif event == "decision":
                lease = self._partial_lease(record)
                ticket = self._ticket(record.get("observation"))
                view = self.observation
                if (lease is None or ticket != self.observation_ticket or view is None
                        or not self.analysis_inputs or self.model["model_state"] != "ready"
                        or ticket[:2] != self.version or ticket[1] != self.capture["epoch"]
                        or view["captured_at_unix_ms"] != lease[3] or view["role"] != "your_turn"
                        or view["action_required"] is not True or view["hero_seated"] is not True
                        or self.partial_observation is not None or ticket == self.decision_seen
                        or self.monotonic() >= self.deadline or int(self.wall() * 1000) >= view["expires_at_unix_ms"]):
                    return
                action = record.get("action")
                if action not in NATIVE_ACTIONS:
                    return
                action = "all_in" if action == "allin" else action
                amount = integer(record.get("amount"), 0xffffffff)
                ev, equity = finite(record.get("ev"), -0xffffffff, 2 * 0xffffffff), finite(record.get("equity"), 0, 1)
                optional = {key: finite(record.get(key), 0, 1) for key in ("pot_odds", "break_even", "confidence")}
                if (amount is None or ev is None or equity is None
                        or any(key not in record or record[key] is not None and value is None for key, value in optional.items())
                        or action not in view["available_actions"]
                        or not any(item == {"action": action, "presence": "present", "enabled": "enabled"}
                                   for item in view["controls"])):
                    return
                cost, stack = view["amounts"]["to_call"], view["amounts"]["hero_chips"]
                low, high = view["amounts"]["min_raise_to"], view["amounts"]["max_raise_to"]
                if (action in ("fold", "check") and amount != 0
                        or action == "call" and amount != min(cost, stack)
                        or action == "raise" and (low is None or high is None or not low <= amount <= high)
                        # No hero contribution/all-in raise-to proof exists in this DTO.
                        # A short all-in call, unlike an all-in raise, is independently checkable.
                        or action == "all_in" and (stack > cost or amount != stack)):
                    return
                expected_odds = min(cost, stack) / (view["amounts"]["pot_size"] + min(cost, stack)) if cost else None
                if any((value is None) != (expected_odds is None) or value is not None
                       and not math.isclose(value, expected_odds, rel_tol=1e-6, abs_tol=1e-6)
                       for value in (optional["pot_odds"], optional["break_even"])):
                    return
                expires = min(lease[4], view["expires_at_unix_ms"])
                deadline = min(self.deadline, self.monotonic() + lease[5] / 1000)
                self.advice = {key: view[key] for key in ("session_id", "source_id", "generation", "epoch", "captured_at_unix_ms")}
                self.advice.update(action=action, amount=amount, ev=ev, equity_pct=equity * 100,
                                   pot_odds_pct=None if optional["pot_odds"] is None else optional["pot_odds"] * 100,
                                   break_even_pct=None if optional["break_even"] is None else optional["break_even"] * 100,
                                   confidence=optional["confidence"], experimental=True, quality_approved=False,
                                   expires_at_unix_ms=expires, remaining_ms=max(0, int((deadline - self.monotonic()) * 1000)))
                self.advice_deadline, self.decision_seen = deadline, ticket
                self.model["advice_ready"] = True
                self.message = "Experimental native decision; perception quality is not certified."
                saved["advice"] = self.advice
            else:
                # Bare replay decisions and weaker table readings never enter this stream.
                return
            self.ledger.append(saved)

    def snapshot(self):
        with self.lock:
            now = self.monotonic()
            if self.experimental_candidates is not None:
                if (not self._experimental_allowed() or now >= self.experimental_deadline
                        or int(self.wall() * 1000) >= self.experimental_candidates["expires_at_unix_ms"]):
                    self._clear_experimental()
                else:
                    self.experimental_candidates["remaining_ms"] = max(0, int((self.experimental_deadline - now) * 1000))
            if self.last_heartbeat is not None and (now - self.last_heartbeat) * 1000 >= HEARTBEAT_MS:
                self.capture.update(state="unavailable", fresh_capture=False, epoch=None, recording_complete=False)
                self._invalidate("capture-heartbeat-expired")
            if self.deadline is not None:
                remaining = min(int((self.deadline - now) * 1000), self.observation["expires_at_unix_ms"] - int(self.wall() * 1000))
                if remaining <= 0:
                    self._invalidate("observation-expired")
                else:
                    self.observation["remaining_ms"] = remaining
            if self.partial_deadline is not None:
                remaining = int((self.partial_deadline - now) * 1000)
                if remaining <= 0 or self.partial_observation["expires_at_unix_ms"] <= int(self.wall() * 1000):
                    self.invalidated_partial_ticket = self.partial_ticket
                    self._invalidate("partial-observation-expired", version=self.partial_ticket[:2])
                else:
                    self.partial_observation["remaining_ms"] = remaining
            if self.status_deadline is not None and (now >= self.status_deadline
                    or self.status_expires <= int(self.wall() * 1000)):
                for value in self.field_statuses.values():
                    if value["reason"] != "missing-capability":
                        value.update(status="unavailable", reason="stale")
                self.status_deadline = self.status_expires = None
            if self.advice is not None:
                remaining = min(int((self.advice_deadline - now) * 1000), self.advice["expires_at_unix_ms"] - int(self.wall() * 1000))
                if remaining <= 0:
                    self.advice = self.advice_deadline = None
                    self.model["advice_ready"] = False
                else:
                    self.advice["remaining_ms"] = remaining
            self.history["ledger"]["complete"] = self.ledger.complete
            return copy.deepcopy({"schema_version": 1, "session_id": self.session_id,
                                  "event_seq": self.event_seq, "source": self.source,
                                   "server": self.model, "capture": {**self.capture,
                                       "source_id": self.target if self.capture["epoch"] is not None else None,
                                       "generation": self.version[0] if self.capture["epoch"] is not None else None},
                                    "observation": self.observation, "advice": self.advice,
                                    "partial_observation": self.partial_observation,
                                     "experimental_candidates": self.experimental_candidates,
                                     "readout_evidence": {"enabled": self.readouts.path is not None,
                                                          "complete": self.readouts.complete,
                                                          "count": self.readouts.count, "bytes": self.readouts.bytes},
                                   "field_statuses": self.field_statuses,
                                  "history": self.history,
                                  "readiness": "UI_READY",
                                  "message": self.message})


def _reject_constant(_):
    raise ValueError("nonfinite JSON")


def drain_feed(stream, state, *, session_id=None):
    session_id = state.session_id if session_id is None else session_id
    try:
        while True:
            raw = stream.readline(MAX_RECORD + 1)
            if not raw:
                break
            if len(raw) > MAX_RECORD or not raw.endswith(b"\n"):
                state.end_stream("invalid-feed-size", session_id=session_id)
                return
            try:
                record = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
            except (ValueError, UnicodeDecodeError, RecursionError):
                state.end_stream("invalid-feed-json", session_id=session_id)
                return
            state.ingest(record, session_id=session_id)
    except (OSError, ValueError):
        state.end_stream("feed-read-failed", session_id=session_id)
        return
    state.end_stream(session_id=session_id)


class ManualSessionFeed:
    """Read the approved child's private JSONL; never select or spawn a source.

    The CLI owns the only capture process. This bounded reader shares exactly the
    same DashboardState ingestion/projection as LiveFeed, without auto-attachment.
    """

    def __init__(self, state, instance_id, *, root=ROOT):
        self.state, self.instance_id, self.root = state, instance_id, Path(root).resolve()
        self.session_id = self.stream_id = self.path = None
        self.offset, self.pending = 0, b""
        self.seen = set()
        self.closed = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.deadline = None
        self.failed = False
        self.failure_reason = self.validation_reason = None
        self.identity = None
        self.source_policy = "manual"
        self.retired = {}
        self.evidence_budget = self.evidence_last = None
        self.receipt_updated = self.receipt_elapsed = self.receipt_deadline = None
        self.candidate_updated = self.candidate_elapsed = None
        from laya_visual import VisualWorker
        self.visual = VisualWorker(self.root, instance_id)

    def _failure(self, error, stage, row=None, *, persist=True):
        if self.failure_reason is None:
            message = error if isinstance(error, str) else str(error)
            if isinstance(error, OSError) and error.strerror:
                message = "[Errno %s] %s" % (error.errno, error.strerror)
            message = "".join(c if 32 <= ord(c) < 127 else " " for c in message[:1024])
            public_keys = {*FIELD_PATHS, "schema_version", "event", "identity", "exe_name", "process_id", "hwnd",
                           "generation", "epoch", "frame_count", "frame_width", "frame_height", "frame_index",
                           "captured_at_unix_ms", "captured_at_ms", "utf-8", "NoneType", "dict", "list",
                           "int", "str", "bool", "float", "tuple", "bytes", "lower", "get", "frame",
                           "source_id", "capture_directory", "recorded_frames", "recorded_bytes"}
            message = re.sub(r"(?i)(?:[a-z]:[\\/]|\\\\|\.local[\\/])[^\"'\r\n]*", "<private-path>", message)
            message = re.sub(r"(['\"])(.*?)(?:\1|$)", lambda m: m.group(0) if m.group(2) in public_keys else "'<redacted>'", message)
            message = re.sub(r"\{.*(?:\}|$)", "<record>", message)
            if message.startswith("[") and not message.startswith("[Errno "):
                message = "<record>"
            message = message[:320]
            row = row if isinstance(row, dict) else {}
            frame = row.get("frame") if isinstance(row.get("frame"), dict) else {}
            ticket = row.get("observation") if isinstance(row.get("observation"), dict) else row
            event = row.get("event")
            self.failure_reason = {"type": None if isinstance(error, str) else type(error).__name__[:64],
                "message": message, "stage": stage,
                "service_instance_id": code(self.instance_id, None), "capture_session_id": code(self.session_id, None),
                "source_id": code(self.state.target, None),
                "event": event if isinstance(event, str) and event in {*manual_capture.FEED_EVENTS, "manual_capture"} else "unknown",
                "generation": integer(ticket.get("generation")), "epoch": integer(ticket.get("epoch")),
                "frame_index": integer(frame.get("frame_index")), "frame_count": integer(row.get("frame_count")),
                "width": integer(frame.get("width", row.get("frame_width")), 16384),
                "height": integer(frame.get("height", row.get("frame_height")), 16384),
                "captured_at_unix_ms": integer(frame.get("source_utc_unix_ms", ticket.get("captured_at_unix_ms"))),
                "captured_at_ms": integer(frame.get("captured_at_monotonic_ms", ticket.get("captured_at_ms"))),
                "emitted_at_unix_ms": integer(row.get("emitted_at_unix_ms")), "offset": self.offset,
                "observed_at_unix_ms": int(self.state.wall() * 1000),
                "receipt_updated_at_unix_ms": self.receipt_updated, "receipt_elapsed_ms": self.receipt_elapsed,
                "candidate_updated_at_unix_ms": self.candidate_updated, "candidate_elapsed_ms": self.candidate_elapsed,
                "last_health": {key: self.state.capture[key] for key in
                                ("frames", "width", "height", "epoch", "last_heartbeat_unix_ms")}}
        if persist and self.path is not None:
            try:
                path = manual_capture.private_path(self.path / "feed-failure.json", root=self.root)
                manual_capture.write_json(path, self.failure_reason, exclusive=True)
            except (OSError, ValueError):
                pass  # A separate, single bounded cause never blocks the owned stop.

    def _end(self, reason):
        if self.stream_id is not None:
            if reason in {"receipt-invalid", "status-stale", "manual-session-ended"}:
                self._failure(self.validation_reason or reason, "receipt", persist=False)
            if self.path is not None:
                self.retired[self.session_id] = reason
            self.state.end_stream(reason, session_id=self.stream_id)
            self.stream_id = None
        self.pending = b""

    def _flush_stops(self):
        # HTTP snapshots only tombstone in memory. The passive worker (or service
        # shutdown) stops each retired owned session even if its receipt recovers.
        for sid, reason in list(self.retired.items()):
            if reason in {"manual-feed-failed", "receipt-invalid", "status-stale", "manual-session-ended"}:
                if sid == self.session_id and self.failure_reason is not None:
                    self._failure(reason, "receipt")
                manual_capture.fail_session(sid, "feed-failed", root=self.root)
            elif reason == "model-not-ready":
                manual_capture.fail_session(sid, "model-not-ready", root=self.root)
            else:
                manual_capture.stop_session(sid, root=self.root)
            del self.retired[sid]

    def _valid(self, current):
        self.validation_reason = None
        self.candidate_updated = integer(current.get("updated_at_unix_ms"), 10**15)
        self.candidate_elapsed = integer(current.get("elapsed_ms"))
        if current.get("source_policy", "manual") != self.source_policy:
            self.validation_reason = "manual-feed-policy-mismatch"
            return False
        sustained = self.source_policy == "automatic-sustained"
        evidence = current.get("evidence") or {}
        if sustained:
            updated, elapsed = current.get("updated_at_unix_ms"), current.get("elapsed_ms")
            now = self.state.monotonic()
            if self.candidate_updated is None or self.candidate_elapsed is None:
                self.validation_reason = "owner-receipt-time-invalid"
                return False
            if self.receipt_updated is not None and updated < self.receipt_updated:
                self.validation_reason = "owner-receipt-update-regressed"
                return False
            if self.receipt_elapsed is not None and elapsed < self.receipt_elapsed:
                self.validation_reason = "owner-receipt-elapsed-regressed"
                return False
            age = self.state.wall() * 1000 - updated
            if age < 0:
                self.validation_reason = "owner-receipt-future"
                return False
            if age >= 3000:
                self.validation_reason = "owner-receipt-expired"
                return False
            # A consumer gap expires the cached sample, not a newer original
            # owner heartbeat. Timestamp rewrites without monotonic progress
            # retain the old lease, including its wall-freeze protection.
            new_sample = (self.receipt_updated is None or updated > self.receipt_updated
                          and elapsed > self.receipt_elapsed)
            deadline = now + min(3, (3000 - age) / 1000)
            if not new_sample and self.receipt_deadline is not None:
                deadline = min(self.receipt_deadline, deadline)
            budget_open = (current.get("receipt_version") == 2 and self.evidence_budget is not None
                and tuple(evidence.get(key) for key in ("max_duration_ms", "max_frames", "max_bytes")) == self.evidence_budget
                and self.evidence_last is not None and all(evidence.get(key, -1) >= self.evidence_last[key]
                for key in ("recorded_frames", "recorded_bytes", "elapsed_ms"))
                and (self.evidence_last["status"] != "ended" or evidence == self.evidence_last))
        else:
            budget_open = (current["remaining_ms"] > 0 and current["recorded_frames"] < current["max_frames"]
                           and self.deadline is not None and self.state.monotonic() < self.deadline)
        if not budget_open:
            if sustained:
                if current.get("receipt_version") != 2:
                    self.validation_reason = "owner-receipt-version-invalid"
                elif self.evidence_budget is None or self.evidence_last is None:
                    self.validation_reason = "evidence-budget-uninitialized"
                elif tuple(evidence.get(key) for key in ("max_duration_ms", "max_frames", "max_bytes")) != self.evidence_budget:
                    self.validation_reason = "evidence-budget-changed"
                elif any(evidence.get(key, -1) < self.evidence_last[key] for key in ("recorded_frames", "recorded_bytes", "elapsed_ms")):
                    self.validation_reason = "evidence-counter-regressed"
                else:
                    self.validation_reason = "ended-evidence-changed"
            else:
                self.validation_reason = ("recording-count-limit" if current["recorded_frames"] >= current["max_frames"]
                                          else "session-duration-ended")
        valid = (not self.closed.is_set() and current["session_id"] == self.session_id
                and current["mode"] == "inference-enabled" and current["inference_enabled"]
                and current.get("source_policy", "manual") == self.source_policy
                and (self.source_policy not in manual_capture.AUTOMATIC_POLICIES
                      or current.get("activity_state") in {"verifying", "active"})
                and current["status"] == "capturing" and budget_open
                and self.state.model["model_state"] == "ready")
        if not valid and self.validation_reason is None:
            self.validation_reason = ("feed-closed" if self.closed.is_set()
                else "owner-session-mismatch" if current["session_id"] != self.session_id
                else "owner-inference-unavailable" if current["mode"] != "inference-enabled" or not current["inference_enabled"]
                else "owner-activity-unavailable" if self.source_policy in manual_capture.AUTOMATIC_POLICIES
                     and current.get("activity_state") not in {"verifying", "active"}
                else current.get("stop_reason") or "owner-not-capturing" if current["status"] != "capturing"
                else "model-not-ready")
        if valid and sustained:
            if self.state.monotonic() >= deadline:
                self.validation_reason = "owner-receipt-expired"
                return False
            self.evidence_last = dict(evidence)
            self.receipt_deadline = deadline
            self.receipt_updated, self.receipt_elapsed = updated, elapsed
        return valid

    def snapshot(self):
        # Polling can invalidate, but never joins, starts, or rearms a session.
        with self.lock:
            current = manual_capture.public_snapshot(root=self.root)
            if self.stream_id is not None and not self._valid(current):
                self._end(current.get("stop_reason") or ("model-not-ready" if self.state.model["model_state"] != "ready"
                                                         else "manual-session-ended"))
            if self.stream_id is not None:
                self.state.set_experimental_receipt(current, approved=self.state.experimental_bet_action is True
                    and current.get("experimental_bet_action") is True and manual_capture.experimental_session_approved(
                    self.session_id, self.instance_id, root=self.root), deadline=self.deadline, session_id=self.stream_id)
            activity_pending = current.get("source_policy") in manual_capture.AUTOMATIC_POLICIES and current.get("activity_state") != "active"
            if activity_pending:
                with self.state.lock:
                    self.state._clear_analysis()
            snapshot = self.state.snapshot()
            if activity_pending:
                snapshot["observation"] = None
                if current["status"] in {"idle", "capturing"}:
                    snapshot["history"] = {**snapshot["history"], "state": "unavailable", "events": [], "counts": {}, "gaps": 0}
            snapshot["capture_session"] = {**current, "failure_reason": copy.deepcopy(self.failure_reason)
                                           if current.get("session_id") == self.session_id else None}
            snapshot["server"] = {**snapshot["server"], "instance_id": self.instance_id}
            partial = snapshot.get("partial_observation") or {}
            for capture in [partial.get("capture"), *(partial.get("field_captures") or {}).values()]:
                if capture is not None:
                    capture["service_instance_id"] = self.instance_id
                    if capture.get("capture_session_id") is None:
                        capture["capture_session_id"] = self.session_id
            snapshot["table_context"] = self.visual.context.snapshot(snapshot)
            snapshot["visual_observation"] = self.visual.snapshot(snapshot,
                occluded_regions=(snapshot["table_context"] or {}).get("occluded_regions", []))
            snapshot["numeric_observation"] = self.visual.numeric.snapshot(snapshot,
                occluded_regions=(snapshot["table_context"] or {}).get("occluded_regions", []))
            snapshot["numeric_diagnostics"] = {"attempts": self.visual.numeric.attempts,
                "dropped_frames": self.visual.numeric.dropped, "error": self.visual.numeric.last_error,
                "last_timing": copy.deepcopy(self.visual.numeric.last_timing)}
            self.visual.mask_snapshot(snapshot, snapshot["table_context"])
            snapshot["event_evidence"] = self.visual.archive.snapshot()
            snapshot["context_diagnostics"] = {"attempts": self.visual.context.attempts,
                "dropped_frames": self.visual.context.dropped, "error": self.visual.context.last_error,
                "log_complete": self.visual.context.log_complete, "log_bytes": self.visual.context.log_bytes,
                "log_path": str((self.visual.archive.directory / "context.jsonl").relative_to(self.root))}
            return snapshot

    def authorizes(self, session_id, instance_id):
        if instance_id != self.instance_id:
            return False
        # A native first request can precede the next passive tail tick. Joining
        # an already approved private receipt does not spawn/select a source.
        self.poll()
        with self.lock:
            current = manual_capture.public_snapshot(root=self.root)
            return (session_id == self.session_id and self.stream_id is not None
                    and not self.failed and self._valid(current))

    def poll(self):
        with self.lock:
            self._flush_stops()
            if self.closed.is_set():
                return
            current = manual_capture.public_snapshot(root=self.root)
            sid = current["session_id"]
            if sid != self.session_id:
                self._end("manual-session-replaced")
                self._flush_stops()
                self.session_id, self.path = sid, None
                self.offset, self.pending, self.deadline, self.failed = 0, b"", None, False
                self.failure_reason = self.validation_reason = None
                self.identity = None
                self.evidence_budget = self.evidence_last = None
                self.receipt_updated = self.receipt_elapsed = self.receipt_deadline = None
                self.candidate_updated = self.candidate_elapsed = None
                if (sid is None or sid in self.seen or len(self.seen) >= 256
                        or current["mode"] != "inference-enabled" or current["status"] != "capturing"):
                    return
                self.seen.add(sid)
                try:
                    path = manual_capture.session_path(sid, root=self.root)
                    approval = manual_capture.read_json(path / "approval.json")
                    policy = approval.get("source_policy", "manual")
                    consent = (policy == "manual" and approval.get("operator_assertion") in (None, manual_capture.ASSERTION)
                               and approval.get("automatic_assertion") is None
                               or policy in manual_capture.AUTOMATIC_POLICIES and approval.get("operator_assertion") is None
                                and approval.get("automatic_assertion") == (manual_capture.SUSTAINED_ASSERTION
                                    if policy == "automatic-sustained" else manual_capture.AUTOMATIC_ASSERTION))
                    sustained = policy == "automatic-sustained"
                    confirmed = approval.get("confirmed_at_unix_ms")
                    now = int(self.state.wall() * 1000)
                    budget = current.get("evidence") if sustained else current
                    if (type(approval.get("version")) is not int or approval["version"] != (2 if sustained else 1)
                            or approval.get("mode") != "inference-enabled"
                            or not consent or policy != current.get("source_policy", "manual")
                            or approval.get("inference_assertion") != manual_capture.INFERENCE_ASSERTION
                            or approval.get("service_instance_id") != self.instance_id
                            or type(confirmed) is not int or not 0 <= now - confirmed <= 30_000
                            or type(approval.get("max_seconds")) is not int
                            or type(approval.get("max_frames")) is not int
                            or approval["max_seconds"] * 1000 != budget["max_duration_ms"]
                            or approval.get("max_frames") != budget["max_frames"]
                            or sustained and (approval.get("experimental_bet_action") is not False
                                or current.get("experimental_bet_action") is not False)):
                        raise ValueError("invalid-manual-approval")
                    # Original receipt budget, frozen once. Status rewrites and wall
                    # clock changes never extend this process's monotonic deadline.
                    self.deadline = None if sustained else self.state.monotonic() + current["remaining_ms"] / 1000
                    if sustained:
                        self.evidence_budget = tuple(budget[key] for key in ("max_duration_ms", "max_frames", "max_bytes"))
                        self.evidence_last = dict(budget)
                    self.path = path
                    self.source_policy = policy
                    source = approval["source"]
                    self.identity = (source["exe_name"].lower(), source["process_id"], source["hwnd"].lower())
                    self.state.begin_stream(path / "ledger.jsonl")
                    self.stream_id = self.state.session_id
                except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
                    self._failure(error, "approval")
                    self.state.attach_blocked("manual-feed-approval-invalid")
                    return
            if self.path is not None and current["status"] == "capturing" and self.state.model["model_state"] != "ready":
                manual_capture.fail_session(sid, "model-not-ready", root=self.root)
                self._end("model-not-ready")
            if self.path is None or self.stream_id is None:
                return
            if not self._valid(current):
                self._end(current.get("stop_reason") or "manual-session-ended")
                self._flush_stops()
                return
            self.state.set_experimental_receipt(current, approved=self.state.experimental_bet_action is True
                and current.get("experimental_bet_action") is True and manual_capture.experimental_session_approved(
                self.session_id, self.instance_id, root=self.root), deadline=self.deadline, session_id=self.stream_id)
            if self.source_policy == "automatic-sustained":
                return  # Only the approved owner's bounded pipe may publish live rows.
            row = None
            try:
                # Bound both file growth and unread work. Lag fails closed rather
                # than turning an old backlog into a new live stream.
                filename = manual_capture.private_path(self.path / "stdout.jsonl", root=self.root)
                if not filename.exists():
                    return  # CLI publishes approval before spawning its child.
                size = filename.stat().st_size
                if size < self.offset or size > manual_capture.MAX_LOG or size - self.offset > 1024 * 1024:
                    raise ValueError("manual-feed-backlog")
                with filename.open("rb") as stream:
                    stream.seek(self.offset)
                    block = stream.read(MAX_RECORD)
                    self.offset = stream.tell()
                self.pending += block
                while b"\n" in self.pending:
                    line, self.pending = self.pending.split(b"\n", 1)
                    if len(line) > MAX_RECORD:
                        raise ValueError("manual-feed-size")
                    row = None
                    row = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
                    if not isinstance(row, dict):
                        raise ValueError("manual-feed-record")
                    self._ingest_row(row, current)
                    if self.stream_id is None:
                        self._flush_stops()
                        return
                if len(self.pending) > MAX_RECORD:
                    raise ValueError("manual-feed-size")
                latest = manual_capture.public_snapshot(root=self.root)
                if not self._valid(latest):
                    self._end(latest.get("stop_reason") or "manual-session-ended")
                    self._flush_stops()
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
                self._failure(error, "poll", row)
                self.failed = True
                self._end("manual-feed-failed")
                # A broken observer must not leave an invisible session collecting.
                manual_capture.fail_session(sid, "feed-failed", root=self.root)
                self._flush_stops()

    def _ingest_row(self, row, current):
        if not isinstance(row, dict):
            raise ValueError("manual-feed-record")
        if row.get("event") == "manual_capture":
            if type(row.get("version")) is not int or row["version"] != 1 or row.get("mode") != "inference-enabled":
                raise ValueError("manual-feed-mode")
            if row.get("stop_reason") is not None:
                self._end(code(row["stop_reason"], "manual-session-ended"))
            return
        if type(row.get("schema_version")) is not int or row["schema_version"] != 2 or row.get("event") not in manual_capture.FEED_EVENTS:
            raise ValueError("manual-feed-record")
        # Scoped invalidations are matched to their published ticket by DashboardState.
        if row["event"] != "partial_observation_invalidated":
            identity = (row.get("observation") or {}).get("identity", row.get("identity"))
            if identity is not None and (identity["exe_name"].lower(), identity["process_id"], identity["hwnd"].lower()) != self.identity:
                raise ValueError("manual-feed-source-mismatch")
        if row.get("service_instance_id") != self.instance_id:
            raise ValueError("manual-feed-instance-mismatch")
        if row.get("source_policy", "manual") != self.source_policy:
            raise ValueError("manual-feed-policy-mismatch")
        if self.source_policy in manual_capture.AUTOMATIC_POLICIES:
            activity = row.get("activity_state")
            if activity not in {"idle", "verifying", "active"}:
                raise ValueError("manual-feed-activity-invalid")
            if (row["event"] in {"observation", "history", "table", "decision"}
                    and (activity != "active" or current["activity_state"] != "active")
                    or row["event"] == "partial_observation" and activity == "idle"):
                return
            if row["event"] == "partial_observation" and current["activity_state"] != "active":
                row = {**row, "activity_state": "verifying"}
        if row["event"] == "visual_frame":
            self.visual.submit({**row, "capture_session_id": self.session_id}, self.stream_id,
                               self.state._target(row.get("identity")), self.state.version[1])
            return
        self.state.ingest(row, session_id=self.stream_id)

    def ingest_live(self, session_id, row):
        """Publish one pipe record under the same approval and typed-feed guards."""
        self.poll()
        with self.lock:
            current = manual_capture.public_snapshot(root=self.root)
            if (session_id != self.session_id or self.source_policy != "automatic-sustained"
                    or self.stream_id is None or not self._valid(current)):
                return False
            try:
                if row.get("event") == "manual_capture":
                    raise ValueError("unexpected-live-receipt")
                self._ingest_row(row, current)
                latest = manual_capture.public_snapshot(root=self.root)
                if self._valid(latest):
                    return True
                self._end(latest.get("stop_reason") or "manual-session-ended")
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
                self._failure(error, "live", row)
                self.failed = True
                self._end("manual-feed-failed")
                manual_capture.fail_session(session_id, "feed-failed", root=self.root)
            self._flush_stops()
            return False

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _run(self):
        while not self.closed.is_set():
            try:
                self.poll()
            except Exception as error:
                with self.lock:
                    self._failure(error, "worker")
                    self._end("manual-feed-failed")
                    self.failed = True
                    if self.path is not None:
                        try:
                            manual_capture.fail_session(self.session_id, "feed-failed", root=self.root)
                        except (OSError, ValueError):
                            pass  # Native/CLI deadlines and heartbeat expiry remain independent.
                return
            self.closed.wait(0.05)

    def stop(self):
        self.closed.set()
        try:
            self.visual.stop()
        finally:
            with self.lock:
                self._end("manual-feed-stopped")
                self._flush_stops()
        if self.thread is not None:
            self.thread.join(timeout=3)


def capture_argv(config):
    if not isinstance(config, dict):
        raise ValueError("invalid live config")
    allowed = {"binary", "exe_name", "pid", "window_hwnd", "window_title", "lobby_title", "lobby_size",
               "record_dir", "record_max_frames", "record_max_bytes", "record_interval_ms"}
    exe = config.get("exe_name")
    if (set(config) - allowed or not isinstance(exe, str) or not exe or len(exe) > 256
            or exe.startswith("-") or exe != exe.strip() or exe.endswith(".")
            or any(c in exe for c in '\\/:*?"<>|') or not exe.lower().endswith(".exe")):
        raise ValueError("live config needs an explicit executable identity")
    name = config.get("binary", "target/release/coinpoker.exe")
    if not isinstance(name, str):
        raise ValueError("invalid native binary")
    root = ROOT.resolve()
    supplied = root / name
    binary = supplied.resolve()
    if (binary != supplied or binary not in {root / "target" / build / "coinpoker.exe" for build in ("debug", "release")}
            or not binary.is_file()):
        raise ValueError("native binary must be a built coinpoker binary inside the checkout")
    argv = [str(binary)]
    flags = {"exe_name": "--exe-name", "pid": "--pid", "window_hwnd": "--window-hwnd",
             "window_title": "--table-title", "lobby_title": "--lobby-title", "lobby_size": "--lobby-size"}
    for field, flag in flags.items():
        if field not in config:
            continue
        value = config[field]
        if (type(value) not in (str, int) or not str(value) or len(str(value)) > 512
                or str(value) != str(value).strip() or str(value).startswith("-")
                or any(ord(c) < 32 or ord(c) == 127 or 0xd800 <= ord(c) <= 0xdfff for c in str(value))):
            raise ValueError("invalid live config value")
        if field == "pid" and (type(value) is not int or not 0 < value <= 0xffffffff):
            raise ValueError("invalid process identity")
        if field == "window_hwnd" and not (type(value) is int and 0 < value <= 0xffffffffffffffff
                or isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{1,16}", value) and int(value, 16) > 0):
            raise ValueError("invalid window identity")
        if field in ("exe_name", "window_title", "lobby_title", "lobby_size") and not isinstance(value, str):
            raise ValueError("invalid selector text")
        if field == "lobby_size" and (not isinstance(value, str) or not re.fullmatch(r"[1-9]\d{0,4}x[1-9]\d{0,4}", value)):
            raise ValueError("invalid lobby size")
        argv.extend((flag, str(value)))
    recording = {"record_max_frames": ("--record-max-frames", RECORD_MAX_FRAMES, 1, 20000),
                 "record_max_bytes": ("--record-max-bytes", RECORD_MAX_BYTES, 1, 2 * 1024 * 1024 * 1024),
                 "record_interval_ms": ("--record-interval-ms", RECORD_INTERVAL_MS, 250, 60000)}
    if "record_dir" in config:
        if config["record_dir"] != ".local/captures":
            raise ValueError("recording must use the private capture base")
        if not local_path(config["record_dir"]).is_relative_to(ROOT.resolve()):
            raise ValueError("recording base cannot leave the checkout")
        argv.extend(("--record-dir", ".local/captures"))
        for field, (flag, default, minimum, maximum) in recording.items():
            value = config.get(field, default)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("invalid recording bound")
            argv.extend((flag, str(value)))
    elif any(field in config for field in recording):
        raise ValueError("recording limits require a private recorder")
    return argv


class LiveFeed:
    def __init__(self, config_path, state, *, config=None):
        if config is None:
            selected = PracticeAttachment(config_path, root=ROOT).select()
            if not selected.ok:
                raise ValueError("capture selector unavailable")
            config = selected.config
        argv = capture_argv(config)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("COINPOKER_")}
        env.update(COINPOKER_VLM_ENDPOINT="http://127.0.0.1:18090/v1/laya/predict",
                   COINPOKER_VLM_MODEL=state.model["alias"])
        state.begin_stream(True)
        self.session_id = state.session_id
        self.state = state
        self.error = PrivateLedger(local_path(".local/history/" + state.session_id + "/feed.stderr.jsonl"),
                                   max_events=MAX_DIAGNOSTICS, max_bytes=MAX_DIAGNOSTIC_BYTES)
        self.process = None
        self.started = threading.Event()
        self.error_thread = threading.Thread(target=self._read_errors, daemon=True)
        self.thread = threading.Thread(target=self._read, daemon=True)
        try:
            # Start both drains before spawning: thread-start failure owns no child.
            self.error_thread.start()
            self.thread.start()
            self.process = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        except Exception:
            self.error.close()
            state.end_stream("feed-start-failed")
            raise
        finally:
            self.started.set()

    def _read_errors(self):
        self.started.wait()
        if self.process is None:
            return
        try:
            while raw := self.process.stderr.readline(MAX_RECORD + 1):
                if len(raw) > MAX_RECORD:
                    self.error.complete = False
                else:
                    self.error.append({"stderr": raw.decode("utf-8", errors="replace")})
        except (OSError, ValueError):
            self.error.complete = False
        finally:
            self.error.close()

    def is_running(self):
        return self.process.poll() is None and self.thread.is_alive()

    def _terminate(self):
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                    self.process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass

    def _read(self):
        self.started.wait()
        if self.process is None:
            return
        drain_feed(self.process.stdout, self.state, session_id=self.session_id)
        # A malformed/closed feed must not leave an invisible capture child running.
        self._terminate()

    def stop(self):
        self._terminate()
        if self.process.poll() is None:
            self.state.end_stream("feed-stop-failed")
            raise OSError("feed-stop-failed")
        self.thread.join(timeout=3)
        self.error_thread.join(timeout=3)
        if self.thread.is_alive() or self.error_thread.is_alive():
            self.state.end_stream("feed-stop-failed")
            raise OSError("feed-stop-failed")
        self.process.stdout.close()
        self.process.stderr.close()
        self.error.close()
        self.state.end_stream("feed-stopped", session_id=self.session_id)


class AutoAttachFeed:
    """Own one passive child. An identity is attempted at most once per supervisor."""

    def __init__(self, profile_path, state, *, selector=None, feed_factory=None,
                 diagnostics_path=None, poll_seconds=1.0):
        self.selector = selector if selector is not None else PracticeAttachment(profile_path, root=ROOT)
        self.feed_factory = feed_factory if feed_factory is not None else LiveFeed
        self.state = state
        self.feed = self.key = None
        self.attempted = set()
        self.diagnosed = set()
        if diagnostics_path is None:
            diagnostics_path = ".local/history/auto-attach-" + uuid.uuid4().hex + "/diagnostics.jsonl"
        self.diagnostics = PrivateLedger(local_path(diagnostics_path), max_events=MAX_DIAGNOSTICS,
                                         max_bytes=MAX_DIAGNOSTIC_BYTES)
        self.poll_seconds = poll_seconds
        self.closed = threading.Event()
        self.thread = None
        self.lock = threading.RLock()

    def _diagnose(self, reason, key=None, details=None):
        marker = (reason, key)
        if marker in self.diagnosed:
            return
        if len(self.diagnosed) >= MAX_DIAGNOSTICS:
            self.diagnostics.complete = False
            return
        self.diagnosed.add(marker)
        self.diagnostics.append({"code": reason, "key": key, "details": details})

    def _stop_feed(self, reason):
        if self.feed is not None:
            try:
                self.feed.stop()
            except Exception:
                self.closed.set()
                self.state.end_stream("feed-stop-failed")
                self._diagnose("feed-stop-failed", self.key)
                return False
            self.feed = None
            self.state.end_stream(reason)
            self._diagnose(reason, self.key)
            self.key = None
        return True

    def poll(self):
        with self.lock:
            if self.closed.is_set():
                return
            with self.state.lock:
                ready = self.state.model["model_state"] == "ready"
            if not ready:
                self._stop_feed("model-not-ready")
                self.state.attach_blocked("model-not-ready")
                self._diagnose("model-not-ready")
                return
            try:
                result = self.selector.select()
                reason = code(result.code, "attach-selection-failed")
                key = result.key if result.ok else None
                if key is not None:
                    hash(key)
                self._diagnose(reason, key, result.private_diagnostics)
            except Exception:
                self._stop_feed("attach-selection-failed")
                self.state.attach_blocked("attach-selection-failed")
                self._diagnose("attach-selection-failed")
                return
            if self.feed is not None:
                if not result.ok or key != self.key:
                    if not self._stop_feed("attach-target-changed" if result.ok else reason):
                        return
                elif self.feed.is_running():
                    return
                else:
                    self._stop_feed("feed-exited")
            if not result.ok or key is None:
                self.state.attach_blocked(reason if not result.ok else "attach-selection-failed")
                return
            if key in self.attempted or len(self.attempted) >= MAX_DIAGNOSTICS:
                self.state.attach_blocked("attach-retry-suppressed")
                self._diagnose("attach-retry-suppressed", key)
                return
            # Consume before construction: failed starts cannot reset recorder caps.
            self.attempted.add(key)
            try:
                self.feed = self.feed_factory(None, self.state, config=result.config)
                self.key = key
                self._diagnose("feed-started", key)
            except Exception:
                self.state.end_stream("feed-start-failed")
                self.state.attach_blocked("feed-start-failed")
                self._diagnose("feed-start-failed", key)

    def start(self):
        with self.lock:
            if self.thread is None and not self.closed.is_set():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def _run(self):
        while not self.closed.is_set():
            try:
                self.poll()
            except Exception:
                with self.lock:
                    self._stop_feed("attach-supervisor-failed")
                self.state.attach_blocked("attach-supervisor-failed")
            self.closed.wait(self.poll_seconds)

    def stop(self):
        self.closed.set()
        if self.thread is not None:
            self.thread.join(timeout=6)
        with self.lock:
            self._stop_feed("feed-stopped")
            self.diagnostics.close()


def references():
    path = ROOT / "scripts/dashboard/reference.json"
    if path.stat().st_size > MAX_RECORD:
        raise ValueError("reference exceeds response bound")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid reference schema")
    return value


def replay():
    frames = []
    for step, title in enumerate(("Waiting: no offered controls", "Hero turn: several buttons coexist",
                                  "Turn changed: controls and advice cleared")):
        state = DashboardState("coinpoker-laya-vision").snapshot()
        state.update(source="demo", session_id="demo-buttons", event_seq=step, message=title)
        if step == 1:
            controls = unknown_controls()
            for item in controls:
                if item["action"] in ("fold", "call", "raise"):
                    item.update(presence="present", enabled="enabled")
            state["observation"] = {"generation": 1, "epoch": 1, "game_phase": "flop",
                                    "hero_cards": [{"rank": "A", "suit": "hearts"}, {"rank": "K", "suit": "hearts"}],
                                    "board": [{"rank": "Q", "suit": "hearts"}, {"rank": "J", "suit": "hearts"},
                                              {"rank": "2", "suit": "clubs"}],
                                    "amounts": {"pot_size": 300, "to_call": 100, "hero_chips": 1000,
                                                "min_raise_to": 200, "max_raise_to": 1000},
                                    "available_actions": ["fold", "call", "raise"], "controls": controls,
                                    "action_required": True, "experimental": True,
                                    "expires_at_unix_ms": None, "remaining_ms": None}
        frames.append(state)
    return {"source": "demo", "scenarios": [{"id": "multi-label-controls", "title": "Controls versus advice",
                                                "description": "Synthetic presentation fixture, not model accuracy or live guidance.",
                                                "frames": frames}]}
