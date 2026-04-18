#!/bin/sh
set -eu

echo "Starting PostgreSQL schema setup..."

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL port to be available..."
max_attempts=30
attempt=0
until nc -z postgresql 5432; do
  attempt=$((attempt + 1))
  if [ $attempt -ge $max_attempts ]; then
    echo "PostgreSQL did not become available after $max_attempts attempts"
    exit 1
  fi
  echo "PostgreSQL not ready yet, retrying... ($attempt/$max_attempts)"
  sleep 2
done
echo "PostgreSQL port is available"

# Create and setup temporal database
echo "Setting up Temporal DB schema..."
temporal-sql-tool --plugin postgres12 --ep postgresql -u temporal -p 5432 --db temporal create
temporal-sql-tool --plugin postgres12 --ep postgresql -u temporal -p 5432 --db temporal setup-schema -v 0.0
temporal-sql-tool --plugin postgres12 --ep postgresql -u temporal -p 5432 --db temporal update-schema -d /etc/temporal/schema/postgresql/v12/temporal/versioned

# Create and setup visibility database
echo "Setting up Temporal visibility DB schema..."
temporal-sql-tool --plugin postgres12 --ep postgresql -u temporal -p 5432 --db temporal_visibility create
temporal-sql-tool --plugin postgres12 --ep postgresql -u temporal -p 5432 --db temporal_visibility setup-schema -v 0.0
temporal-sql-tool --plugin postgres12 --ep postgresql -u temporal -p 5432 --db temporal_visibility update-schema -d /etc/temporal/schema/postgresql/v12/visibility/versioned

echo "PostgreSQL schema setup complete"