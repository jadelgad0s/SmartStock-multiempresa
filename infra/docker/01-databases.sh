#!/bin/sh
set -e

psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
SELECT format('CREATE DATABASE %I', nombre)
FROM (VALUES ('smartstock_central'), ('ferreteria_la_fragua'), ('repuestos_punto_motor')) AS bases(nombre)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = nombre)
\gexec
SQL
