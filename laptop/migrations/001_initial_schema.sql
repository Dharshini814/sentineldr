-- SentinelDR Laptop PostgreSQL Migration: 001_initial_schema.sql
-- Compatible with PostgreSQL 14+

CREATE TABLE IF NOT EXISTS nodes (
    node_id VARCHAR(64) PRIMARY KEY,
    role VARCHAR(32) NOT NULL,
    endpoint_url TEXT NOT NULL,
    last_heartbeat_at DOUBLE PRECISION,
    status VARCHAR(32) NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS ownership (
    cluster_id VARCHAR(64) PRIMARY KEY,
    owner_node_id VARCHAR(64) NOT NULL,
    epoch BIGINT NOT NULL,
    lease_id VARCHAR(64) NOT NULL,
    lease_expires_at DOUBLE PRECISION NOT NULL,
    granted_by VARCHAR(64) NOT NULL,
    signature TEXT NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    operation_id UUID PRIMARY KEY,
    sequence_number BIGINT NOT NULL,
    origin_node_id VARCHAR(64) NOT NULL,
    origin_epoch BIGINT NOT NULL,
    schema_version INT NOT NULL DEFAULT 1,
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    operation VARCHAR(16) NOT NULL,
    payload JSONB NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_change_log_origin_seq ON change_log(origin_node_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_change_log_entity ON change_log(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS replication_checkpoint (
    peer_node_id VARCHAR(64) PRIMARY KEY,
    last_applied_sequence BIGINT NOT NULL DEFAULT 0,
    last_applied_operation_id UUID,
    last_applied_at DOUBLE PRECISION,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id UUID PRIMARY KEY,
    timestamp DOUBLE PRECISION NOT NULL,
    node_id VARCHAR(64) NOT NULL,
    epoch BIGINT NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'INFO',
    details JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_events_ts ON audit_events(timestamp);

CREATE TABLE IF NOT EXISTS portfolio_profile (
    id VARCHAR(64) PRIMARY KEY,
    name TEXT NOT NULL,
    headline TEXT NOT NULL,
    bio_primary TEXT NOT NULL,
    bio_secondary TEXT,
    cta_text TEXT,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_skills (
    id VARCHAR(64) PRIMARY KEY,
    category VARCHAR(64) NOT NULL,
    items JSONB NOT NULL,
    display_order INT NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_projects (
    id VARCHAR(64) PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    link TEXT,
    display_order INT NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_contact (
    id VARCHAR(64) PRIMARY KEY,
    email TEXT NOT NULL,
    linkedin TEXT,
    github TEXT,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS conflict_records (
    conflict_id UUID PRIMARY KEY,
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    origin_node_id VARCHAR(64) NOT NULL,
    local_data JSONB NOT NULL,
    remote_data JSONB NOT NULL,
    detected_at DOUBLE PRECISION NOT NULL,
    resolved INT NOT NULL DEFAULT 0,
    resolution_notes TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_experience (
    id VARCHAR(64) PRIMARY KEY,
    role TEXT NOT NULL,
    company TEXT NOT NULL,
    duration TEXT NOT NULL,
    description TEXT,
    display_order INT NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_education (
    id VARCHAR(64) PRIMARY KEY,
    degree TEXT NOT NULL,
    institution TEXT NOT NULL,
    duration TEXT NOT NULL,
    details TEXT,
    display_order INT NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_certifications (
    id VARCHAR(64) PRIMARY KEY,
    name TEXT NOT NULL,
    issuer TEXT NOT NULL,
    issue_date TEXT,
    credential_id TEXT,
    display_order INT NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_inquiries (
    id VARCHAR(64) PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);
