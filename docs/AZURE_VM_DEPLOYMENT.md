# Azure VM Deployment Guide

How to deploy KaiOps on an Azure virtual machine. The same repository and
docker-compose.yml are used everywhere — nothing in the codebase is
cloud-specific (the "GCP Pub/Sub" service is a local emulator container, not a
real GCP dependency). Only the environment file and network setup differ.

## Access you must request first (ask your Azure admin)

1. **Subscription / resource group access** — at minimum Reader to see the VM;
   Contributor (or Virtual Machine Contributor) if you will create/manage it.
2. **A VM** — Linux (Ubuntu 22.04+) or Windows Server. Suggested minimum size
   for the full 22-container stack: 8 vCPU / 16 GB RAM (e.g. Standard_D8s_v5
   or E8s_v5). 100+ GB disk.
3. **A way to connect** — Azure Bastion (browser-based, closest equivalent of
   IAP Desktop) or a direct RDP/SSH NSG rule.
4. **NSG (Network Security Group) inbound rules**:
   - 22 (SSH) or 3389 (RDP) — for you to deploy (Bastion avoids exposing these).
   - 8501 — the UI, for end users.
   - 8010 — the API gateway, if external systems will call it directly.
   - Do NOT open 3306 (MySQL), 6379 (Redis), 9092 (Kafka), 5672/15672
     (RabbitMQ), 9090 (Prometheus) to the network unless explicitly needed.
5. **A static IP** (public, or private if users reach it over VPN/ExpressRoute)
   so DNS entries do not break when the VM restarts.
6. **DNS record (later)** — whoever controls your DNS adds:
   `kaims-dev.com  ->  <VM static IP>`. Until then the app is reachable at
   `http://<VM-IP>:8501`. nginx `server_name` is already set to
   `kaims-dev.com`, and because it is the only server block it also answers
   plain-IP and localhost requests, so nothing breaks before DNS exists.

## Deployment steps on the VM

1. Install Docker Engine + Docker Compose plugin (Linux) or Docker Desktop
   (Windows Server).
2. Get this repository onto the VM (git clone, or copy the folder).
3. Create the environment file from the Azure template:
   ```bash
   cp .env.azure .env      # then edit .env and fill in every REQUIRED value
   ```
   Required before others can reach the VM:
   - `MYSQL_ROOT_PASSWORD`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`
   - `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`
   - `JWT_SECRET_KEY` and the five `*_USER_PASSWORD` values
     (12+ chars, upper/lower/number/special — enforced at startup)
   - `OPENAI_API_KEY` (the only LLM key actually used)
4. Build and start:
   ```bash
   docker compose up -d --build
   ```
5. Verify (same checks as local):
   ```bash
   docker compose ps
   curl http://localhost:8010/healthz
   curl http://localhost:8001/healthz
   curl http://localhost:8501            # UI returns HTTP 200
   ```
6. From your own machine, browse to `http://<VM-IP>:8501`
   (requires the NSG rule for 8501).

## After DNS is added

Once `kaims-dev.com -> <VM IP>` exists, `http://kaims-dev.com:8501` works with
no redeployment. To drop the `:8501` port from the URL, change the UI port
mapping in docker-compose.yml from `"8501:80"` to `"80:80"` (and open port 80
in the NSG instead of 8501).

To test the domain BEFORE DNS exists, add a hosts-file entry on your own
machine pointing `kaims-dev.com` to the VM IP:
- Windows: `C:\Windows\System32\drivers\etc\hosts`
- Linux/macOS: `/etc/hosts`

## Still outstanding (deliberate decisions, not blockers)

- **TLS/HTTPS** — nothing is encrypted in transit yet. Fine inside a trusted
  network; add a reverse proxy (Caddy/nginx + certificate) before wider
  exposure. A real certificate for `kaims-dev.com` needs the DNS record first.
- **Backups** — named Docker volumes (mysql-data, kafka-data, rabbitmq-data,
  redis-data, zookeeper-*, prometheus-data) persist across restarts but live
  on the VM disk; use Azure Backup or scheduled `mysqldump` for real safety.
- **Ingested alerts path** — defaults to `../kaiops-data/ingested_alerts`
  outside the repo (auto-created). Point `INGESTED_ALERTS_HOST_PATH` at a data
  disk if the VM has one.
