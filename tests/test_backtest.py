import csv
from datetime import date, timedelta
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from research.backtest import Dataset, Settings, SYMBOLS, TABLES, from_csv, from_sqlite, run


DEMO = Path(__file__).resolve().parents[1] / "examples"
CFG = Settings(ma=3, peak=3, min_drawdown=.15, min_vol=30, expires=9, confirm_days=2, horizon=2)


def sample_rows():
    dates = [str(date(2020, 1, 6) + timedelta(days=i)) for i in range(12) if i % 7 < 5]
    values = [
        (129, 135, 125, 130), (130, 133, 123, 125), (125, 129, 117, 120),
        (92, 96, 85, 90), (98, 106, 95, 102), (97, 104, 92, 97),
        (105, 110, 102, 108), (109, 114, 108, 112),
        (113, 116, 109, 114), (114, 118, 111, 116),
    ]
    rows = {"sessions": [], "bars": [], "evidence": []}
    for i, day in enumerate(dates):
        when = lambda k: day + "T" + k + "+09:00"
        rows["sessions"].append(dict(day=day, opened_at=when("09:00:00"), closed_at=when("15:30:00"), decision_at=when("16:00:00")))
        for symbol, factor in zip(SYMBOLS, (10, 1000, 100)):
            rows["bars"].append(dict(zip(TABLES["bars"], [
                day, symbol, *(x*factor for x in values[i]), when("15:45:00")])))
        checked = [26, 29, 32, 42, 40, 39, 35, 32, 31, 29][i]
        rows["bars"].append(dict(zip(TABLES["bars"], [day, "VKOSPI", "", "", "", checked, when("15:45:00")])))
    for kind, n in [("valuation", 3), ("earnings", 4)]:
        day = dates[n]
        rows["evidence"].append(dict(kind=kind, event_at=day+"T13:00:00+09:00",
             available_at=day+"T13:05:00+09:00", state="support", source="synthetic example"))
    return rows


