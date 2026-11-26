from copy import deepcopy
import json
from pathlib import Path
import unittest

from research.backtest import stamp
from research.sector_financials import chart_svg, overview_svg, sector_financials
from research.staged import Screen


ROOT = Path(__file__).resolve().parents[1]


class FinancialBasketTest(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / "examples/sector-financials-demo.json").read_text())
        self.config = self.payload["sector_financials"]
        self.basket = self.config["baskets"]["entertainment"]

    def report(self):
        return sector_financials(self.config, stamp(self.payload["cutoff"]))

    def latest(self):
        return self.report()["sectors"]["entertainment"]["latest"]

    def test_totals_and_breadth(self):
        r = self.report()
        p = self.latest()
        self.assertEqual(len(r["sectors"]), 10)
        self.assertEqual(len(r["sectors"]["entertainment"]["history"]), 8)
        self.assertEqual(p["revenue"], 2050000000000)
        self.assertEqual(p["operating_profit"], 470000000000)
        self.assertEqual(p["both_improved"], 3)
        self.assertEqual(p["status"], "pass")
        self.assertIn("가상 데이터", chart_svg(r, "entertainment", demo=True))

    def test_incomplete_does_not_reuse_older_quarter(self):
        self.basket["observations"][-1]["available_at"] = "2026-12-01T08:00:00+09:00"
        p = self.latest()
        self.assertEqual(p["coverage"], 3)
        self.assertIsNone(p["revenue"])
        self.assertEqual(p["status"], "unknown")

    def test_one_company_driven_aggregate_does_not_pass(self):
        p = self.latest()
        self.assertEqual(p["both_improved"], 3)
        for row in self.basket["observations"][-3:]:
            row.update(revenue=100_000_000_000, operating_profit=-9_000_000_000)
        p = self.latest()
        self.assertGreater(p["revenue_yoy_pct"], 0)
        self.assertGreater(p["operating_profit_delta"], 0)
        self.assertEqual(p["both_improved"], 1)
        self.assertEqual(p["status"], "hold")

    def test_late_revisions_and_estimates(self):
        row = deepcopy(self.basket["observations"][-1])
        row.update(available_at="2026-11-22T09:00:00+09:00", revenue=1, grade="estimate")
        self.basket["observations"].append(row)
        self.assertEqual(self.latest()["revenue"], 2050000000000)
        row["grade"] = "actual"
        self.assertEqual(self.latest()["revenue"], 1960000000001)

    def test_missing_prior_and_sign_transition(self):
        self.assertEqual(self.latest()["profit_transition"], "turned_profitable")
        self.assertIsNone(self.latest()["operating_profit_yoy_pct"])
        self.basket["observations"] = [o for o in self.basket["observations"] if o["quarter"] != "2025-Q3"]
        self.assertEqual(self.latest()["status"], "unknown")
        self.assertIsNotNone(self.latest()["revenue"])
        self.assertIsNone(self.latest()["both_improved"])

    def test_bad_scope_or_membership(self):
        self.basket["observations"][0]["scope"] = "segment:other"
        with self.assertRaises(ValueError):
            self.report()
        self.basket["observations"][0]["scope"] = "consolidated"
        self.basket["members"][-1]["symbol"] = "OTHER"
        with self.assertRaises(ValueError):
            self.report()

    def test_actual_entertainment_fixture(self):
        data = json.loads((ROOT / "examples/sector-financials-entertainment-2026q3.json").read_text())
        result = sector_financials(data["sector_financials"], stamp(data["cutoff"]))
        ent = result["sectors"]["entertainment"]
        self.assertTrue(all(q["coverage"] == 4 for q in ent["history"]))
        self.assertEqual(ent["latest"]["revenue"], 2237830798636)
        self.assertEqual(ent["latest"]["operating_profit"], 283556506129)
        self.assertEqual(ent["latest"]["both_improved"], 2)
        self.assertEqual(ent["status"], "hold")
        svg = overview_svg(result)
        from xml.etree.ElementTree import fromstring
        fromstring(svg)
        self.assertIn("비교 가능 1/10개 섹터", svg)
        self.assertEqual(svg.count("미집계</text>"), 9)
        for label in ("반도체", "조선", "게임", "엔터", "+53.9%", "+263.9%", "2/4사", "혼조"):
            self.assertIn(label, svg)

    def test_five_member_sector(self):
        games = deepcopy(self.basket)
        games["members"].append({"symbol": "EXAMPLE-5", "scope": "segment:games"})
        self.config["baskets"]["games"] = games
        self.assertEqual(self.report()["sectors"]["games"]["latest"]["coverage"], 4)
        self.assertEqual(self.report()["sectors"]["games"]["status"], "unknown")
        games["observations"].extend(
            dict(row, symbol="EXAMPLE-5", scope="segment:games")
            for row in list(games["observations"]) if row["symbol"] == "352820")
        self.assertEqual(self.report()["sectors"]["games"]["latest"]["both_improved"], 4)
        self.assertEqual(self.report()["sectors"]["games"]["status"], "pass")

    def test_staged_pipeline_uses_sector_without_company_data(self):
        payload = json.loads((ROOT / "examples/staged-research.json").read_text())
        payload["cutoff"] = "2026-11-27T08:00:00+09:00"
        payload["sector_financials"] = self.config
        for row in payload["universe"]:
            row["sector"] = "entertainment"
        s = Screen(payload)
        sym = next(iter(s.universe))
        self.assertEqual(s.sector_gate(sym, "entertainment")["status"], "pass")
        self.assertEqual(s.sector_gate(sym, "games")["status"], "unknown")
        self.assertEqual(s.run()["sector_financial_report"]["report_quarter"], "2026-Q3")


if __name__ == "__main__":
    unittest.main()
