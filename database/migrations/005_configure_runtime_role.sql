\if :{?runtime_password}
\else
\echo 'HATA: runtime_password zorunludur.'
\quit 3
\endif

\set ON_ERROR_STOP on

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'nhr_runtime'
  ) THEN
    RAISE EXCEPTION
      'nhr_runtime rolü bulunamadı; önce database/init/005_v2_hardening.sql uygulanmalıdır.';
  END IF;
END;
$$;

SELECT format(
  'ALTER ROLE nhr_runtime LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'runtime_password'
)
\gexec

SELECT 'nhr_runtime login enabled' AS result;
