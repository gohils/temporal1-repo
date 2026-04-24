
# build and deploy container with detached mode (up -d option Run in background)
docker compose -f docker-compose-payment.yml up -d

# Step 1: create .env from terminal
cat > .env <<EOF
POSTGRES_HOST=zdb1.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_USER=sqladmin
POSTGRES_PASSWORD=Zsupabase~1
POSTGRES_DB=temporal
POSTGRES_VISIBILITY_DB=temporal_visibility
EOF

# step 2: run compose with env file
docker-compose --env-file .env -f docker-compose.yml up -d

# Verify containers are running
docker ps

# Check container logs
docker logs -f payment-worker