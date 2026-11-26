import json
from pathlib import Path
import subprocess
import sys
import unittest

from research.staged import Screen

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "staged-research.json"


class StagedResearchTest(unittest.TestCase):
    def setUp(self):
        self.p = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def evidence(self, kind):
        return next(e for e in self.p["evidence"] if e["kind"] == kind)

    def run_one(self):
        return Screen(self.p).run()["candidates"][0]

    def test_all_stages_and_derived_metrics(self):
        row = self.run_one()
        self.assertEqual(row["status"], "review")
        self.assertEqual(list(row["stages"]), ["macro", "sector", "chart", "company"])
        self.assertEqual(row["illustrative_max_weight"], .5)
        self.assertEqual(row["stages"]["company"]["fcf"], 380)
        self.assertEqual(row["stages"]["company"]["trailing_pe"], 10.6)
        self.assertEqual(row["stages"]["chart"]["reasons"], ["new_bullish_alignment"])

    def test_macro_reduces_and_blocks(self):
        self.evidence("fx")["values"]["usd_local_change_pct"] = .5
        self.evidence("credit")["values"]["hy_oas_change_bp"] = 10.
        self.assertEqual(self.run_one()["illustrative_max_weight"], .25)
        self.evidence("rates")["values"]["us_10y_change_bp"] = 10.
        row = self.run_one()
        self.assertEqual(row["first_blocker"], "macro")
        self.assertEqual(row["stages"]["company"]["status"], "skipped")
        self.assertIsNone(row["illustrative_max_weight"])

    def test_macro_missing_expired(self):
        x = self.evidence("credit")
        x["period_end"] = "2026-01-02T15:30:00+09:00"
        self.assertEqual(self.run_one()["stages"]["macro"]["status"], "unknown")

    def test_relative_strength_is_optional_sector_context_only(self):
        self.evidence("breadth")["values"]["sector_vs_benchmark_pct"] = -25
        row = self.run_one()
        self.assertEqual(row["stages"]["macro"]["adverse"], [])
        self.assertEqual(row["stages"]["sector"]["status"], "pass")
        info = row["stages"]["sector"]["relative_strength"]
        self.assertEqual(info["values"]["sector_vs_benchmark_pct"], -25)
        self.p["evidence"].remove(self.evidence("breadth"))
        row = self.run_one()
        self.assertEqual(row["status"], "review")
        self.assertIsNone(row["stages"]["sector"]["relative_strength"])

    def test_missing_rates_not_replaced_by_semis(self):
        self.p["evidence"].remove(self.evidence("rates"))
        row = self.run_one()
        self.assertEqual(row["first_blocker"], "macro")
        self.assertEqual(row["stages"]["macro"]["reasons"], ["rates"])

    def test_sector_mixed_and_declining(self):
        self.evidence("orders")["values"]["orders_change_pct"] = -1.
        self.assertEqual(self.run_one()["stages"]["sector"]["status"], "hold")
        self.evidence("breadth")["values"]["sector_vs_benchmark_pct"] = 25
        self.evidence("contract_price")["values"]["price_change_pct"] = -1.
        self.assertEqual(self.run_one()["stages"]["sector"]["status"], "fail")

    def test_late_vintage_and_old_revision_no_lookahead(self):
        e = self.evidence("orders")
        self.p["evidence"].extend([
            {**e, "available_at": "2026-02-02T15:30:00+09:00",
             "values": {"orders_change_pct": -100}},
            {**e, "period_end": "2025-12-25T15:30:00+09:00",
             "values": {"orders_change_pct": -100}},
        ])
        self.assertEqual(self.run_one()["stages"]["sector"]["status"], "pass")
        e["available_at"] = "2026-02-02T14:00:00+09:00"
        self.assertEqual(self.run_one()["stages"]["sector"]["status"], "hold")

    def test_missing_or_delayed_bar_does_not_compress_history(self):
        self.p["bars"][7]["available_at"] = "2026-02-02T15:30:00+09:00"
        self.assertEqual(self.run_one()["stages"]["chart"]["status"], "unknown")
        del self.p["bars"][7]
        self.assertEqual(self.run_one()["first_blocker"], "chart")

    def test_ongoing_bullish_alignment_is_not_new(self):
        self.p["bars"][-2]["close"] = 104
        row = self.run_one()
        self.assertEqual(row["stages"]["chart"]["reasons"], ["existing_alignment_not_new"])
        self.assertEqual(row["stages"]["company"]["status"], "skipped")

    def test_company_financial_failure_or_no_publication(self):
        fin = self.evidence("financials")
        fin["values"]["capex"] = 601
        row = self.run_one()
        self.assertEqual(row["first_blocker"], "company")
        self.assertIn("fcf_positive", row["stages"]["company"]["reasons"])
        fin["available_at"] = "2026-02-02T15:30:00+09:00"
        self.assertEqual(self.run_one()["stages"]["company"]["status"], "unknown")

    def test_other_sector_does_not_substitute(self):
        self.evidence("orders")["key"] = "NAND"
        self.assertEqual(self.run_one()["stages"]["sector"]["status"], "unknown")

    def test_reject_after_hours_bar(self):
        self.p["bars"][-1]["session"] = "NXT"
        with self.assertRaisesRegex(ValueError, "regular close"):
            Screen(self.p)

    def test_cli_example(self):
        out = subprocess.check_output(
            [sys.executable, "-m", "research.staged", "--input", str(FIXTURE)], cwd=ROOT)
        self.assertEqual(json.loads(out)["candidates"][0]["status"], "review")


if __name__ == "__main__":
    unittest.main()
