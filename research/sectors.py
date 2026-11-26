"""Stage 2 sector dashboard: 10 sectors, independent evidence profiles, no trades."""
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
class Axis:
    key: str
    title: str
    unit: str = "%"
    direction: int = 1


@dataclass(frozen=True)
class Profile:
    key: str
    sector: str
    title: str
    primary: Axis
    secondary: Axis
    frequency: str
    comparison: str
    max_age_days: int


def volume(key, title):
    return Axis(key, title)


def ratio(key, title, direction=1):
    return Axis(key, title, "%p", direction)


def memory(key, title):
    return Profile(key, "semiconductor", title, volume("orders", "제품 주문 물량"),
                   volume("contract_price", "동일 규격 계약가"), "quarter", "qoq", 145)


SECTORS = {
    "semiconductor": "반도체", "autos": "자동차·부품", "shipbuilding": "조선",
    "electrical": "전력기기", "defense": "방산", "battery": "2차전지",
    "cosmetics": "화장품", "healthcare": "바이오·헬스케어", "games": "게임", "entertainment": "엔터",
}
PROFILES = (
    memory("hbm", "HBM"),
    memory("server_dram", "서버 DDR5 DRAM"),
    memory("enterprise_ssd", "기업용 SSD"),
    Profile("autos", "autos", "신차 시장", volume("sales_units", "신차 판매량"),
            ratio("incentive_ratio", "인센티브/판매가격 비율", -1), "month", "yoy", 75),
    Profile("shipbuilding", "shipbuilding", "상선", volume("signed_cgt", "확정 신규 수주 CGT"),
            volume("matched_newbuild_price", "동일 선종·규격 신조선가"), "month", "yoy", 75),
    Profile("electrical", "electrical", "전력 변압기", volume("transformer_orders", "취소 차감 변압기 수주액"),
            volume("matched_transformer_price", "동일 규격 계약단가"), "quarter", "yoy", 145),
    Profile("defense", "defense", "지상방산", volume("signed_orders", "확정 신규 계약액"),
            ratio("on_time_deliveries", "계획 대비 정시 인도율"), "quarter", "yoy", 145),
    Profile("battery", "battery", "EV 배터리", volume("battery_shipments", "동일 업체군 EV 배터리 출하 GWh"),
            ratio("plant_utilization", "동일 EV 배터리 생산라인 가동률"), "quarter", "yoy", 145),
    Profile("cosmetics", "cosmetics", "K-뷰티", volume("cosmetics_exports", "화장품 수출액 USD"),
            volume("reorders", "동일 상품군·시장 유통 재주문 물량"), "month", "yoy", 75),
    Profile("healthcare", "healthcare", "바이오 CDMO", volume("signed_bookings", "확정 신규 CDMO 수주액"),
            ratio("plant_utilization", "동일 CDMO 생산라인 가동률"), "quarter", "yoy", 145),
    Profile("games", "games", "게임 타이틀", volume("net_sales_units", "동일 타이틀 순판매 수량"),
            ratio("d30_retention", "동일 타이틀 유입 코호트 D30 유지율"), "month", "yoy", 75),
    Profile("entertainment", "entertainment", "공연", volume("paid_attendance", "동일 범위 유료 관객 수"),
            volume("real_ticket_price", "동일 범위·통화 실질 유료 티켓단가"), "quarter", "yoy", 145),
)
BY_KEY = {p.key: p for p in PROFILES}
GRADES = {"observed", "estimate", "proxy", "outlook"}


def required_text(v, key):
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{key} must be nonempty")
    return v.strip()


def period_window(d, period):
    if not isinstance(period, str):
        raise ValueError("Invalid sector period")
    if d.frequency == "month":
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            raise ValueError(f"{d.key} requires YYYY-MM")
        y, m = map(int, period.split("-"))
        end_month = m
    else:
        if not re.fullmatch(r"\d{4}-Q[1-4]", period):
            raise ValueError(f"{d.key} requires YYYY-Qn")
        y, m = map(int, period.split("-Q"))
        end_month = m * 3
    next_y, next_m = (y + 1, 1) if end_month == 12 else (y, end_month + 1)
    return date(next_y, next_m, 1) - timedelta(days=1)


def read_row(row):
    key = row["profile"]
    d = BY_KEY.get(key)
    if d is None:
        raise ValueError(f"Unknown sector profile {key}")
    metric, grade = row["metric"], row["grade"]
    if grade not in GRADES:
        raise ValueError(f"Invalid evidence grade: {grade}")
    axes = {x.key: x for x in (d.primary, d.secondary)}
    if metric not in (*axes, "context"):
        raise ValueError(f"{key} metric not configured: {metric}")
    period = row["period"]
    end = period_window(d, period)
    available = stamp(row["available_at"])
    scope = required_text(row["scope"], "scope")
    source = required_text(row["source"], "source")
    note = required_text(row["note"], "note")
    value = row.get("value")
    if metric == "context":
        if value is not None:
            raise ValueError("Context has no gate value; put the fact in note")
    else:
        if (type(value) not in (float, int) or not math.isfinite(value)
                or row.get("unit") != axes[metric].unit
                or row.get("comparison") != d.comparison):
            raise ValueError(f"Invalid value, unit or comparison for {key}/{metric}")
    if grade != "outlook" and end > date.fromisoformat(row["available_at"][:10]):
        raise ValueError(f"{key} observation refers to an unfinished period; classify as outlook")
    return key, end, available, dict(profile=key, metric=metric, period=period, scope=scope,
        grade=grade, unit=row.get("unit"), comparison=row.get("comparison"), value=value,
        source=source, note=note, available_at=available.isoformat())


