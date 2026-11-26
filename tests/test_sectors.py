import json
from pathlib import Path
import subprocess
import sys
import unittest

from research.backtest import stamp
from research.sectors import screen_sectors
from research.staged import Screen

ROOT = Path(__file__).resolve().parents[1]
NOW = stamp("2026-11-27T07:45:00+09:00")


def row(profile, metric, value, period="2026-Q3", grade="observed", scope="stable-sample",
        unit="%", comparison="qoq", available_at="2026-11-10T12:00:00+09:00"):
    return dict(profile=profile, metric=metric, value=value, period=period, grade=grade,
                scope=scope, unit=unit, comparison=comparison, available_at=available_at,
                source="synthetic test", note="test input")


def pick(r, key):
    return next(p for s in r["sectors"] for p in s["profiles"] if p["key"] == key)


class SectorTest(unittest.TestCase):
    def test_all_sectors_and_separate_memory(self):
        report = screen_sectors([], NOW)
        self.assertEqual(len(report["sectors"]), 10)
        self.assertEqual([p["key"] for p in report["sectors"][0]["profiles"]],
                         ["hbm", "server_dram", "enterprise_ssd"])
        self.assertTrue(all(p["status"] == "unknown" for s in report["sectors"] for p in s["profiles"]))

    def test_estimate_and_outlook_do_not_vote(self):
        p = [row("server_dram", "orders", 1),
             row("server_dram", "contract_price", 11.9, grade="estimate"),
             row("server_dram", "contract_price", 20, grade="outlook", period="2026-Q4")]
        found = pick(screen_sectors(p, NOW), "server_dram")
        self.assertEqual(found["status"], "unknown")
        self.assertIn("orders", found["gate_evidence"])
        self.assertEqual(len(found["research_context"]), 3)

    def test_product_and_period_do_not_mix(self):
        observations = [row("hbm", "orders", 5), row("enterprise_ssd", "contract_price", 5),
                        row("hbm", "contract_price", 5, period="2026-Q2")]
        p = pick(screen_sectors(observations, NOW), "hbm")
        self.assertEqual(p["reason"], "missing_matched_observed_pair")
        self.assertEqual(p["missing"], ["contract_price"])

    def test_scope_not_selected_automatically_when_ambiguous(self):
        p = [row("hbm", "orders", 5), row("hbm", "contract_price", 5),
             row("hbm", "orders", 7, scope="different")]
        self.assertEqual(pick(screen_sectors(p, NOW), "hbm")["reason"], "choose_a_single_scope")
        self.assertEqual(pick(screen_sectors(p, NOW, {"hbm":"stable-sample"}), "hbm")["status"], "pass")

    def test_sign_and_units_autos(self):
        a = row("autos", "sales_units", 2, period="2026-10", comparison="yoy")
        b = row("autos", "incentive_ratio", .3, period="2026-10", unit="%p", comparison="yoy")
        self.assertEqual(pick(screen_sectors([a,b], NOW), "autos")["status"], "hold")
        b["value"] = -.3
        self.assertEqual(pick(screen_sectors([a,b], NOW), "autos")["status"], "pass")
        b["unit"] = "%"
        with self.assertRaisesRegex(ValueError, "comparison"):
            screen_sectors([a,b], NOW)

    def test_stale_and_future_availability(self):
        p = [row("hbm", "orders", -5),
             row("hbm", "contract_price", -5, available_at="2026-12-10T08:00:00+09:00")]
        self.assertEqual(pick(screen_sectors(p, NOW), "hbm")["status"], "unknown")
        self.assertEqual(pick(screen_sectors(p, stamp("2026-12-11T00:00:00Z")), "hbm")["status"], "fail")
        self.assertFalse(pick(screen_sectors(p, stamp("2027-03-12T00:00:00Z")), "hbm")["gate_evidence"])

    def test_stage_requires_explicit_profile_and_stops(self):
        p = json.loads((ROOT / "examples/staged-research.json").read_text(encoding="utf-8"))
        cand = p["universe"][0]
        cand["sector"] = "semiconductor"
        p["industry_observations"] = []
        self.assertEqual(Screen(p).run()["candidates"][0]["stages"]["sector"]["reasons"],
                         ["sector_profile_required"])
        cand["sector_profile"] = "hbm"
        r = Screen(p).run()
        self.assertEqual(r["candidates"][0]["stages"]["chart"]["status"], "skipped")
        self.assertEqual(len(r["industry_report"]["sectors"]), 10)

    def test_markdown_cli_renders_all_sections(self):
        out = subprocess.check_output(
            [sys.executable, "-m", "research.sectors", "--input", "examples/sectors.json",
             "--format", "markdown"], cwd=ROOT, text=True)
        for k in ("HBM", "서버 DDR5", "기업용 SSD", "조선", "엔터", "참고 근거"):
            self.assertIn(k, out)


if __name__ == "__main__":
    unittest.main()
