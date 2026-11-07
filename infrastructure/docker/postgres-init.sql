-- Runs once, the first time the Postgres volume is created (local development only).
-- Owner role "app" runs migrations. Runtime role "agent_app" is NOT a superuser and
-- cannot bypass Row Level Security. Passwords here are for local development only.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE ROLE agent_app LOGIN PASSWORD 'agent_app'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE agentplatform TO agent_app;
GRANT USAGE ON SCHEMA public TO agent_app;

-- Tables and sequences created later by "app" (via Alembic) are usable by "agent_app".
ALTER DEFAULT PRIVILEGES FOR ROLE app IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agent_app;
ALTER DEFAULT PRIVILEGES FOR ROLE app IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO agent_app;
