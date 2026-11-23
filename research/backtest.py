"""Point-in-time bottom-pattern study. No dependencies, trading, or forecasts."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Iterable

SYMBOLS = ("KOSPI", "HYNIX", "SAMSUNG")
VOL = "VKOSPI"
KINDS = frozenset({"valuation", "fx", "flows", "earnings", "policy"})
TABLES = {
    "sessions": ("day", "opened_at", "closed_at", "decision_at"),
    "bars": ("day", "symbol", "open", "high", "low", "close", "available_at"),
    "evidence": ("kind", "event_at", "available_at", "state", "source"),
}


def stamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError(f"Timestamp must have an explicit timezone: {value}")
    return result.astimezone(timezone.utc)


def price(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"Prices must be finite and positive: {value}")
    return result


@dataclass(frozen=True)
class Session:
    day: date
    opened_at: datetime
    closed_at: datetime
    decision_at: datetime


@dataclass(frozen=True)
class Bar:
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    available_at: datetime


@dataclass(frozen=True)
class Evidence:
    kind: str
    event_at: datetime
    available_at: datetime
    state: str
    source: str


@dataclass(frozen=True)
class Settings:
    ma: int = 200
    peak: int = 60
    min_drawdown: float = .15
    min_vol: float = 30.
    expires: int = 12
    confirm_days: int = 2
    horizon: int = 20
    valuation_max_age_days: int = 31

    def __post_init__(self) -> None:
        if min(self.ma, self.peak, self.expires, self.confirm_days, self.horizon,
               self.valuation_max_age_days) < 1:
            raise ValueError("Window lengths must be positive")
        if not (0 < self.min_drawdown < 1 and math.isfinite(self.min_vol) and self.min_vol > 0):
            raise ValueError("Invalid risk thresholds")


@dataclass
class Dataset:
    sessions: list[Session]
    bars: dict[tuple[date, str], Bar]
    evidence: list[Evidence]

    @classmethod
    def from_rows(cls, rows: dict[str, Iterable[dict]]) -> Dataset:
        sessions = sorted(
            (Session(date.fromisoformat(r["day"]), stamp(r["opened_at"]),
                     stamp(r["closed_at"]), stamp(r["decision_at"]))
             for r in rows["sessions"]), key=lambda s: s.day
        )
        if not sessions:
            raise ValueError("Provide a nonempty calendar of all eligible KRX trading sessions")
        by_day = {s.day: s for s in sessions}
        if len(by_day) != len(sessions):
            raise ValueError("Duplicate calendar session")
        for i, session in enumerate(sessions):
            if (not session.opened_at < session.closed_at <= session.decision_at
                    or (i and sessions[i - 1].decision_at >= session.opened_at)):
                raise ValueError("Invalid calendar clock order")
        bars: dict[tuple[date, str], Bar] = {}
        for r in rows["bars"]:
            day = date.fromisoformat(r["day"])
            sym = r["symbol"]
            key = day, sym
            if day not in by_day or sym not in (*SYMBOLS, VOL) or key in bars:
                raise ValueError(f"Unknown or duplicate daily bar: {key}")
            o, h, l, c = (price(r[k]) for k in ("open", "high", "low", "close"))
            if any(h is not None and v is not None and v > h for v in (o, l, c)):
                raise ValueError(f"Daily high is inconsistent: {key}")
            if any(l is not None and v is not None and v < l for v in (o, c)):
                raise ValueError(f"Daily low is inconsistent: {key}")
            available = stamp(r["available_at"])
            if available < by_day[day].closed_at:
                raise ValueError(f"Completed daily bar predates market close: {key}")
            bars[key] = Bar(o, h, l, c, available)
        evidence = []
        seen = set()
        for r in rows["evidence"]:
            ev = Evidence(r["kind"], stamp(r["event_at"]), stamp(r["available_at"]),
                          r["state"], r["source"])
            key = ev.kind, ev.available_at
            if (ev.kind not in KINDS or ev.state not in {"support", "against", "unknown"}
                    or ev.event_at > ev.available_at or not ev.source.strip() or key in seen):
                raise ValueError(f"Invalid or ambiguous evidence row: {ev}")
            evidence.append(ev)
            seen.add(key)
        return cls(sessions, bars, sorted(evidence, key=lambda e: e.available_at))

    def feature(self, day: date, sym: str, field: str, at: datetime) -> float | None:
        bar = self.bars.get((day, sym))
        return getattr(bar, field) if bar is not None and bar.available_at <= at else None


def from_csv(directory: Path) -> Dataset:
    rows = {}
    for table, fields in TABLES.items():
        with (directory / f"{table}.csv").open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if tuple(reader.fieldnames or ()) != fields:
                raise ValueError(f"{table}.csv requires columns: {', '.join(fields)}")
            rows[table] = list(reader)
    return Dataset.from_rows(rows)


def from_sqlite(path: Path) -> Dataset:
    """Read only an existing normalized study DB, never an operational archive."""
    uri = path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA trusted_schema=OFF")
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        if not TABLES.keys() <= names:
            raise ValueError("Not a normalized research SQLite snapshot; see database/schema.sql")
        try:
            rows = {t: [dict(r) for r in con.execute(
                f'SELECT {", ".join(chr(34) + col + chr(34) for col in cols)} FROM "{t}"'
            )] for t, cols in TABLES.items()}
        except sqlite3.Error as ex:
            raise ValueError("Incompatible normalized research SQLite schema") from ex
        return Dataset.from_rows(rows)
    finally:
        con.close()


def _window(dataset: Dataset, i: int, symbol: str, length: int) -> list[float] | None:
    """Use the previous N completed calendar sessions, never skip a missing row."""
    if i < length:
        return None
    sessions = dataset.sessions
    vals = [dataset.feature(s.day, symbol, "close", sessions[i].decision_at)
            for s in sessions[i-length:i]]
    return vals if all(v is not None for v in vals) else None


def _latest(dataset: Dataset, now: datetime, after: datetime) -> dict[str, Evidence]:
    latest = {}
    for e in dataset.evidence:
        if after < e.available_at <= now:
            latest[e.kind] = e  # deterministic, unique (kind, available_at)
    return latest


def _trigger(latest: dict[str, Evidence]) -> tuple[Evidence, ...]:
    support = {k: e for k, e in latest.items() if e.state == "support"}
    for keys in (("fx", "flows"), ("earnings",), ("policy",)):
        if all(k in support for k in keys):
            return tuple(support[k] for k in keys)
    return ()


def _outcome(dataset: Dataset, idx: int, horizon: int, anchor: float) -> dict:
    sessions = dataset.sessions
    entry_index = idx + 1
    result = {"status": "incomplete_calendar", "horizon_sessions": horizon,
              "entry_session": None, "entry_open_reference": None,
              "confirmation_cost_vs_anchor": None, "forward_close_return": None,
              "future_adverse_excursion": None}
    if entry_index >= len(sessions):
        return result
    result["entry_session"] = str(sessions[entry_index].day)
    bar = dataset.bars.get((sessions[entry_index].day, "HYNIX"))
    if bar is None or bar.open is None:
        result["status"] = "missing_entry_open"
        return result
    entry = bar.open
    result["entry_open_reference"] = entry
    result["confirmation_cost_vs_anchor"] = entry / anchor - 1
    if entry_index + horizon > len(sessions):
        return result
    rows = [dataset.bars.get((s.day, "HYNIX"))
            for s in sessions[entry_index:entry_index+horizon]]
    if any(b is None or b.low is None or b.close is None for b in rows):
        result["status"] = "missing_forward_bars"
        return result
    result.update(status="complete", forward_close_return=rows[-1].close / entry - 1,
                  future_adverse_excursion=min(0., min(b.low for b in rows) / entry - 1))
    return result


def run(dataset: Dataset, cfg: Settings = Settings()) -> dict:
    calendar = dataset.sessions
    cases: list[dict] = []
    diagnostics: list[dict] = []
    active = None
    for i, s in enumerate(calendar):
        get = lambda sym, f: dataset.feature(s.day, sym, f, s.decision_at)
        lows = {sym: get(sym, "low") for sym in SYMBOLS}
        closes = {sym: get(sym, "close") for sym in SYMBOLS}
        highs = {sym: get(sym, "high") for sym in SYMBOLS}
        vol = get(VOL, "close")
        stamp_day = str(s.day)
        missing = []
        if active is None:
            histories = {sym: (_window(dataset, i, sym, cfg.ma),
                               _window(dataset, i, sym, cfg.peak)) for sym in SYMBOLS}
            val = _latest(dataset, s.decision_at, s.decision_at -
                          timedelta(days=cfg.valuation_max_age_days)).get("valuation")
            missing.extend(sym for sym in SYMBOLS if lows[sym] is None or closes[sym] is None
                           or any(v is None for v in histories[sym]))
            if vol is None:
                missing.append(VOL)
            if val is None or val.state == "unknown" or val.event_at <= s.decision_at - timedelta(days=cfg.valuation_max_age_days):
                missing.append("valuation")
            if missing:
                diagnostics.append({"day": stamp_day, "unavailable": missing})
                continue
            if (vol < cfg.min_vol or val.state != "support"
                    or not all(closes[k] <= sum(histories[k][0]) / cfg.ma
                               and closes[k] / max(histories[k][1]) - 1 <= -cfg.min_drawdown
                               for k in SYMBOLS)):
                continue
            active = {"candidate": stamp_day, "anchor_lows": lows, "candidate_close": closes,
                      "valuation_source": val.source, "trigger": None, "retest": None,
                      "confirmation": None, "status": "open", "outcome": None}
            cases.append(active)
            start_i, support_run, prev_lows = i, 0, lows
            continue

        if i - start_i > cfg.expires:
            active.update(status="expired", terminal_day=stamp_day)
            active = None
            continue
        known_breach = any(lows[k] is not None and lows[k] < active["anchor_lows"][k]
                           for k in SYMBOLS)
        if known_breach or any(v is None for v in lows.values()):
            active.update(status="invalidated" if known_breach else "censored_missing_low",
                          terminal_day=stamp_day)
            active = None
            continue
        if active["trigger"] is None:
            evidence = _latest(dataset, s.decision_at, calendar[i-1].decision_at)
            triggers = _trigger(evidence)
            if triggers and vol is not None and all(v is not None for v in (*highs.values(), *closes.values())):
                active.update(trigger=stamp_day, trigger_evidence=[
                    {"kind": e.kind, "event_at": e.event_at.isoformat(),
                     "available_at": e.available_at.isoformat(), "source": e.source} for e in triggers],
                    recovery_highs=highs, trigger_volatility=vol)
            prev_lows = lows
            continue

        if active["retest"] is None:
            # A pullback versus the immediately preceding session; all three hold
            # strictly higher lows than their own candidate anchors.
            if (all(lows[k] > active["anchor_lows"][k] for k in SYMBOLS)
                    and any(lows[k] < prev_lows[k] for k in SYMBOLS)):
                active["retest"] = stamp_day
            prev_lows = lows
            continue

        enough = (
            vol is not None and vol < active["trigger_volatility"]
            and all(closes[k] is not None and closes[k] > active["recovery_highs"][k] for k in SYMBOLS)
        )
        support_run = support_run + 1 if enough else 0
        if support_run >= cfg.confirm_days:
            active.update(status="confirmed", terminal_day=stamp_day, confirmation=stamp_day,
                          decision_at=s.decision_at.isoformat())
            active = None
        prev_lows = lows
    if active is not None:
        active["status"] = "incomplete_setup_history"
    # Forward data are only read after every historical decision has been labeled.
    by_day = {str(s.day): i for i, s in enumerate(calendar)}
    for case in cases:
        anchor = case["anchor_lows"]["HYNIX"]
        candidate = _outcome(dataset, by_day[case["candidate"]], cfg.horizon, anchor)
        candidate["entry_gap_vs_candidate_low"] = candidate.pop("confirmation_cost_vs_anchor")
        case["candidate_outcome"] = candidate
        case["paired_comparison"] = None
        if case["confirmation"] is not None:
            later = _outcome(dataset, by_day[case["confirmation"]], cfg.horizon, anchor)
            case["outcome"] = later
            if later["status"] == candidate["status"] == "complete":
                case["paired_comparison"] = {
                    "later_open_vs_candidate_open": (
                        later["entry_open_reference"] / candidate["entry_open_reference"] - 1),
                    "forward_close_return_difference": (
                        later["forward_close_return"] - candidate["forward_close_return"]),
                    "adverse_excursion_difference": (
                        later["future_adverse_excursion"] - candidate["future_adverse_excursion"]),
                }
    return {"kind": "retrospective_event_study", "settings": asdict(cfg),
            "cases": cases, "missing_candidate_inputs": diagnostics}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="Directory with the three normalized CSV files")
    source.add_argument("--sqlite", type=Path, help="Normalized, closed SQLite snapshot (read-only)")
    for name, default in asdict(Settings()).items():
        parser.add_argument("--" + name.replace("_", "-"), default=default, type=type(default))
    args = vars(parser.parse_args())
    try:
        directory, sql = args.pop("csv"), args.pop("sqlite")
        dataset = from_csv(directory) if directory is not None else from_sqlite(sql)
        print(json.dumps(run(dataset, Settings(**args)), indent=2, ensure_ascii=False, allow_nan=False))
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, AttributeError) as ex:
        parser.exit(2, f"Input error: {ex}\n")


if __name__ == "__main__":
    main()