class StudyTests(unittest.TestCase):
    def test_fixture_and_distinct_metrics(self):
        result = run(from_csv(DEMO), CFG)
        c, = result["cases"]
        self.assertEqual((c["candidate"], c["trigger"], c["retest"], c["confirmation"]),
                         ("2020-01-09", "2020-01-10", "2020-01-13", "2020-01-15"))
        o = c["outcome"]
        self.assertEqual(o["status"], "complete")
        self.assertEqual(o["entry_session"], "2020-01-16")
        self.assertEqual(o["entry_open_reference"], 113000)
        self.assertAlmostEqual(o["confirmation_cost_vs_anchor"], 113/85-1)
        self.assertAlmostEqual(o["forward_close_return"], 116/113-1)
        self.assertAlmostEqual(o["future_adverse_excursion"], 109/113-1)
        base = c["candidate_outcome"]
        self.assertEqual(base["entry_session"], "2020-01-10")
        self.assertAlmostEqual(base["forward_close_return"], 97/98-1)
        self.assertAlmostEqual(c["paired_comparison"]["later_open_vs_candidate_open"], 113/98-1)

    def test_late_evidence_cannot_trigger_prior_session(self):
        rows = sample_rows()
        rows["evidence"][1]["available_at"] = "2020-01-10T16:00:01+09:00"
        c, = run(Dataset.from_rows(rows), CFG)["cases"]
        self.assertEqual(c["trigger"], "2020-01-13")
        self.assertIsNone(c["confirmation"])

    def test_future_observations_do_not_rewrite_prior_decision(self):
        rows = sample_rows()
        before = run(Dataset.from_rows(rows), CFG)["cases"][0]
        for r in rows["bars"]:
            if r["day"] == "2020-01-16" and r["symbol"] == "HYNIX":
                r.update(open=105000, low=100000)
        after = run(Dataset.from_rows(rows), CFG)["cases"][0]
        self.assertEqual({k:v for k,v in before.items() if k not in {"outcome", "candidate_outcome", "paired_comparison"}},
                         {k:v for k,v in after.items() if k not in {"outcome", "candidate_outcome", "paired_comparison"}})
        self.assertNotEqual(before["outcome"], after["outcome"])

    def test_late_bar_censors_not_changes_to_zero(self):
        rows = sample_rows()
        for r in rows["bars"]:
            if r["day"] == "2020-01-13" and r["symbol"] == "HYNIX":
                r["available_at"] = "2020-01-13T16:30:00+09:00"
        c, = run(Dataset.from_rows(rows), CFG)["cases"]
        self.assertEqual(c["status"], "censored_missing_low")
        self.assertIsNone(c["outcome"])

    def test_missing_evidence_does_not_confirm(self):
        rows = sample_rows()
        rows["evidence"].pop()
        c, = run(Dataset.from_rows(rows), CFG)["cases"]
        self.assertIsNone(c["trigger"])
        self.assertIsNone(c["confirmation"])

    def test_unknown_vol_breaks_consecutive_confirmation(self):
        rows = sample_rows()
        rows["bars"] = [r for r in rows["bars"]
                        if (r["day"],r["symbol"]) != ("2020-01-14","VKOSPI")]
        c, = run(Dataset.from_rows(rows), CFG)["cases"]
        self.assertEqual(c["confirmation"], "2020-01-16")

    def test_retest_breach_invalidates(self):
        rows = sample_rows()
        for r in rows["bars"]:
            if r["day"] == "2020-01-13" and r["symbol"] == "HYNIX":
                r["low"] = 84000
        c, = run(Dataset.from_rows(rows), CFG)["cases"]
        self.assertEqual(c["status"], "invalidated")
        self.assertEqual(c["candidate_outcome"]["status"], "complete")
        self.assertIsNone(c["paired_comparison"])

    def test_incomplete_calendar_has_no_forward_metrics(self):
        rows = sample_rows()
        rows["sessions"].pop()
        rows["bars"] = [r for r in rows["bars"] if r["day"] < "2020-01-17"]
        c, = run(Dataset.from_rows(rows), CFG)["cases"]
        self.assertEqual(c["outcome"]["status"], "incomplete_calendar")
        self.assertIsNotNone(c["outcome"]["confirmation_cost_vs_anchor"])
        self.assertIsNone(c["outcome"]["future_adverse_excursion"])
        self.assertIsNone(c["outcome"]["forward_close_return"])
        self.assertIsNone(c["paired_comparison"])

    def test_decision_must_precede_next_session_open(self):
        rows = sample_rows()
        rows["sessions"][7]["decision_at"] = rows["sessions"][8]["opened_at"]
        with self.assertRaisesRegex(ValueError, "clock order"):
            Dataset.from_rows(rows)

    def test_missing_forward_bar_is_not_skipped(self):
        rows = sample_rows()
        rows["bars"] = [r for r in rows["bars"]
                        if (r["day"],r["symbol"]) != ("2020-01-17","HYNIX")]
        c, = run(Dataset.from_rows(rows), CFG)["cases"]
        self.assertEqual(c["outcome"]["status"], "missing_forward_bars")
        self.assertIsNone(c["outcome"]["forward_close_return"])
        self.assertIsNone(c["paired_comparison"])

    def test_sqlite_exact_match_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.sqlite"
            c = sqlite3.connect(p)
            with c:
                c.executescript((DEMO.parent/"database"/"schema.sql").read_text())
                for t, fields in TABLES.items():
                    c.executemany(f"INSERT INTO {t} VALUES({','.join('?'*len(fields))})",
                                [tuple(r[k] or None for k in fields) for r in sample_rows()[t]])
            c.close()
            before = hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertEqual(run(from_sqlite(p), CFG), run(from_csv(DEMO), CFG))
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), before)
            self.assertEqual([f.name for f in Path(tmp).iterdir()], ["test.sqlite"])

    def test_do_not_accept_legacy_archive_or_create_missing_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "legacy.sqlite"
            with sqlite3.connect(p) as c:
                c.execute("CREATE TABLE records (payload_json TEXT)")
            with self.assertRaisesRegex(ValueError, "Not a normalized"):
                from_sqlite(p)
            missing = p.with_name("missing.sqlite")
            with self.assertRaises(FileNotFoundError):
                from_sqlite(missing)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
