#!/bin/sh
set -eu

NAMESPACE=${DEFAULT_NAMESPACE:-default}
TEMPORAL_ADDRESS=${TEMPORAL_ADDRESS:-temporal-server:7233}

echo "Waiting for Temporal server port to be available..."
max_attempts=30
attempt=0
host=$(echo $TEMPORAL_ADDRESS | cut -d: -f1)
port=$(echo $TEMPORAL_ADDRESS | cut -d: -f2)
until nc -z $host $port; do
  attempt=$((attempt + 1))
  if [ $attempt -ge $max_attempts ]; then
    echo "Temporal server did not become available after $max_attempts attempts"
    exit 1
  fi
  echo "Temporal server not ready yet, retrying... ($attempt/$max_attempts)"
  sleep 2
done
echo "Temporal server port is available"

echo "Waiting for Temporal server to report healthy..."
max_attempts_health=10
attempt_health=0
until temporal operator cluster health --address $TEMPORAL_ADDRESS; do
  attempt_health=$((attempt_health + 1))
  if [ $attempt_health -ge $max_attempts_health ]; then
    echo "Temporal server did not become healthy after $max_attempts_health attempts"
    exit 1
  fi
  echo "Temporal server not healthy yet, retrying... ($attempt_health/$max_attempts_health)"
  sleep 5
done
echo "Temporal server is healthy"

# Create namespace if it doesn't exist
if temporal operator namespace describe -n $NAMESPACE --address $TEMPORAL_ADDRESS >/dev/null 2>&1; then
  echo "Namespace '$NAMESPACE' already exists"
else
  echo "Creating namespace '$NAMESPACE'..."
  temporal operator namespace create -n $NAMESPACE --address $TEMPORAL_ADDRESS
  echo "Namespace '$NAMESPACE' created"
fi