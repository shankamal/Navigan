-- psql script; connect to an administrative database as an authorized database creator.
-- Example: psql "$ADMIN_DATABASE_URL" -v database_name=navigan -f database/bootstrap/create_database.sql
-- CREATE DATABASE must run outside a transaction. Database name is safely quoted as an identifier.
\set ON_ERROR_STOP on
\if :{?database_name}
\else
  \set database_name navigan
\endif
SELECT format('CREATE DATABASE %I ENCODING %L TEMPLATE template0', :'database_name', 'UTF8')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'database_name')
\gexec
