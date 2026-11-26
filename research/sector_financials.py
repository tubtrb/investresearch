"""Point-in-time quarterly financial trends for fixed sector baskets."""
from __future__ import annotations

import argparse
from datetime import date
from html import escape
import json
import math
from pathlib import Path
import re

from .backtest import stamp
from .sectors import SECTORS, required_text

ENTERTAINMENT = {"352820", "041510", "035900", "122870"}


def quarter_index(label):
    if not isinstance(label, str) or not re.fullmatch(r"[1-9][0-9]{3}-Q[1-4]", label):
        raise ValueError("Quarter must be YYYY-Qn")
    return int(label[:4]) * 4 + int(label[-1]) - 1


def quarter_label(index):
    year, q = divmod(index, 4)
    return f"{year:04d}-Q{q + 1}"


def quarter_end(index):
    y, q = divmod(index, 4)
    return date(y, (q + 1) * 3, (31, 30, 30, 31)[q])


def numeric(value, key):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(f"Invalid number: {key}")
    return value


def sector_financials(config, cutoff):
    report_quarter = quarter_index(config["report_quarter"])
    if quarter_end(report_quarter) > cutoff.date():
        raise ValueError("report_quarter has not ended")
    if set(config["baskets"]) - set(SECTORS):
        raise ValueError("Unknown sector in financial baskets")
    reports = {}
    for sector, title in SECTORS.items():
        basket = config["baskets"].get(sector)
        n = 4 if sector == "entertainment" else 5
        if basket is None:
            reports[sector] = {"name": title, "status": "unknown", "reason": "basket_not_configured",
                               "expected_members": n, "history": []}
            continue
        members = {}
        for member in basket["members"]:
            symbol = required_text(member["symbol"], "symbol")
            if symbol in members:
                raise ValueError(f"Duplicate basket member: {sector}/{symbol}")
            members[symbol] = required_text(member["scope"], "scope")
        if (len(members) != n or (sector == "entertainment"
                                 and (set(members) != ENTERTAINMENT
                                      or set(members.values()) != {"consolidated"}))):
            raise ValueError(f"Invalid member count or membership: {sector}")
        # Single immutable universe for a given snapshot; no silent substitution.
        selected = stamp(basket["selected_at"])
        currency = required_text(basket["currency"], "currency")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Currency must be a three-letter uppercase code")
        unit = basket["units_per_display"]
        if type(unit) is not int or unit not in (1, 10**6, 10**8, 10**9, 10**12):
            raise ValueError("Invalid units_per_display")
        rows, vintages = {}, set()
        for row in basket["observations"]:
            symbol, q = row["symbol"], quarter_index(row["quarter"])
            avail = stamp(row["available_at"])
            if (symbol not in members or row["scope"] != members[symbol] or row["currency"] != currency
                    or row["basis"] != "standalone_quarter" or avail.date() < quarter_end(q)):
                raise ValueError(f"Incompatible financial observation: {sector}/{symbol}/{row['quarter']}")
            key = q, symbol
            vintage = key, avail
            if vintage in vintages:
                raise ValueError(f"Duplicate financial vintage: {sector}/{symbol}/{row['quarter']}")
            vintages.add(vintage)
            revenue = numeric(row["revenue"], "revenue")
            profit = numeric(row["operating_profit"], "operating_profit")
            source = required_text(row["source"], "source")
            if revenue < 0:
                raise ValueError("Negative revenue")
            if row["grade"] not in ("actual", "estimate"):
                raise ValueError("Financial grade must be actual or estimate")
            if avail <= cutoff and row["grade"] == "actual" and selected <= cutoff:
                if key not in rows or avail > rows[key][0]:
                    rows[key] = avail, revenue, profit, source

        def period(q):
            matched = {s: rows[q, s] for s in members if (q, s) in rows}
            return matched, sorted(set(members) - set(matched))

        history = []
        for q in range(report_quarter - 7, report_quarter + 1):
            cur, missing = period(q)
            prev, missing_prior = period(q - 4)
            p = {"quarter": quarter_label(q), "coverage": len(cur), "missing": missing,
                 "missing_prior": missing_prior,
                 "revenue": None, "operating_profit": None, "revenue_yoy_pct": None,
                 "operating_profit_yoy_pct": None, "operating_profit_delta": None,
                 "profit_transition": None, "both_improved": None, "both_weakened": None,
                 "sources": sorted({v[3] for v in cur.values()}),
                 "prior_sources": sorted({v[3] for v in prev.values()}),
                 "status": "unknown", "reason": "incomplete_comparable_quarters"}
            if not missing:
                p["revenue"] = sum(v[1] for v in cur.values())
                p["operating_profit"] = sum(v[2] for v in cur.values())
            if not missing and not missing_prior:
                a, b = sum(v[1] for v in prev.values()), sum(v[2] for v in prev.values())
                rev, op = p["revenue"], p["operating_profit"]
                grown = sum(cur[s][1] > prev[s][1] and cur[s][2] > prev[s][2] for s in members)
                shrunk = sum(cur[s][1] < prev[s][1] and cur[s][2] < prev[s][2] for s in members)
                if rev > a and op > b and grown > n / 2:
                    status, reason = "pass", "aggregate_and_majority_improving"
                elif rev < a and op < b and shrunk > n / 2:
                    status, reason = "fail", "aggregate_and_majority_weakening"
                else:
                    status, reason = "hold", "mixed_or_narrow_change"
                p.update(revenue_yoy_pct=(rev / a - 1) * 100 if a > 0 else None,
                         operating_profit_yoy_pct=(op / b - 1) * 100 if b > 0 and op >= 0 else None,
                         operating_profit_delta=op - b,
                         profit_transition=("turned_profitable" if b <= 0 < op else
                                            "turned_unprofitable" if op < 0 <= b else
                                            "loss_narrowed" if b < op < 0 else
                                            "loss_widened" if op < b < 0 else None),
                         both_improved=grown, both_weakened=shrunk, status=status, reason=reason)
            history.append(p)
        # Historical lines are retrospective for the selected basket. The gate must
        # not activate before that basket could have been known or on stale data.
        latest = history[-1]
        status, reason = latest["status"], latest["reason"]
        if selected > cutoff:
            status, reason = "unknown", "basket_not_yet_selected"
        elif (cutoff.date() - quarter_end(report_quarter)).days > 145:
            status, reason = "unknown", "stale_report_quarter"
        reports[sector] = {"name": title, "status": status, "reason": reason, "expected_members": n,
                           "currency": currency, "units_per_display": unit, "members": members,
                           "selected_at": selected.isoformat(), "latest": latest, "history": history}
    return {"report_quarter": config["report_quarter"], "cutoff": cutoff.isoformat(), "sectors": reports}


