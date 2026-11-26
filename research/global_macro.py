"""Global macro dashboard: 4 groups x 10 plus 7 cross-checks, no trade score."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, timedelta
import json
import math
from pathlib import Path
import re

from .backtest import stamp


@dataclass(frozen=True)
class Series:
    key: str
    group: str
    name: str
    basis: str
    unit: str
    cluster: str
    reference: str
    quote: str = ""


def group(name, basis, values):
    return tuple(Series(key, name, title, basis, unit, cluster, source, *rest)
                 for key, title, unit, cluster, source, *rest in values)


UST = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"
ECB = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
CME = "https://www.cmegroup.com/markets.html"
STOXX = "https://stoxx.com/indices/"
FRED_HY = "https://fred.stlouisfed.org/series/BAMLH0A0HYM2"
CATALOG = (
    *group("bonds", "yield_close", [
        ("US2Y", "미국 2년", "%", "US_curve", UST),
        ("US10Y", "미국 10년", "%", "US_curve", UST),
        ("KR10Y", "한국 10년", "%", "KR_curve", "https://www.kofiabond.or.kr/"),
        ("JP10Y", "일본 10년", "%", "JP_curve", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"),
        ("DE10Y", "독일 10년", "%", "euro_curve", "https://www.bundesbank.de/en/statistics/money-and-capital-markets/interest-rates-and-yields"),
        ("UK10Y", "영국 10년", "%", "UK_curve", "https://www.bankofengland.co.uk/statistics/yield-curves"),
        ("CN10Y", "중국 10년", "%", "CN_curve", "https://yield.chinabond.com.cn/"),
        ("AU10Y", "호주 10년", "%", "AU_curve", "https://www.rba.gov.au/statistics/tables/"),
        ("CA10Y", "캐나다 10년", "%", "CA_curve", "https://www.bankofcanada.ca/rates/interest-rates/canadian-bonds/"),
        ("IT10Y", "이탈리아 10년", "%", "euro_curve", "https://data.ecb.europa.eu/"),
    ]),
    *group("fx", "fx_fix", [
        ("USDKRW", "달러/원", "KRW/USD", "Asia_USD", "https://ecos.bok.or.kr/", "local_per_usd"),
        ("USDJPY", "달러/엔", "JPY/USD", "G10_USD", ECB, "local_per_usd"),
        ("USDTWD", "달러/대만달러", "TWD/USD", "Asia_USD", "https://www.cbc.gov.tw/en/lp-700-2.html", "local_per_usd"),
        ("USDCNH", "달러/역외 위안", "CNH/USD", "Asia_USD", "https://www.tma.org.hk/", "local_per_usd"),
        ("USDIDR", "달러/루피아", "IDR/USD", "Asia_USD", "https://www.bi.go.id/en/statistik/informasi-kurs/transaksi-bi/jisdor/default.aspx", "local_per_usd"),
        ("EURUSD", "유로/달러", "USD/EUR", "G10_USD", ECB, "usd_per_local"),
        ("GBPUSD", "파운드/달러", "USD/GBP", "G10_USD", ECB, "usd_per_local"),
        ("AUDUSD", "호주달러/달러", "USD/AUD", "G10_USD", ECB, "usd_per_local"),
        ("USDCAD", "달러/캐나다달러", "CAD/USD", "G10_USD", ECB, "local_per_usd"),
        ("USDCHF", "달러/스위스프랑", "CHF/USD", "G10_USD", ECB, "local_per_usd"),
    ]),
    *group("commodities", "futures_settlement", [
        ("WTI", "WTI 원유", "USD/bbl", "oil", CME),
        ("BRENT", "브렌트 원유", "USD/bbl", "oil", "https://www.ice.com/products/219/Brent-Crude-Futures"),
        ("HENRY_HUB", "미국 천연가스", "USD/MMBtu", "gas", CME),
        ("GOLD", "금", "USD/troy_oz", "precious", CME),
        ("SILVER", "은", "USD/troy_oz", "precious", CME),
        ("COPPER", "구리", "USD/lb", "industrial_metal", CME),
        ("ALUMINIUM", "알루미늄", "USD/t", "industrial_metal", "https://www.lme.com/en/Metals/Non-ferrous/LME-Aluminium"),
        ("IRON_ORE", "철광석 62% Fe", "USD/t", "industrial_metal", "https://www.sgx.com/derivatives/products/iron-ore"),
        ("WHEAT", "시카고 밀", "USc/bu", "grains", CME),
        ("CORN", "옥수수", "USc/bu", "grains", CME),
    ]),
    *group("indices", "cash_close", [
        ("SP500", "S&P 500", "index_pt", "US_equity", "https://fred.stlouisfed.org/series/SP500"),
        ("NDX", "나스닥100", "index_pt", "US_equity", "https://indexes.nasdaqomx.com/Index/Overview/NDX"),
        ("SX5E", "유로스톡스50", "index_pt", "Euro_equity", STOXX),
        ("DAX", "독일 DAX (성과지수)", "index_pt", "Euro_equity", STOXX),
        ("FTSE100", "영국 FTSE100", "index_pt", "UK_equity", "https://www.lseg.com/en/ftse-russell/indices/uk"),
        ("N225", "닛케이225", "index_pt", "JP_equity", "https://indexes.nikkei.co.jp/en/nkave"),
        ("KOSPI", "코스피", "index_pt", "KR_equity", "https://data.krx.co.kr/"),
        ("TAIEX", "대만 가권", "index_pt", "TW_equity", "https://www.twse.com.tw/exchangeReport/FMTQIK?response=html"),
        ("HSI", "홍콩 항셍", "index_pt", "CN_equity", "https://www.hsi.com.hk/"),
        ("SSEC", "상하이종합", "index_pt", "CN_equity", "https://english.sse.com.cn/markets/indices/overview/"),
    ]),
    *group("index_futures", "futures_settlement", [
        ("ES", "S&P 500 선물", "index_pt", "US_equity", CME),
        ("NQ", "나스닥100 선물", "index_pt", "US_equity", CME),
        ("FESX", "유로스톡스50 선물", "index_pt", "Euro_equity", "https://www.eurex.com/ex-en/markets/idx/stx"),
        ("NK225F", "닛케이225 선물 (오사카)", "index_pt", "JP_equity", "https://www.jpx.co.jp/english/derivatives/products/domestic/225futures/"),
        ("TX", "대만 가권 선물", "index_pt", "TW_equity", "https://www.taifex.com.tw/enl/eng3/futDailyMarketReport"),
    ]),
    Series("VIX", "cross_checks", "VIX", "index_close", "index_pt", "US_risk",
           "https://www.cboe.com/tradable_products/vix/vix_historical_data/"),
    Series("HY_OAS", "cross_checks", "미국 하이일드 OAS", "spread_close", "%", "US_risk", FRED_HY),
)
BY_KEY = {series.key: series for series in CATALOG}
GROUPS = ("bonds", "fx", "commodities", "indices", "index_futures", "cross_checks")
INDEX_FUTURES = {"ES", "NQ", "FESX", "NK225F", "TX"}


def parse(row):
    s = BY_KEY.get(row["key"])
    if s is None:
        raise ValueError(f"Unknown series: {row['key']}")
    basis = row["basis"]
    if basis != s.basis and not (s.key in INDEX_FUTURES and basis == "futures_snapshot"):
        raise ValueError(f"{s.key} requires {s.basis} (index futures also accept futures_snapshot)")
    if row["unit"] != s.unit:
        raise ValueError(f"{s.key} requires unit {s.unit}")
    contract = row.get("contract")
    if basis.startswith("futures_"):
        if not isinstance(contract, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", contract):
            raise ValueError(f"{s.key} requires explicit YYYY-MM contract")
    elif contract is not None:
        raise ValueError(f"{s.key} must not carry a futures contract")
    value = row["value"]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{s.key} needs a finite numeric value")
    if s.basis in ("fx_fix", "cash_close", "index_close") and value <= 0:
        raise ValueError(f"{s.key} level must be positive")
    if s.key in INDEX_FUTURES and value <= 0:
        raise ValueError(f"{s.key} level must be positive")
    source = row["source"]
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"{s.key} needs a source")
    market_date = date.fromisoformat(row["market_date"])
    observed, available = stamp(row["observed_at"]), stamp(row["available_at"])
    if observed > available:
        raise ValueError(f"{s.key} availability cannot precede observation")
    if abs((market_date - observed.date()).days) > 1:
        raise ValueError(f"{s.key} market_date not near observation time")
    return (market_date, observed, available, basis, value, source.strip(), contract)


def packet(row):
    day, observed, available, basis, value, source, contract = row
    return dict(market_date=day.isoformat(), observed_at=observed.isoformat(),
                available_at=available.isoformat(), basis=basis, value=value,
                source=source, contract=contract)


def dashboard(rows, cutoff):
    """Use only visible vintages and compare two dated observations on matched definitions."""
    observed = {}
    seen = set()
    for row in rows:
        item = parse(row)
        key = row["key"]
        identity = (key, *item[:4])
        if identity in seen:
            raise ValueError(f"Ambiguous duplicate observation: {key}")
        seen.add(identity)
        if item[2] <= cutoff:
            observed.setdefault(key, []).append(item)

    result = {g: [] for g in GROUPS}
    for s in CATALOG:
        data = sorted(observed.get(s.key, ()), key=lambda x: (x[0], x[1], x[2]), reverse=True)
        latest = data[0] if data else None
        prior = next((x for x in data[1:] if x[0] < latest[0]), None) if latest else None
        status, change = "ok", None
        change_unit = "bp" if s.basis in ("yield_close", "spread_close") else (
            "pt" if s.key == "VIX" else "%")
        if not latest or not prior:
            status = "missing_pair"
        elif cutoff - latest[1] > timedelta(days=5 if s.group == "bonds" or s.key == "HY_OAS" else 4):
            status = "stale"
        elif latest[0] - prior[0] > timedelta(days=7):
            status = "comparison_gap"
        elif latest[3] != prior[3] or latest[5] != prior[5]:
            status = "different_basis_or_source"
        elif latest[6] != prior[6]:
            status = "contract_roll"
        elif latest[3] == "futures_snapshot" and (
                (latest[1].hour, latest[1].minute) != (prior[1].hour, prior[1].minute)):
            status = "different_snapshot_time"
        else:
            new, old = latest[4], prior[4]
            if change_unit == "bp":
                change = (new - old) * 100
            elif change_unit == "pt":
                change = new - old
            elif old <= 0 or new <= 0:
                status = "nonpositive_price_for_return"
            elif s.quote == "usd_per_local":
                change = (old / new - 1) * 100
            else:
                change = (new / old - 1) * 100
            if change is not None and not math.isfinite(change):
                status, change = "invalid_change", None
        result[s.group].append({**asdict(s), "status": status, "change": change,
                                "change_unit": change_unit,
                                "current": packet(latest) if latest else None,
                                "previous": packet(prior) if prior else None})
    return {"mode": "context_only", "cutoff": cutoff.isoformat(),
            "coverage": {g: sum(row["status"] == "ok" for row in items)
                         for g, items in result.items()}, "groups": result}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    a = p.parse_args()
    try:
        data = json.loads(a.input.read_text(encoding="utf-8-sig"))
        print(json.dumps(dashboard(data["observations"], stamp(data["cutoff"])),
                         ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError) as ex:
        p.exit(2, f"Input error: {ex}\n")


if __name__ == "__main__":
    main()
