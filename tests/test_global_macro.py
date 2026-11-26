import json
from pathlib import Path
import subprocess
import sys
import unittest

from research.backtest import stamp
from research.global_macro import BY_KEY, dashboard
from research.staged import Screen

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = stamp("2026-11-27T08:30:00+09:00")


def obs(key, day, value, **kw):
    s = BY_KEY[key]
    return dict(key=key, basis=s.basis, unit=s.unit, market_date=day,
                observed_at=f"{day}T17:00:00+00:00", available_at=f"{day}T17:30:00+00:00",
                value=value, source="synthetic_test_source", **kw)


def pair(key, old, new, **kw):
    return [obs(key, "2026-11-25", old, **kw), obs(key, "2026-11-26", new, **kw)]


def pick(res, key):
    return next(x for x in res["groups"][BY_KEY[key].group] if x["key"] == key)


class GlobalMacroTest(unittest.TestCase):
    def test_forty_plus_seven(self):
        r = dashboard([], CUTOFF)
        self.assertEqual({k: len(v) for k, v in r["groups"].items()}, dict(
            bonds=10, fx=10, commodities=10, indices=10, index_futures=5, cross_checks=2))
        self.assertEqual(len(BY_KEY), 47)
        self.assertTrue(all(x["status"] == "missing_pair" for g in r["groups"].values() for x in g))

    def test_units_and_common_dollar_direction(self):
        r = dashboard(pair("US10Y", 4.91, 4.85) + pair("HY_OAS", 3.63, 3.72)
                      + pair("USDKRW", 1343.2, 1342.7) + pair("EURUSD", 1.10, 1.09)
                      + pair("TAIEX", 38195.43, 39151.81), CUTOFF)
        for key, expected in [("US10Y", -6), ("HY_OAS", 9), ("TAIEX", 2.503912117)]:
            self.assertAlmostEqual(pick(r, key)["change"], expected, places=5)
        self.assertLess(pick(r, "USDKRW")["change"], 0)
        self.assertGreater(pick(r, "EURUSD")["change"], 0)

    def test_contract_roll_and_same_contract(self):
        p = pair("BRENT", 91., 94., contract="2027-01")
        self.assertAlmostEqual(pick(dashboard(p, CUTOFF), "BRENT")["change"], 100 * (94./91.-1))
        p[-1]["contract"] = "2027-02"
        row = pick(dashboard(p, CUTOFF), "BRENT")
        self.assertEqual((row["status"], row["change"]), ("contract_roll", None))

    def test_live_futures_never_replace_cash_or_settlement(self):
        p = pair("NQ", 25800, 26200, contract="2026-12")
        p[-1]["basis"] = "futures_snapshot"
        r = dashboard(p, CUTOFF)
        self.assertEqual(pick(r, "NQ")["status"], "different_basis_or_source")
        self.assertEqual(pick(r, "NDX")["status"], "missing_pair")
        p[0]["basis"] = "futures_snapshot"
        self.assertEqual(pick(dashboard(p, CUTOFF), "NQ")["status"], "ok")
        p[-1]["observed_at"] = "2026-11-26T17:08:00+00:00"
        self.assertEqual(pick(dashboard(p, CUTOFF), "NQ")["status"], "different_snapshot_time")

    def test_late_and_missing_unchanged(self):
        p = pair("US10Y", 4.91, 4.85)
        p[-1]["available_at"] = "2026-11-27T09:00:00+09:00"
        r = pick(dashboard(p, CUTOFF), "US10Y")
        self.assertEqual(r["status"], "missing_pair")
        self.assertEqual(r["current"]["market_date"], "2026-11-25")
        self.assertIsNone(r["change"])

    def test_stale_and_source_consistency(self):
        p = pair("US10Y", 4.91, 4.85)
        p[-1]["source"] = "another_source"
        self.assertEqual(pick(dashboard(p, CUTOFF), "US10Y")["status"], "different_basis_or_source")
        later = stamp("2026-12-06T08:30:00+09:00")
        self.assertEqual(pick(dashboard(p, later), "US10Y")["status"], "stale")

    def test_global_context_never_changes_stage_gate(self):
        p = json.loads((ROOT / "examples/staged-research.json").read_text(encoding="utf-8"))
        prior = Screen(p).run()["candidates"]
        p["global_macro"] = pair("TAIEX", 38000, 1000)
        self.assertEqual(Screen(p).run()["candidates"], prior)

    def test_standalone_cli(self):
        out = subprocess.check_output([sys.executable, "-m", "research.global_macro", "--input",
                                       str(ROOT / "examples/global-macro.json")], cwd=ROOT)
        self.assertEqual(json.loads(out)["coverage"]["bonds"], 1)


if __name__ == "__main__":
    unittest.main()
