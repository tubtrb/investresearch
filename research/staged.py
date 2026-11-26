"""Deterministic four-stage equity research screen. No live feed or trading."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from statistics import fmean

from .backtest import stamp
from .global_macro import dashboard

SCHEMA = {
    "fx": ("usd_local_change_pct",),
    "credit": ("hy_oas_change_bp",),
    "rates": ("us_10y_change_bp",),
    "breadth": ("sector_vs_benchmark_pct",),
    "orders": ("orders_change_pct",),
    "contract_price": ("price_change_pct",),
    "financials": ("op_income", "op_income_prior", "cfo", "capex", "eps"),
    "valuation": ("max_trailing_pe",),
}
AGES = {"fx": 4, "credit": 5, "rates": 5, "breadth": 4, "orders": 120,
        "contract_price": 120, "financials": 160, "valuation": 45}
MACRO_LIMITS = {"fx": .5, "credit": 10., "rates": 10.}


def number(value, what):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")
    return value


def label(value, what):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be nonempty text")
    return value.strip()


@dataclass(frozen=True)
class Observation:
    kind: str
    key: str
    period_end: datetime
    available_at: datetime
    source: str
    values: dict

    @classmethod
    def parse(cls, row):
        kind = row["kind"]
        if kind not in SCHEMA or set(row["values"]) != set(SCHEMA[kind]):
            raise ValueError(f"Unknown evidence kind or fields: {kind}")
        period, avail = stamp(row["period_end"]), stamp(row["available_at"])
        if period > avail:
            raise ValueError("Evidence cannot be available before period_end")
        values = {k: number(v, k) for k, v in row["values"].items()}
        if kind == "financials" and values["capex"] < 0:
            raise ValueError("Enter capex as positive cash outflow")
        if kind == "valuation" and values["max_trailing_pe"] <= 0:
            raise ValueError("max_trailing_pe must be positive")
        return cls(kind, label(row["key"], "evidence key"), period, avail,
                   label(row["source"], "evidence source"), values)

    def audit(self):
        return {"kind": self.kind, "key": self.key,
                "period_end": self.period_end.isoformat(), "available_at": self.available_at.isoformat(),
                "source": self.source, "values": self.values}


class Screen:
    def __init__(self, payload):
        self.market = label(payload["market"], "market")
        self.cutoff = stamp(payload["cutoff"])
        self.global_macro = dashboard(payload["global_macro"], self.cutoff) if "global_macro" in payload else None
        self.sessions = [stamp(x) for x in payload["regular_closes"]]
        if not self.sessions or any(a >= b for a, b in zip(self.sessions, self.sessions[1:])):
            raise ValueError("regular_closes must be a nonempty strictly increasing exchange calendar")
        self.completed = [s for s in self.sessions if s <= self.cutoff]
        self.calendar = set(self.sessions)
        if not self.completed:
            raise ValueError("No completed regular session at cutoff")
        self.universe = {}
        for candidate in payload["universe"]:
            sym = label(candidate["symbol"], "symbol")
            if sym in self.universe:
                raise ValueError(f"Duplicate candidate: {sym}")
            self.universe[sym] = label(candidate["sector"], "sector/product key")
        if not self.universe:
            raise ValueError("Provide at least one equity")
        self.observations = {}
        duplicates = set()
        for row in payload["evidence"]:
            obs = Observation.parse(row)
            identity = obs.kind, obs.key, obs.period_end, obs.available_at
            if identity in duplicates:
                raise ValueError(f"Duplicate evidence vintage: {obs.kind}/{obs.key}")
            duplicates.add(identity)
            if obs.available_at <= self.cutoff:
                self.observations.setdefault((obs.kind, obs.key), []).append(obs)
        self.bars = {}
        for row in payload["bars"]:
            sym = row["symbol"]
            close_at, avail = stamp(row["close_at"]), stamp(row["available_at"])
            price = number(row["close"], "close")
            key = sym, close_at
            if (sym not in self.universe or close_at not in self.calendar or avail < close_at
                    or price <= 0 or row["session"] != "regular" or key in self.bars):
                raise ValueError(f"Invalid or duplicate regular close: {sym}/{close_at.isoformat()}")
            self.bars[key] = price, avail, label(row["source"], "bar source")

    def evidence(self, kind, key):
        rows = self.observations.get((kind, key), ())
        # A late revision for an older period cannot replace a newer observed period.
        latest = max(rows, key=lambda e: (e.period_end, e.available_at), default=None)
        if latest is not None and self.cutoff - latest.period_end <= timedelta(days=AGES[kind]):
            return latest
        return None

    def macro(self):
        kinds = tuple(MACRO_LIMITS)
        obs = [self.evidence(kind, self.market) for kind in kinds]
        missing = [kind for kind, row in zip(kinds, obs) if row is None]
        adverse = [row.kind for row in obs if row is not None
                   and row.values[SCHEMA[row.kind][0]] >= MACRO_LIMITS[row.kind]]
        if len(adverse) == 3:
            return result("hold", ["joint_stress"], obs, adverse=adverse, exposure_factor=0.)
        if missing:
            return result("unknown", missing, obs, adverse=adverse, exposure_factor=None)
        factor = .5 if len(adverse) == 2 else 1.
        return result("pass", ["reduced_risk_budget" if factor == .5 else "normal_risk_budget"],
                      obs, adverse=adverse, exposure_factor=factor)

    def sector(self, sector):
        kinds = ("orders", "contract_price")
        obs = [self.evidence(kind, sector) for kind in kinds]
        relative = self.evidence("breadth", sector)
        context = {"relative_strength": relative.audit() if relative is not None else None}
        if any(row is None for row in obs):
            return result("unknown", [kind for kind, row in zip(kinds, obs) if row is None],
                          obs, **context)
        a, b = obs[0].values["orders_change_pct"], obs[1].values["price_change_pct"]
        if a > 0 and b > 0:
            return result("pass", ["orders_and_contract_prices_improving"], obs, **context)
        if a < 0 and b < 0:
            return result("fail", ["orders_and_contract_prices_declining"], obs, **context)
        return result("hold", ["mixed_or_flat_sector"], obs, **context)

    def chart(self, symbol):
        dates = self.completed[-21:]
        bars = [self.bars.get((symbol, session)) for session in dates]
        missing = [s.isoformat() for s, b in zip(dates, bars) if b is None or b[1] > self.cutoff]
        if len(dates) < 21 or missing:
            return result("unknown", ["need_21_visible_contiguous_regular_closes"], missing_closes=missing)
        closes = [b[0] for b in bars]

        def averages(series):
            return {f"sma{n}": fmean(series[-n:]) for n in (5, 10, 20)}

        def bullish(series, av):
            return av["sma5"] > av["sma10"] > av["sma20"] and series[-1] > av["sma20"]

        now, prev = averages(closes), averages(closes[:-1])
        up, was_up = bullish(closes, now), bullish(closes[:-1], prev)
        why = "new_bullish_alignment" if up and not was_up else (
            "existing_alignment_not_new" if up else "alignment_or_close_filter_not_met")
        return result("pass" if up and not was_up else "hold", [why], close=closes[-1], **now,
                      previous_sma=prev, close_at=dates[-1].isoformat(),
                      bars_available_at=max(b[1] for b in bars).isoformat(),
                      bar_sources=sorted({b[2] for b in bars}))

    def company(self, symbol, close):
        obs = [self.evidence(kind, symbol) for kind in ("financials", "valuation")]
        if any(row is None for row in obs):
            return result("unknown", [kind for kind, row in zip(("financials", "valuation"), obs)
                                      if row is None], obs)
        v, cap = obs[0].values, obs[1].values["max_trailing_pe"]
        fcf = v["cfo"] - v["capex"]
        pe = close / v["eps"] if v["eps"] > 0 else None
        tests = {
            "op_income_positive_and_growing": v["op_income"] > max(0., v["op_income_prior"]),
            "fcf_positive": fcf > 0,
            "positive_eps_and_within_pe_ceiling": pe is not None and pe <= cap,
        }
        failed = [test for test, passed in tests.items() if not passed]
        return result("fail" if failed else "pass", failed or ["quality_and_valuation_pass"], obs,
                      fcf=fcf, trailing_pe=pe, checks=tests)

    def run(self):
        candidates = []
        for sym, sector in self.universe.items():
            gates = {"macro": self.macro()}
            for name, test in (("sector", lambda: self.sector(sector)),
                               ("chart", lambda: self.chart(sym)),
                               ("company", lambda: self.company(sym, gates["chart"]["close"]))):
                blocker = next((k for k, v in gates.items() if v["status"] != "pass"), None)
                gates[name] = result("skipped", [f"blocked_by_{blocker}"]) if blocker else test()
            first = next((k for k, v in gates.items() if v["status"] != "pass"), None)
            candidates.append({"symbol": sym, "sector": sector, "stages": gates,
                               "status": "review" if first is None else "not_eligible",
                               "first_blocker": first,
                               "illustrative_max_weight": .5 * gates["macro"]["exposure_factor"]
                               if first is None else None})
        return {"schema_version": 2, "mode": "research_only", "market": self.market,
                "cutoff": self.cutoff.isoformat(), "evaluated_close_at": self.completed[-1].isoformat(),
                "macro_stress_limits": MACRO_LIMITS, "max_age_calendar_days": AGES,
                "candidates": candidates, "global_macro": self.global_macro}


def result(status, reasons, evidence=(), **details):
    return {"status": status, "reasons": reasons,
            "evidence": [row.audit() for row in evidence if row is not None], **details}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path, help="Point-in-time JSON snapshot")
    a = p.parse_args()
    try:
        report = Screen(json.loads(a.input.read_text(encoding="utf-8-sig"))).run()
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError) as ex:
        p.exit(2, f"Input error: {ex}\n")


if __name__ == "__main__":
    main()
