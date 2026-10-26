-- NetworkMeasureBox schema v1
-- Timestamps: INTEGER unix epoch milliseconds (UTC). Compact + index friendly.
-- Hot tables are WITHOUT ROWID where the PK is naturally the access path.

PRAGMA user_version = 1;

-- Key/value runtime config & state (web UI / netd mode)
CREATE TABLE IF NOT EXISTS kv (
    k   TEXT PRIMARY KEY,
    v   TEXT NOT NULL,
    ts  INTEGER NOT NULL
) WITHOUT ROWID;

-- Probe targets (1.1.1.1, 8.8.8.8, ...); small int FK keeps samples narrow
CREATE TABLE IF NOT EXISTS target (
    id      INTEGER PRIMARY KEY,
    addr    TEXT NOT NULL UNIQUE,
    label   TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    role    TEXT NOT NULL DEFAULT 'Public DNS'
);

-- Raw latency samples (highest volume table). rtt_us NULL = lost.
CREATE TABLE IF NOT EXISTS ping_sample (
    ts        INTEGER NOT NULL,
    target_id INTEGER NOT NULL REFERENCES target(id),
    rtt_us    INTEGER,
    PRIMARY KEY (target_id, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_ping_ts ON ping_sample(ts);

-- 1-minute rollups (kept far longer than raw samples; feeds reports)
CREATE TABLE IF NOT EXISTS ping_minute (
    ts        INTEGER NOT NULL,           -- minute bucket start
    target_id INTEGER NOT NULL REFERENCES target(id),
    sent      INTEGER NOT NULL,
    lost      INTEGER NOT NULL,
    rtt_min   INTEGER, rtt_avg INTEGER, rtt_max INTEGER,
    rtt_p95   INTEGER,
    jitter_us INTEGER,                    -- RFC3550-style mean |delta|
    PRIMARY KEY (target_id, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_ping_minute_ts ON ping_minute(ts);

-- Speedtest results
CREATE TABLE IF NOT EXISTS speedtest (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    trigger     TEXT NOT NULL CHECK (trigger IN ('schedule','manual','telegram','web')),
    status      TEXT NOT NULL CHECK (status IN ('ok','skipped_busy','error')),
    server_id   INTEGER, server_name TEXT,
    down_bps    INTEGER, up_bps INTEGER,
    ping_us     INTEGER, jitter_us INTEGER, loss_pct REAL,
    result_url  TEXT,
    raw_json    TEXT,
    error       TEXT,
    down_loaded_lat_ms REAL,
    up_loaded_lat_ms REAL,
    bufferbloat_grade TEXT,
    bufferbloat_delta_ms REAL,
    connection_type TEXT,
    client_ip TEXT,
    client_ipv6 TEXT,
    server_host TEXT,
    server_location TEXT,
    engine TEXT DEFAULT 'ookla',
    colo TEXT,
    bound_iface TEXT,
    bound_ip TEXT,
    retransmits INTEGER,
    tcp_window TEXT
);
CREATE INDEX IF NOT EXISTS ix_speedtest_ts ON speedtest(ts);

-- Net-neutrality / port throttling checks
CREATE TABLE IF NOT EXISTS port_check (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    proto       TEXT NOT NULL CHECK (proto IN ('tcp','udp')),
    port        INTEGER NOT NULL,
    endpoint    TEXT NOT NULL,
    bps         INTEGER,
    baseline_bps INTEGER,
    ratio       REAL,                     -- bps / baseline
    verdict     TEXT NOT NULL CHECK (verdict IN ('ok','throttled','blocked','error'))
);
CREATE INDEX IF NOT EXISTS ix_port_check_ts ON port_check(ts);

-- Link / mode / failover / outage events
CREATE TABLE IF NOT EXISTS event (
    id       INTEGER PRIMARY KEY,
    ts       INTEGER NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('debug','info','warn','crit')),
    source   TEXT NOT NULL,              -- netd, probe, speed, bot...
    kind     TEXT NOT NULL,              -- mode_change, link_down, outage_start...
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS ix_event_ts ON event(ts);
CREATE INDEX IF NOT EXISTS ix_event_kind_ts ON event(kind, ts);

-- Outage windows derived from probes (all targets lost)
CREATE TABLE IF NOT EXISTS outage (
    id        INTEGER PRIMARY KEY,
    start_ts  INTEGER NOT NULL,
    end_ts    INTEGER,                    -- NULL = ongoing
    cause     TEXT
);
CREATE INDEX IF NOT EXISTS ix_outage_start ON outage(start_ts);

-- Interface counter snapshots (traffic gate history, low rate)
CREATE TABLE IF NOT EXISTS iface_stat (
    ts       INTEGER NOT NULL,
    iface    TEXT NOT NULL,
    rx_bps   INTEGER NOT NULL,
    tx_bps   INTEGER NOT NULL,
    PRIMARY KEY (iface, ts)
) WITHOUT ROWID;

-- Alert dedup / history (Telegram)
CREATE TABLE IF NOT EXISTS alert (
    id      INTEGER PRIMARY KEY,
    ts      INTEGER NOT NULL,
    rule    TEXT NOT NULL,
    state   TEXT NOT NULL CHECK (state IN ('firing','resolved')),
    message TEXT
);
CREATE INDEX IF NOT EXISTS ix_alert_rule_ts ON alert(rule, ts);

INSERT OR IGNORE INTO target(id, addr, label) VALUES
    (1, '1.1.1.1',         'Cloudflare'),
    (2, '8.8.8.8',         'Google'),
    (3, '9.9.9.9',         'Quad9'),
    (4, '185.222.222.222', 'DNS.SB');