def chart_svg(report, sector, *, demo=False):
    data = report["sectors"][sector]
    history = data["history"]
    if not history:
        raise ValueError("Configure a basket before plotting")
    size = data["units_per_display"]
    unit = {1: "", 10**6: "백만 ", 10**8: "억 ", 10**9: "십억 ", 10**12: "조 "}[size]
    unit += "원" if data["currency"] == "KRW" else data["currency"]
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="650" viewBox="0 0 960 650">',
           '<rect width="960" height="650" fill="#f5f8fc"/>',
           '<style>text{font-family:"Noto Sans CJK KR",sans-serif;fill:#223855}</style>']

    def text(x, y, value, px=17, props=""):
        out.append(f'<text x="{x}" y="{y}" font-size="{px}" {props}>{escape(str(value))}</text>')

    def line(x1, y1, x2, y2, color="#dce5ef", width=1):
        out.append(f'<line x1="{x1}" y1="{y1:.2f}" x2="{x2}" y2="{y2:.2f}" stroke="{color}" stroke-width="{width}"/>')

    text(32, 51, f"{data['name']} | 대표 {data['expected_members']}사 분기 실적", 31, 'font-weight="bold"')
    latest = data["latest"]
    count = latest["both_improved"]
    sub = (f"매출·이익 동반 개선 {count}/{data['expected_members']}사  ·  전년 동기 대비"
           if count is not None else f"공시 확보 {latest['coverage']}/{data['expected_members']}사  ·  비교 가능한 데이터 부족")
    text(32, 89, f"{report['report_quarter']}  |  {sub}", 18)
    xs = [133 + 105 * i for i in range(8)]
    for metric, title, top, bottom in (("revenue", "합산 매출", 159, 325),
                                        ("operating_profit", "합산 영업이익", 391, 557)):
        vals = [p[metric] / size if p[metric] is not None else None for p in history]
        known = [v for v in vals if v is not None]
        low = min([0, *known]) if metric == "operating_profit" else min(known, default=0)
        high = max([0, *known])
        gap = (high - low) * .13 or max(abs(high) * .1, 1)
        low -= gap
        high += gap

        def y(v):
            return bottom - (v - low) / (high - low) * (bottom - top)

        out.append(f'<rect x="24" y="{top-47}" width="912" height="218" rx="10" fill="white"/>')
        text(42, top - 18, f"{title} ({unit})", 19, 'font-weight="bold"')
        for tick in (low + (high-low) * j / 3 for j in range(4)):
            if metric == "operating_profit" and abs(y(tick)-y(0)) < 17:
                continue
            line(92, y(tick), 903, y(tick))
            text(84, y(tick) + 5, f"{tick:,.2f}".rstrip("0").rstrip("."), 13, 'text-anchor="end"')
        if metric == "operating_profit":
            line(92, y(0), 903, y(0), "#63768d", 1.5)
            text(84, y(0) + 5, "0", 13, 'text-anchor="end"')
        last = None
        for x, value in zip(xs, vals):
            if value is None:
                text(x, bottom-6, "미집계", 13, 'text-anchor="middle"')
                last = None
                continue
            vy = y(value)
            if metric == "revenue":
                if last:
                    line(*last, x, vy, "#185bb3", 3)
                out.append(f'<circle cx="{x}" cy="{vy}" r="4.5" fill="#185bb3"/>')
                last = x, vy
            else:
                zero = y(0)
                color = "#187c70" if value >= 0 else "#bb4651"
                out.append(f'<rect x="{x-23}" y="{min(zero,vy)}" width="46" height="{max(1,abs(zero-vy))}" fill="{color}"/>')
            text(x, vy-11 if value >= 0 else vy+16, f"{value:,.2f}".rstrip("0").rstrip("."), 15,
                 'text-anchor="middle" font-weight="bold"')
    for x, period in zip(xs, history):
        text(x, 589, period["quarter"][2:].replace("-Q", "년 ") + "Q", 15, 'text-anchor="middle"')
    text(32, 628, "가상 데이터 · 형식 예시" if demo else "동일 구성 기준 · 공시 누락 분기는 연결하지 않음", 16)
    return "\n".join(out + ["</svg>"])



