-- Generic normalized study input schema. No legacy operational DB data.
CREATE TABLE sessions (
    day TEXT PRIMARY KEY NOT NULL,       -- exchange trading date YYYY-MM-DD
    opened_at TEXT NOT NULL,             -- ISO-8601 with offset
    closed_at TEXT NOT NULL,             -- ISO-8601 with offset
    decision_at TEXT NOT NULL
);
CREATE TABLE bars (
    day TEXT NOT NULL REFERENCES sessions(day),
    symbol TEXT NOT NULL CHECK (symbol IN ('KOSPI', 'HYNIX', 'SAMSUNG', 'VKOSPI')),
    open REAL, high REAL, low REAL, close REAL,
    available_at TEXT NOT NULL,
    PRIMARY KEY (day, symbol)
);
CREATE TABLE evidence (
    kind TEXT NOT NULL CHECK (kind IN ('valuation','fx','flows','earnings','policy')),
    event_at TEXT NOT NULL,
    available_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('support','against','unknown')),
    source TEXT NOT NULL,
    PRIMARY KEY (kind, available_at)
);
