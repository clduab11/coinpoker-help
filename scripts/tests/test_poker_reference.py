import datetime as dt
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit


REFERENCE_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "reference.json"
EXPECTED_SECTIONS = {
    "hand-rankings", "pot-odds", "outs-and-draws", "six-max-positions",
    "opening-examples", "facing-raises", "glossary", "limits-and-sources",
}


def expand_range(text):
    ranks = "23456789TJQKA"
    hands = set()
    for token in text.split(", "):
        if not re.fullmatch(r"[2-9TJQKA]{2}[so]?\+?", token):
            raise ValueError("Invalid hand notation: " + token)
        base = token.rstrip("+")
        high, low = (ranks.index(card) for card in base[:2])
        if high == low:
            if len(base) != 2:
                raise ValueError("Pocket pairs cannot have a suit suffix")
            expanded = {ranks[i] * 2 for i in range(high, 13)} if token.endswith("+") else {base}
        else:
            if high < low or len(base) != 3:
                raise ValueError("Non-pairs need descending ranks and s/o")
            expanded = {ranks[high] + ranks[i] + base[2] for i in range(low, high)} if token.endswith("+") else {base}
        if hands & expanded:
            raise ValueError("Duplicate range entries: " + token)
        hands.update(expanded)
    return hands


class PokerReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = REFERENCE_PATH.read_text(encoding="ascii")
        cls.reference = json.loads(cls.raw)
        cls.sections = {section["id"]: section for section in cls.reference["sections"]}

    def test_schema_and_compact_ascii_content(self):
        self.assertEqual(set(self.reference), {
            "schema_version", "title", "scope", "reviewed_utc", "sources", "sections",
        })
        self.assertEqual(type(self.reference["schema_version"]), int)
        self.assertEqual(self.reference["schema_version"], 1)
        self.assertLess(len(self.raw.encode("ascii")), 48 * 1024)
        for name in ("title", "scope", "reviewed_utc"):
            self.assertIsInstance(self.reference[name], str)
            self.assertTrue(self.reference[name])
        reviewed = dt.datetime.fromisoformat(self.reference["reviewed_utc"].replace("Z", "+00:00"))
        self.assertEqual(reviewed.utcoffset(), dt.timedelta(0))
        self.assertLessEqual(reviewed, dt.datetime.now(dt.timezone.utc))
        self.assertEqual(set(self.sections), EXPECTED_SECTIONS)
        self.assertEqual(len(self.sections), len(self.reference["sections"]))
        for section in self.sections.values():
            with self.subTest(section=section["id"]):
                self.assertEqual(set(section), {
                    "id", "title", "scope", "paragraphs", "bullets", "tables", "source_ids",
                })
                self.assertRegex(section["id"], r"^[a-z][a-z0-9-]*$")
                self.assertTrue(section["title"])
                self.assertTrue(section["scope"])
                for field in ("paragraphs", "bullets", "tables", "source_ids"):
                    self.assertIsInstance(section[field], list)
                self.assertTrue(section["paragraphs"] or section["bullets"] or section["tables"])
                for text in section["paragraphs"] + section["bullets"]:
                    self.assertIsInstance(text, str)
                    self.assertTrue(text.isascii())
                    self.assertTrue(text.strip())
                    self.assertLess(len(text), 1000)

    def test_traceable_citations_and_sane_links(self):
        sources = self.reference["sources"]
        self.assertGreaterEqual(len(sources), 4)
        self.assertLessEqual(len(sources), 16)
        by_id = {source["id"]: source for source in sources}
        self.assertEqual(len(by_id), len(sources))
        self.assertGreaterEqual(len({source["publisher"] for source in sources}), 4)
        allowed_hosts = {"www.pokernews.com", "upswingpoker.com", "www.pokerology.com", "blog.gtowizard.com"}
        for source in sources:
            self.assertEqual(set(source), {"id", "title", "url", "publisher"})
            for value in source.values():
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip())
                self.assertTrue(value.isascii())
            self.assertRegex(source["id"], r"^[a-z][a-z0-9-]*$")
            url = urlsplit(source["url"])
            self.assertEqual(url.scheme, "https")
            self.assertIn(url.hostname, allowed_hosts)
            self.assertIsNone(url.username)
            self.assertIsNone(url.password)
            self.assertIsNone(url.port)
            self.assertNotIn(url.path, ("", "/"))
            self.assertFalse(url.query or url.fragment)
        cited = set()
        for section in self.sections.values():
            self.assertTrue(section["source_ids"])
            self.assertEqual(len(section["source_ids"]), len(set(section["source_ids"])))
            self.assertLessEqual(set(section["source_ids"]), set(by_id))
            cited.update(section["source_ids"])
        self.assertEqual(cited, set(by_id))

    def test_table_widths_and_finite_cells(self):
        for section in self.sections.values():
            for table in section["tables"]:
                with self.subTest(section=section["id"], table=table["caption"]):
                    self.assertEqual(set(table), {"caption", "columns", "rows"})
                    self.assertIsInstance(table["caption"], str)
                    self.assertTrue(table["caption"])
                    self.assertIsInstance(table["columns"], list)
                    self.assertIsInstance(table["rows"], list)
                    self.assertGreaterEqual(len(table["columns"]), 2)
                    self.assertLessEqual(len(table["columns"]), 6)
                    self.assertGreater(len(table["rows"]), 0)
                    self.assertLessEqual(len(table["rows"]), 20)
                    self.assertEqual(len(table["columns"]), len(set(table["columns"])))
                    for column in table["columns"]:
                        self.assertIsInstance(column, str)
                        self.assertTrue(column.strip())
                    for row in table["rows"]:
                        self.assertIsInstance(row, list)
                        self.assertEqual(len(row), len(table["columns"]))
                        for cell in row:
                            self.assertIn(type(cell), (str, int, float))
                            if isinstance(cell, str):
                                self.assertTrue(cell.strip())
                                self.assertTrue(cell.isascii())
                                self.assertLess(len(cell), 300)
                            else:
                                self.assertTrue(math.isfinite(cell))

    def test_pot_odds_tables_match_exact_fractions(self):
        table = self.sections["pot-odds"]["tables"][0]
        self.assertEqual(table["columns"], ["Pot now P", "Extra call C", "Final pot P+C", "Break-even equity %"])
        expected_inputs = [(150, 50), (175, 75), (200, 100), (250, 150), (300, 200), (3.75, 1.25)]
        self.assertEqual([(row[0], row[1]) for row in table["rows"]], expected_inputs)
        for pot, call, final, percent in table["rows"]:
            with self.subTest(pot=pot, call=call):
                pot, call = Fraction(str(pot)), Fraction(str(call))
                self.assertGreater(pot, 0)
                self.assertGreater(call, 0)
                self.assertEqual(Fraction(str(final)), pot + call)
                self.assertAlmostEqual(percent, float(100 * call / (pot + call)), delta=0.0000005)
        self.assertEqual(table["rows"][0], [150, 50, 200, 25])
        self.assertEqual(table["rows"][-1], [3.75, 1.25, 5, 25])
        text = " ".join(self.sections["pot-odds"]["paragraphs"] + self.sections["pot-odds"]["bullets"]).lower()
        for phrase in ("includes the opponent's bet", "excludes the caller's unpaid call", "extra price", "no rake", "no further betting", "eligible pot"):
            self.assertIn(phrase, text)

    def test_draw_table_matches_combination_and_sequential_formulas(self):
        table = self.sections["outs-and-draws"]["tables"][1]
        self.assertEqual(table["columns"], ["Outs", "Flop -> turn %", "Turn -> river %", "Flop -> river %", "Rule of 2 %", "Rule of 4 %"])
        self.assertEqual([row[0] for row in table["rows"]], [2, 4, 6, 8, 9, 15])
        for outs, flop_turn, turn_river, flop_river, rule_two, rule_four in table["rows"]:
            with self.subTest(outs=outs):
                exact = 1 - Fraction(math.comb(47 - outs, 2), math.comb(47, 2))
                sequential = Fraction(outs, 47) + Fraction(47 - outs, 47) * Fraction(outs, 46)
                self.assertEqual(exact, sequential)
                for actual, expected in zip((flop_turn, turn_river, flop_river), (Fraction(outs, 47), Fraction(outs, 46), exact)):
                    self.assertAlmostEqual(actual, float(100 * expected), delta=0.0000005)
                self.assertEqual((rule_two, rule_four), (2 * outs, 4 * outs))
        text = " ".join(self.sections["outs-and-draws"]["paragraphs"] + self.sections["outs-and-draws"]["bullets"]).lower()
        for phrase in ("distinct cards once", "dirty outs", "only the turn", "uniform", "fixed", "not an equity calculator", "known dead"):
            self.assertIn(phrase, text + " " + self.sections["outs-and-draws"]["scope"].lower())
        self.assertEqual(Fraction(378, 1081), 1 - Fraction(math.comb(38, 2), math.comb(47, 2)))
        self.assertGreater(60 - table["rows"][-1][3], 5)

    def test_six_max_rfi_positions_and_applicability_are_separate(self):
        positions = self.sections["six-max-positions"]
        self.assertEqual([row[0] for row in positions["tables"][0]["rows"]], ["UTG", "HJ", "CO", "BTN", "SB", "BB"])
        self.assertEqual([row[1] for row in positions["tables"][0]["rows"]], list(range(1, 7)))
        context = " ".join(positions["paragraphs"] + positions["bullets"]).lower()
        self.assertIn("lj (lojack)", context)
        self.assertIn("hj is the next seat", context)
        self.assertIn("bb has no raise-first-in opportunity", context)
        examples = self.sections["opening-examples"]
        rows = examples["tables"][0]["rows"]
        self.assertEqual([row[0] for row in rows], ["UTG", "HJ", "CO", "BTN", "SB"])
        self.assertEqual([row[1] for row in rows], [2.5, 2.5, 2.5, 2.5, 3])
        ranges = {position: expand_range(text) for position, _, text in rows}
        for earlier, later in zip(("UTG", "HJ", "CO"), ("HJ", "CO", "BTN")):
            self.assertLess(ranges[earlier], ranges[later])
        self.assertNotEqual(ranges["SB"], ranges["BTN"])
        for hands in ranges.values():
            self.assertIn("AA", hands)
            self.assertIn("AKs", hands)
        self.assertEqual(expand_range("97s+"), {"97s", "98s"})
        self.assertEqual(expand_range("ATo+"), {"ATo", "AJo", "AQo", "AKo"})
        text = " ".join(examples["paragraphs"] + examples["bullets"] + [examples["scope"]]).lower()
        for phrase in ("unopened", "six-max cash", "100bb", "effective", "no antes", "rake", "opponents", "opening size", "strategy opinion", "not live recommendations or an exact solver", "independently authored", "limping", "or responses to a raise"):
            self.assertIn(phrase, text)

    def test_ranking_and_raise_nuance_is_not_live_advice(self):
        ranking = self.sections["hand-rankings"]
        self.assertEqual([row[1] for row in ranking["tables"][0]["rows"]], [
            "Royal flush", "Straight flush", "Four of a kind", "Full house", "Flush", "Straight",
            "Three of a kind", "Two pair", "One pair", "High card",
        ])
        text = " ".join(ranking["paragraphs"] + ranking["bullets"]).lower()
        for phrase in ("zero, one, or two", "five-high", "does not wrap", "sixth or seventh", "suits do not rank", "split"):
            self.assertIn(phrase, text)
        facing = self.sections["facing-raises"]
        text = " ".join(facing["paragraphs"] + facing["bullets"]).lower()
        for phrase in ("big blind as the first", "opening raise as the second", "calls do not increment", "not automatically all-in", "aa", "fold equity", "effective stack", "sunk costs", "150bb"):
            self.assertIn(phrase, text)
        totals = [row[1] for row in facing["tables"][0]["rows"]]
        increments = [new - old for old, new in zip(totals, totals[1:])]
        self.assertGreaterEqual(increments[0], totals[0])
        self.assertEqual(increments, sorted(increments))
        self.assertLess(totals[3], 100)
        scope = self.reference["scope"].lower()
        self.assertIn("offline educational", scope)
        self.assertIn("not live recommendations", scope)
        self.assertIn("perception validation", scope)
        self.assertIn("advice activation", scope)

    def test_no_copied_root_range_or_runtime_asset_dependency(self):
        lower = self.raw.lower()
        for marker in (".png", ".jpg", ".webp", ".pdf", "file://", "data:", "wp-content", "<script", "<img", "<iframe", "../", "c:\\"):
            self.assertNotIn(marker, lower)
        limits = self.sections["limits-and-sources"]
        text = " ".join(limits["paragraphs"] + limits["bullets"]).lower()
        for phrase in ("no runtime network", "not copied", "independently", "does not enable advice", "validates screenshots", "short-deck", "icm"):
            self.assertIn(phrase, text)

    def test_browser_bundle_exactly_matches_reference_source(self):
        app = (REFERENCE_PATH.parent / "app.js").read_text(encoding="ascii")
        begin, end = "/* BEGIN BUNDLED REFERENCE */", "/* END BUNDLED REFERENCE */"
        self.assertEqual(app.count(begin), 1)
        self.assertEqual(app.count(end), 1)
        block = app.split(begin, 1)[1].split(end, 1)[0]
        match = re.fullmatch(r"\s*const\s+LOCAL_REFERENCE\s*=\s*(\{.*\})\s*;\s*", block, flags=re.S)
        self.assertIsNotNone(match, "Reference must be locally bundled as a JSON literal")
        self.assertEqual(json.loads(match.group(1)), self.reference)


if __name__ == "__main__":
    unittest.main()