def screen_sectors(rows, cutoff, scopes=None):
    scopes = scopes or {}
    for k, v in scopes.items():
        if k not in BY_KEY:
            raise ValueError(f"Unknown sector scope profile: {k}")
        required_text(v, "selected scope")
    groups = {k: [] for k in SECTORS}
    by_key = {k: [] for k in BY_KEY}
    duplicate = set()
    for row in rows:
        k, end, available, item = read_row(row)
        identity = (k, item["metric"], item["period"], item["scope"], item["grade"], available,
                    item["note"] if item["metric"] == "context" else "")
        if identity in duplicate:
            raise ValueError(f"Duplicate sector vintage: {k}/{item['metric']}")
        duplicate.add(identity)
        if available <= cutoff:
            by_key[k].append((end, available, item))

    for d in PROFILES:
        all_rows = sorted(by_key[d.key], key=lambda x: (x[0], x[1]), reverse=True)
        scope = scopes.get(d.key)
        eligible = [x for x in all_rows if x[2]["metric"] != "context" and x[2]["grade"] == "observed"
                    and (cutoff.date() - x[0]).days <= d.max_age_days]
        visible_scopes = {x[2]["scope"] for x in eligible}
        if scope is None and len(visible_scopes) == 1:
            scope = next(iter(visible_scopes))
        eligible = [x for x in eligible if x[2]["scope"] == scope]
        current = eligible[0][0] if eligible else None
        evidence = {}
        for end, _, item in eligible:
            if end == current:
                evidence.setdefault(item["metric"], item)
        missing = [a.key for a in (d.primary, d.secondary) if a.key not in evidence]
        if len(visible_scopes) > 1 and scope is None:
            status, reason = "unknown", "choose_a_single_scope"
        elif missing:
            status, reason = "unknown", "missing_matched_observed_pair"
        else:
            x, y = (evidence[a.key]["value"] * a.direction for a in (d.primary, d.secondary))
            if x > 0 and y > 0:
                status, reason = "pass", "both_improving"
            elif x < 0 and y < 0:
                status, reason = "fail", "both_deteriorating"
            else:
                status, reason = "hold", "mixed_or_flat"
        groups[d.sector].append({**asdict(d), "status": status, "reason": reason,
            "scope": scope, "missing": missing, "gate_evidence": evidence,
            "research_context": [item for _, _, item in all_rows]})
    return {"mode": "sector_research_only", "cutoff": cutoff.isoformat(),
            "sectors": [{"key": k, "name": name, "profiles": groups[k]} for k, name in SECTORS.items()]}


LABELS = {"pass": "통과", "hold": "혼조·보류", "fail": "탈락", "unknown": "미확인"}


def markdown(report):
    def esc(s):
        return str(s).replace("|", "\\|").replace("\n", " ")
    lines = ["# 2차 업황·섹터", "", f"기준시각: {report['cutoff']}", "",
             "| 섹터 / 분석 범위 | 수요 | 두 번째 확인선 | 판정 |",
             "|---|---|---|---|"]
    for g in report["sectors"]:
        for p in g["profiles"]:
            def cell(axis):
                e = p["gate_evidence"].get(axis["key"])
                return f"{axis['title']} {e['value']:+g}{axis['unit']} ({e['period']})" if e else f"{axis['title']} 미확인"
            title = g["name"] + " / " + p["title"]
            lines.append("| " + " | ".join(map(esc, (title, cell(p["primary"]),
                                            cell(p["secondary"]), LABELS[p["status"]]))) + " |")
    lines.extend(["", "## 참고 근거 (자동 판정과 별도)", ""])
    for g in report["sectors"]:
        for p in g["profiles"]:
            for e in p["research_context"]:
                lines.append(f"- {p['title']} · {e['period']} · {e['grade']}: "
                             f"{esc(e['note'])} ({esc(e['source'])})")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--format", choices=("json", "markdown"), default="json")
    a = p.parse_args()
    try:
        data = json.loads(a.input.read_text(encoding="utf-8-sig"))
        out = screen_sectors(data["observations"], stamp(data["cutoff"]), data.get("scopes"))
        print(markdown(out) if a.format == "markdown" else
              json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError) as ex:
        p.exit(2, f"Input error: {ex}\n")


if __name__ == "__main__":
    main()
