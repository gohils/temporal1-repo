
docker compose -f docker-compose-postgres.yml up -d

docker compose -f docker-compose-worker-fastapi.yml up -d

docker logs -f temporal-admin-tools      # watch real-time DB setup logs
docker logs -f temporal-create-namespace # watch namespace setup logs
docker compose -f docker-compose-postgres.yml down -v

# Create Spot VM
az vm create \
  --resource-group 1-ai-llm-rg \
  --name temporal-server-vm \
  --image Ubuntu2204 \
  --size Standard_D2as_v5 \
  --priority Spot \
  --eviction-policy Deallocate \
  --max-price -1 \
  --admin-username azureuser \
  --ssh-key-values ~/.ssh/id_rsa.pub \
  --public-ip-address-dns-name temporal-server-demo

# Open ports for demo only
az vm open-port --resource-group 1-ai-llm-rg --name temporal-server-vm --port "*"

# SSH into VM
ssh azureuser@temporal-server-demo.australiaeast.cloudapp.azure.com

# Install Docker + Compose
sudo apt update
sudo apt install -y docker.io docker-compose
sudo usermod -aG docker $USER
newgrp docker

docker-compose -f docker-compose-image-postgres.yml up -d