CREATE TABLE IF NOT EXISTS audit_events (
    id                String,
    created_at        DateTime64(3),
    request_id        String,
    api_key_id        String,
    app_name          LowCardinality(String),
    guardrail         LowCardinality(String),
    guardrail_version UInt32,
    mode              LowCardinality(String),
    action            LowCardinality(String),
    checkpoint        LowCardinality(String),
    checks_fired      Array(LowCardinality(String)),
    verdicts          String,
    tier_reached      LowCardinality(String),
    tainted           UInt8,
    latency_ms        Float32,
    model             LowCardinality(String),
    prompt_tokens     UInt32,
    completion_tokens UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (app_name, created_at, id);
