-- SentinelDR PostgreSQL Database Setup
-- 
-- WARNING: Run this script once only.
-- Running it again will error if user/database already exist.
-- To reset: DROP DATABASE sentineldr; DROP USER sentineldr;

-- Create database user with password
-- This user will own the SentinelDR database
CREATE USER sentineldr WITH PASSWORD 'sentineldr_secure_pass_2024';

-- Create database owned by the SentinelDR user
-- This isolates SentinelDR data from other applications
CREATE DATABASE sentineldr OWNER sentineldr;

-- Grant all privileges to ensure user can manage the database
-- Includes CREATE, ALTER, DROP table permissions
GRANT ALL PRIVILEGES ON DATABASE sentineldr TO sentineldr;

-- Connect to the new database (run this manually in psql)
\c sentineldr

-- NOTE: Database tables will be created automatically by SQLAlchemy
-- when the laptop node starts for the first time. The following tables
-- will be created:
--   - projects (portfolio data with sync versioning)
--   - events (system events and alerts)
--   - sync_metadata (synchronization state tracking)
--
-- No manual table creation is required.