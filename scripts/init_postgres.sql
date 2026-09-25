-- Run as a PostgreSQL superuser, for example:
--   $env:PGPASSWORD='your-postgres-password'
--   & "C:\Program Files\PostgreSQL\14\bin\psql.exe" -U postgres -d postgres -f scripts\init_postgres.sql

CREATE USER amiri WITH PASSWORD 'amiri';
CREATE DATABASE amiri OWNER amiri;
GRANT ALL PRIVILEGES ON DATABASE amiri TO amiri;
