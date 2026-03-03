-- PostgreSQL extensions required by the Mobily Support system
-- This script runs automatically on first container start

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";    -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_trgm";      -- Fuzzy/trigram search (Arabic + English)
CREATE EXTENSION IF NOT EXISTS "unaccent";     -- Accent-insensitive search

-- Allow app_user to use these extensions
GRANT USAGE ON SCHEMA public TO PUBLIC;
