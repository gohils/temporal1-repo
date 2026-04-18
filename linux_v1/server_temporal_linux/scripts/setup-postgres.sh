#!/bin/sh
set -eu

echo "Starting PostgreSQL schema setup (Azure-ready)..."

# =========================
# SAFETY: Validate env vars
# =========================
if [ -z "${POSTGRES_HOST:-}" ]; then
  echo "ERROR: POSTGRES_HOST is not set"
  exit 1
fi

if [ -z "${POSTGRES_USER:-}" ]; then
  echo "ERROR: POSTGRES_USER is not set"
  exit 1
fi

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo "ERROR: POSTGRES_PASSWORD is not set"
  exit 1
fi

# =========================
# TLS CONFIG (Azure mandatory)
# =========================
export PGSSLMODE=require
export PGSSLROOTCERT=""
export PGSSLMODE=require

echo "Waiting for Azure PostgreSQL..."

# =========================
# Better connectivity check
# (nc is unreliable in containers)
# =========================
max_attempts=30
attempt=0

until timeout 2 bash -c "</dev/tcp/$POSTGRES_HOST/5432" 2>/dev/null; do
  attempt=$((attempt + 1))

  if [ $attempt -ge $max_attempts ]; then
    echo "ERROR: Azure PostgreSQL not reachable after $max_attempts attempts"
    exit 1
  fi

  echo "Waiting for Azure PostgreSQL... ($attempt/$max_attempts)"
  sleep 2
done

echo "Azure PostgreSQL is reachable"

# =========================
# Common TLS flags for Temporal tool
# =========================
TLS_FLAGS="--tls --tls-disable-host-verification"

# =========================
# TEMPORAL DATABASE
# =========================
echo "Setting up Temporal database..."

temporal-sql-tool \
  --plugin postgres12 \
  --ep "$POSTGRES_HOST" \
  --port 5432 \
  -u "$POSTGRES_USER" \
  --pw "$POSTGRES_PASSWORD" \
  --db temporal \
  $TLS_FLAGS \
  setup-schema -v 0.0

temporal-sql-tool \
  --plugin postgres12 \
  --ep "$POSTGRES_HOST" \
  --port 5432 \
  -u "$POSTGRES_USER" \
  --pw "$POSTGRES_PASSWORD" \
  --db temporal \
  $TLS_FLAGS \
  update-schema \
  -d /etc/temporal/schema/postgresql/v12/temporal/versioned

# =========================
# VISIBILITY DATABASE
# =========================
echo "Setting up Visibility database..."

temporal-sql-tool \
  --plugin postgres12 \
  --ep "$POSTGRES_HOST" \
  --port 5432 \
  -u "$POSTGRES_USER" \
  --pw "$POSTGRES_PASSWORD" \
  --db temporal_visibility \
  $TLS_FLAGS \
  setup-schema -v 0.0

temporal-sql-tool \
  --plugin postgres12 \
  --ep "$POSTGRES_HOST" \
  --port 5432 \
  -u "$POSTGRES_USER" \
  --pw "$POSTGRES_PASSWORD" \
  --db temporal_visibility \
  $TLS_FLAGS \
  update-schema \
  -d /etc/temporal/schema/postgresql/v12/visibility/versioned

echo "PostgreSQL schema setup complete"