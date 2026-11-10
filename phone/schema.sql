-- SentinelDR Phone Schema (SQLite)
-- Standard Library & SQLite only. No foreign extensions.

CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,
    last_heartbeat_at REAL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ownership (
    cluster_id TEXT PRIMARY KEY,
    owner_node_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    lease_id TEXT NOT NULL,
    lease_expires_at REAL NOT NULL,
    granted_by TEXT NOT NULL,
    signature TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    operation_id TEXT PRIMARY KEY,
    sequence_number INTEGER NOT NULL,
    origin_node_id TEXT NOT NULL,
    origin_epoch INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_change_log_origin_seq ON change_log(origin_node_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_change_log_entity ON change_log(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS replication_checkpoint (
    peer_node_id TEXT PRIMARY KEY,
    last_applied_sequence INTEGER NOT NULL DEFAULT 0,
    last_applied_operation_id TEXT,
    last_applied_at REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    node_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO',
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_events_ts ON audit_events(timestamp);

CREATE TABLE IF NOT EXISTS portfolio_profile (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    headline TEXT NOT NULL,
    bio_primary TEXT NOT NULL,
    bio_secondary TEXT,
    cta_text TEXT,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_skills (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    items TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    link TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_contact (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    linkedin TEXT,
    github TEXT,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_resume (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    location TEXT,
    summary TEXT NOT NULL,
    skills TEXT NOT NULL,
    experience TEXT NOT NULL,
    education TEXT NOT NULL,
    template TEXT NOT NULL DEFAULT 'modern',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conflict_records (
    conflict_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    origin_node_id TEXT NOT NULL,
    local_data TEXT NOT NULL,
    remote_data TEXT NOT NULL,
    detected_at REAL NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution_notes TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_experience (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    company TEXT NOT NULL,
    duration TEXT NOT NULL,
    description TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_education (
    id TEXT PRIMARY KEY,
    degree TEXT NOT NULL,
    institution TEXT NOT NULL,
    duration TEXT NOT NULL,
    details TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_certifications (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    issuer TEXT NOT NULL,
    issue_date TEXT,
    credential_id TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_inquiries (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- Durable Alert Outbox for asynchronous, retryable email delivery
CREATE TABLE IF NOT EXISTS alert_outbox (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    sent_at REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alert_outbox_pending ON alert_outbox(sent_at, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_alert_outbox_dedupe ON alert_outbox(dedupe_key, created_at);

-- Incident Tracker Table for end-to-end failover & recovery analytics
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    last_good_heartbeat_at REAL,
    suspected_at REAL,
    promotion_started_at REAL,
    phone_node_active_at REAL,
    writes_accepted_during_outage INTEGER NOT NULL DEFAULT 0,
    laptop_node_first_seen_back_at REAL,
    recovery_started_at REAL,
    replay_complete_at REAL,
    events_replayed_count INTEGER NOT NULL DEFAULT 0,
    failback_completed_at REAL,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    integrity_result TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
