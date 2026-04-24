#!/bin/sh
set -eu

NAMESPACE=${DEFAULT_NAMESPACE:-default}
TEMPORAL_ADDRESS=${TEMPORAL_ADDRESS:-temporal:7233}

host=$(echo "$TEMPORAL_ADDRESS" | cut -d: -f1)
port=$(echo "$TEMPORAL_ADDRESS" | cut -d: -f2)

echo "Waiting for Temporal server port..."
for i in $(seq 1 30); do
  if nc -z "$host" "$port"; then
    break
  fi
  echo "Waiting for Temporal ($i/30)..."
  sleep 2
done

echo "Waiting for Temporal cluster health..."
for i in $(seq 1 10); do
  if temporal operator cluster health --address "$TEMPORAL_ADDRESS" >/dev/null 2>&1; then
    break
  fi
  echo "Cluster not ready ($i/10)..."
  sleep 5
done

echo "Checking namespace..."
if temporal operator namespace describe -n "$NAMESPACE" --address "$TEMPORAL_ADDRESS" >/dev/null 2>&1; then
  echo "Namespace already exists"
else
  echo "Creating namespace..."
  temporal operator namespace create -n "$NAMESPACE" --address "$TEMPORAL_ADDRESS"
fi