#!/usr/bin/env python3
"""Generate fictional pixels + scripted envelopes. Not CoinPoker screenshots."""
import copy
import json
from pathlib import Path


def main():
    cases = []
    identity = {"exe_name": "Synthetic.exe", "process_id": 42, "hwnd": "0x7"}
    empty_evidence = {"table_layout": False, "hero_cards": False, "board_area": False, "pot": False, "action_controls": False, "readable": True}
    def add(name, kind, state, tags, *, response=None, metadata="candidate", sequence=None, allowed=False, fresh=None):
        evidence = dict(empty_evidence)
        if kind == "poker_table":
            evidence.update(table_layout=True, board_area=True, pot=True, hero_cards=bool(state and state["hero_cards"]), action_controls=bool(state and state["action_required"]))
        row = {"id": name, "sequence": sequence or name, "identity": dict(identity), "metadata": metadata,
               "expected_kind": kind, "expected_state": state, "recommendation_allowed": allowed, "tags": tags,
               "image": None, "synthetic_image": {"width": 320, "height": 240, "seed": 7},
               "response": response or {"screen_kind": kind, "evidence": evidence, "state": state}, "freshness": fresh}
        cases.append(row)
    add("lobby", "lobby", None, ["lobby"], metadata="lobby_title")
    add("dialog", "other_coin_poker_window", None, ["dialog"])
    add("ambiguous-screen", "unknown", None, ["unknown", "obscured"])
    board = [{"rank": r, "suit": s} for r, s in [("Q","clubs"),("7","diamonds"),("2","spades"),("9","hearts"),("J","clubs")]]
    for phase, count in [("preflop",0),("flop",3),("turn",4),("river",5),("showdown",5)]:
        for required in ([False,True] if phase != "showdown" else [False]):
            state = {"game_phase": phase, "hero_cards": [{"rank":"A","suit":"spades"},{"rank":"K","suit":"hearts"}], "board": board[:count],
                     "pot_size":1000,"to_call":0,"hero_chips":5000,"min_raise_to":500 if required else None,"max_raise_to":5000 if required else None,
                     "players":[{"name":"Hero","chips":5000,"last_action":"check","bet_amount":0},{"name":"Seat1","chips":5000,"last_action":"check","bet_amount":0}],
                     "action_required":required,"available_actions":["check","raise"] if required else []}
            sequence = phase + ("-hero" if required else "-waiting")
            for repeat in [1,2]:
                add(sequence+str(repeat),"poker_table",copy.deepcopy(state),[phase,"cash" if required else "tournament","hero_turn" if required else "non_hero_turn"], metadata="table_title",sequence=sequence,allowed=required and repeat==2)
                if not required:
                    cases[-1]["synthetic_image"] = {"width":640,"height":480,"seed":7}
                    cases[-1]["tags"].append("high_dpi")
    unreadable = {"screen_kind":"poker_table","evidence":{**empty_evidence,"table_layout":True,"readable":False},"state":None}
    add("unreadable-table","poker_table",None,["unreadable","animation"],response=unreadable)
    # These exercise the identical freshness predicate used by the runtime, not
    # the HTTP worker timing. The Rust mock-runtime suite tests actual queuing.
    for issue in ["generation", "identity", "age", "capture"]:
        fresh = {"generation":1,"current_generation":1,"epoch":1,"current_epoch":1,"age_ms":100,"current_identity":dict(identity),"fresh_capture":True,"expected_fresh":False}
        if issue == "generation": fresh["current_generation"] = 2
        if issue == "identity": fresh["current_identity"]["hwnd"] = "0x63"
        if issue == "age": fresh["age_ms"] = 5001
        if issue == "capture": fresh["fresh_capture"] = False
        add("stale-"+issue,"poker_table",copy.deepcopy(cases[5]["expected_state"]),["stale", "closed_reopened" if issue == "identity" else "inference_change"],fresh=fresh)
    path = Path(__file__).resolve().parents[1] / "fixtures/synthetic/manifest.json"
    path.write_text(json.dumps({"format":2,"source":"synthetic","cases":cases},indent=2)+"\n",encoding="utf-8")
    print(f"Generated {len(cases)} synthetic contract fixtures (not visual accuracy evidence)")

if __name__ == "__main__":
    main()
