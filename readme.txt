
docker-compose -f docker-compose-image-postgres.yml up -d

docker logs -f temporal-admin-tools      # watch real-time DB setup logs
docker logs -f temporal-create-namespace # watch namespace setup logs
docker-compose -f docker-compose-image-postgres.yml down -v

How you access Temporal from your local machine
🔹 1. Temporal Web UI (browser) - Temporal frontend service runs on: port 7233
http://<your-dns-name>:8080
http://temporal-server-demo.australiaeast.cloudapp.azure.com:8080
🔹 2. Temporal Server (SDK / client connection)
client = await Client.connect("temporal-server-demo.australiaeast.cloudapp.azure.com:7233")

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

ssh -o StrictHostKeyChecking=no azureuser@temporal-server-demo.australiaeast.cloudapp.azure.com

upload local folder - sftp
scp -o StrictHostKeyChecking=no -r C:\myproject azureuser@temporal-server-demo.australiaeast.cloudapp.azure.com:/home/azureuser/

git archive -o deploy.tar.gz HEAD
scp -o StrictHostKeyChecking=no deploy.tar.gz azureuser@temporal-server-demo.australiaeast.cloudapp.azure.com:/home/azureuser/
mkdir -p temporal-repo && tar -xzf deploy.tar.gz -C temporal-repo
tar -xzf deploy.tar.gz

# Install Docker + Compose
sudo apt update
sudo apt install -y docker.io docker-compose
sudo apt install python3-pip
sudo usermod -aG docker $USER
newgrp docker

git clone https://github.com/gohils/temporal1-repo.git
cd temporal1-repo/linux_v1
docker-compose -f docker-compose-image-postgres.yml up -d

cd ..
cd temporal_worker
docker-compose -f docker-compose-worker-pattern1.yml up -d
fastapi endpoint -
http://temporal-server-demo.australiaeast.cloudapp.azure.com:8000

# Verify containers are running
docker ps

# Check container logs
docker logs -f wf-worker-pattern1
docker logs -f wf-mgt-api

docker-compose -f docker-compose-worker-pattern1.yml down -v