def overview_svg(report, *, demo=False):
    """Render all sectors on a common mobile-friendly, latest-quarter comparison."""
    palette = {
        "positive": ("#e3f2eb", "#135a43"),
        "negative": ("#fae9ec", "#962e43"),
        "neutral": ("#eef2f6", "#52647a"),
        "mixed": ("#fff0d4", "#825615"),
    }
    states = {"pass": ("개선", "positive"), "hold": ("혼조", "mixed"),
              "fail": ("악화", "negative"), "unknown": ("미확인", "neutral")}
    transitions = {"turned_profitable": "흑자전환", "turned_unprofitable": "적자전환",
                   "loss_narrowed": "적자 축소", "loss_widened": "적자 확대"}
    out = ['<svg xmlns="http://www.w3.org/2000/svg" role="img" width="800" height="890" viewBox="0 0 800 890">',
           '<title>대표 기업 실적 비교 · 10개 섹터</title>',
           '<rect width="800" height="890" fill="#f5f8fc"/>',
           '<style>text{font-family:"Noto Sans CJK KR",sans-serif}</style>']

    def txt(x, y, value, size=20, color="#203651", *, bold=False, center=False):
        out.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}"'
                   f' font-weight="{700 if bold else 400}" text-anchor="{"middle" if center else "start"}">'
                   f'{escape(str(value))}</text>')

    def box(x, y, w, h, fill="#fff", radius=10):
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"/>')

    def pill(x, y, value, tone, w=117):
        bg, fg = palette[tone]
        box(x-w/2, y-26, w, 34, bg)
        txt(x, y-3, value, 18, fg, bold=True, center=True)

    def pct(v):
        if v is None:
            return "—", "neutral"
        return (f"{v:+.1f}%" if round(v, 1) else "0.0%",
                "positive" if v > 0 else "negative" if v < 0 else "neutral")

    rows = list(report["sectors"].values())
    comparable = sum(r.get("latest", {}).get("both_improved") is not None for r in rows)
    txt(30, 55, "10개 섹터 | 대표 기업 실적", 35, bold=True)
    txt(30, 92, f"{report['report_quarter']}  ·  전년 동기 대비  ·  비교 가능 {comparable}/{len(rows)}개 섹터", 20)
    for x, title in ((283, "합산 매출"), (425, "합산 영업이익"), (555, "동반 개선"), (700, "판정")):
        txt(x, 148, title, 19, bold=True, center=True)
    txt(39, 148, "섹터", 19, bold=True)
    for i, row in enumerate(rows):
        y = 201 + 59*i
        box(25, y-35, 750, 51)
        latest = row.get("latest", {})
        txt(39, y-4, row["name"], 21, bold=True)
        rev, rev_tone = pct(latest.get("revenue_yoy_pct"))
        op, op_tone = pct(latest.get("operating_profit_yoy_pct"))
        change = latest.get("profit_transition")
        if change in transitions:
            op = transitions[change]
            op_tone = "positive" if change in {"turned_profitable", "loss_narrowed"} else "negative"
        n = row["expected_members"]
        ups = latest.get("both_improved")
        pill(283, y, rev, rev_tone)
        pill(425, y, op, op_tone)
        txt(555, y-4, f"{ups}/{n}사" if ups is not None else "—", 20,
            "#253a55" if ups is not None else "#52647a", center=True)
        label, tone = states[row["status"]]
        if row["reason"] == "basket_not_configured":
            label = "미집계"
        elif row["reason"] == "stale_report_quarter":
            label = "기간 경과"
        pill(700, y, label, tone, w=105)
    txt(31, 827, "동반 개선: 매출과 영업이익이 모두 늘어난 기업 수", 17)
    txt(31, 855, "가상 데이터 · 형식 예시" if demo else "미집계: 대표사·실적 입력 전  |  —: 비교값 없음", 17, "#52647a")
    return "\n".join(out + ["</svg>"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    view = parser.add_mutually_exclusive_group()
    view.add_argument("--chart", choices=SECTORS)
    view.add_argument("--overview", action="store_true", help="Render a 10-sector comparison SVG")
    parser.add_argument("--demo", action="store_true", help="Mark an illustrative SVG chart")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        report = sector_financials(payload["sector_financials"], stamp(payload["cutoff"]))
        if args.overview:
            print(overview_svg(report, demo=args.demo))
        elif args.chart:
            print(chart_svg(report, args.chart, demo=args.demo))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    except (TypeError, KeyError, ValueError, OSError, OverflowError) as ex:
        parser.exit(2, f"Input error: {ex}\n")


if __name__ == "__main__":
    main()
