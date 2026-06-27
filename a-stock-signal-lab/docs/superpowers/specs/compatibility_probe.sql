-- Run inside the exact Hermes container image before choosing optional DDL.
SELECT sqlite_version() AS sqlite_version;
PRAGMA compile_options;
PRAGMA foreign_keys = ON;
PRAGMA foreign_keys;
PRAGMA integrity_check;

-- JSON1 capability probe. If this statement fails, keep JSON validation in the
-- application and integrity suite rather than adding json_valid() CHECK clauses.
SELECT json_valid('{"fenjue":2}') AS json1_available;
