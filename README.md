# Market bottom event study

**v0.1.0 연구 문서:** [리서치 기준서](docs/research-methodology.md) · [데이터·검증 가이드](docs/data-and-validation.md) · [변경 기록](CHANGELOG.md)

A dependency-free Python 3.10+ MVP for reviewing historical KRX bottom candidates, not forecasting a live bottom or sending orders. The supplied prices and evidence are **synthetic**, not backtest evidence.

## Run

```sh
python -m research.backtest --csv examples --ma 3 --peak 3 --horizon 2
python -m unittest discover -s tests -v
# For an independently prepared, closed, normalized snapshot:
python -m research.backtest --sqlite /path/to/study.sqlite
```

The demo produces one confirmed case and reports next-session open reference, confirmation cost versus the candidate low, forward close return, and maximum adverse excursion separately. A reference open is **not** an executable fill or P&L claim; slippage, fees and executable liquidity are not simulated.

## 별도 4단계 주식 리서치

매크로 → 업황·섹터 → 정규장 차트 → 기업 분석 순서로 후보를 검토합니다.
`python -m research.staged --input examples/staged-research.json`으로 가상 예제를 실행할 수 있습니다.
[규칙·입력·제약](docs/staged-research.md)

## Rules, in order

1. **Condition.** At the declared cutoff after a completed session, require all three markets (KOSPI, SK hynix and Samsung Electronics) to close at/below their respective previous-200-session moving average and at least 15% below their respective previous-60-session closing high. Require current VKOSPI at least 30 and a still-current, source-tagged conservative valuation assessment marked supportive by the data producer. Record the three daily lows as anchors. These defaults are transparent research settings, not calibrated thresholds. Use prior calendar sessions, never compress missing observations.
2. **Trigger.** On a later completed session and within 12 calendar entries (trading sessions), take newly available verified evidence of **both** FX and foreign cash flow pressure easing, **or** confirmed relevant earnings/order evidence, **or** enacted targeted policy; a rumor, announcement alone, or unknown classification does not count. For the macro route both pieces must be available within that decision interval. Use the triggering session’s respective highs and VKOSPI close as recovery references.
3. **Retest then confirmation.** On a later session, all three lows must be strictly above their own candidate anchors, and at least one lower than its own preceding-session low so that the rule detects an actual pullback. After this retest, require two consecutive completed sessions with all three closes above their own trigger-session highs and VKOSPI below its own trigger close. A missing confirmation input breaks the streak. A known break of any anchor invalidates the setup; if no break is known but any anchor-check low is missing at cutoff, the setup is censored rather than assumed to hold. The first eligible setup is tracked until resolution; no overlapping detection in this baseline.

For each confirmed setup, Hynix’s **next calendar session’s official open** is the retrospective entry reference. Its ratio to the candidate low minus one is the confirmation-cost benchmark (not a hypothetical fill at the low). Forward return uses the final close and adverse excursion uses the worst low relative to entry, counting the entry session as day one. Missing opening reference, a short calendar horizon, or missing forward bars produces an explicit incomplete status and null forward metrics rather than shortening the horizon. Open setups at sample end are incomplete. After labeling all cases, a condition-only baseline (`candidate_outcome`) is measured from the session after **every** candidate, including invalidated, expired and still-open setups. For confirmed cases, `outcome` is the waiting alternative; a paired comparison is emitted only when both fixed-length paths are complete. Those two paths have different starting dates and may have different end dates. The return/adverse differences are event-study comparisons, not a same-date P&L contest, and the confirmed-only subset has selection bias. Selection, confirmation and forward metrics are not interchangeable.

## Normalized inputs

CSV headers in [examples](examples) and the SQLite [schema](database/schema.sql) are equivalent:

- `sessions`: a complete ordered exchange calendar for the study window, including special openings/closings, exclusion of holidays, and a decision cutoff after each close and before the next open. A missing-data trading day still belongs in this table.
- `bars`: KRX regular-session OHLC for `KOSPI`, `HYNIX`, `SAMSUNG`; `VKOSPI` can provide the close only. Use a common treatment of corporate actions, keep market/session provenance outside this MVP, and supply the true availability time for the **completed** bar. Blank fields are unknown. Never use NXT or indicative auction quotes as KRX opens.
- `evidence`: source-tagged `valuation`, `fx`, `flows`, `earnings`, or `policy` events, their factual event time and first usable/verified availability time, and `support`, `against`, or `unknown`. Use timezone-qualified ISO-8601 clocks, including for retroactive publications. Distinguish verified facts from publication dates, and retain original vintages. The loader accepts one bar per symbol/session and does **not** reconstruct historical revisions.

The previous operational direction-model research archive is **not integrated**. It contains checkpointed records and JSON archive rows, not the aligned, versioned daily OHLC, VKOSPI and point-in-time evidence this study requires. There is no direct table mapping or silent substitution. An independently authorized conversion would first need separate market-data intake and provenance validation. The generic SQLite adapter uses a closed, immutable, read-only snapshot; do not point it at a live WAL-backed file. No actual history, accounts, credentials, or database are included.

## Layout / limitations

- `research/`: working engine and CLI.
- `database/`: generic schema; no production connection or archived data.
- `backend/`: future API boundary reusing the engine, not a running service.
- `frontend/`: future UI boundary; access data through backend only.
- `examples/`, `tests/`: synthetic fixture and reproducibility checks.

This MVP reports all tracked statuses, including expiry, invalidation and censoring. Choose thresholds/measurement windows before real evaluation, compare both successes and failures on point-in-time data, and avoid inferring probability, causation, or tradability from a small event sample. Use an independently verified calendar and source timestamps; the engine does not fetch data or verify source claims.
