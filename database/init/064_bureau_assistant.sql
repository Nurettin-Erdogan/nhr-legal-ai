\set ON_ERROR_STOP on
-- Include Bureau Assistant owner-isolated storage on fresh installs and CI.
\i /nhr-database/migrations/063_bureau_assistant.sql
