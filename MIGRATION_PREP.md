# Hermes-Lite VPS Migration Prep

Source VM: `instance-20260413-080555` in `us-central1-c`

Local backup:

`D:\Geek\hermes-lite-agent\migration-backups\hermes-lite-migration-20260623-005006.tar.gz`

SHA256:

`05b6fdc5428385d3b3ae9a896c347c2037fc40d997ec265ce825d53906ca9382`

This archive contains secrets: Hermes `.env*`, New API `.env`, x-ui database,
nginx/certbot material, and systemd unit files. Keep it private.

## Current Service Inventory

- OS: Ubuntu on GCE, x86_64.
- Machine: GCE `e2-micro`, `us-central1-c`, internal IP `10.128.0.3`.
- Current external IP: `34.10.143.63`.
- Disk: 30G root.
- RAM: e2-micro, 954MiB RAM, 2.5GiB swap.
- Hermes-Lite:
  - systemd unit: `/etc/systemd/system/hermes-lite.service`
  - home: `/home/caozuohua99/.hermes-lite`
  - command: `/home/caozuohua99/.hermes-lite/venv/bin/hermes gateway run`
  - env files: `/home/caozuohua99/.hermes-lite/.env`, `.env.lark`
- New API:
  - systemd unit: `/etc/systemd/system/new-api.service`
  - container: `new-api`
  - image: `calciumion/new-api:v1.0.0-rc.11`
  - data: `/root/new-api/data`
  - env: `/root/new-api/.env`
  - binding: `127.0.0.1:3000->3000`
- VPN / proxy:
  - service: `/etc/systemd/system/x-ui.service`
  - binary dir: `/usr/local/x-ui`
  - database: `/etc/x-ui/x-ui.db`
  - x-ui panel process listens on `*:50404`, but GCE firewall denies direct
    public access.
  - xray reality backend: `127.0.0.1:44301`
  - xray internal API: `127.0.0.1:62789`
- Nginx:
  - config: `/etc/nginx/nginx.conf`
  - site: `/etc/nginx/sites-enabled/planb.conf`
  - domains: `xui.caozuohua.cloud-ip.cc`, `api.caozuohua.cloud-ip.cc`
  - SNI routing on `443`: xui/api domains to nginx TLS on `127.0.0.1:8443`,
    all other SNI to xray on `127.0.0.1:44301`.
- Firewall shape:
  - allow public `22`, `80`, `443`
  - public `19591/tcp,udp` rule exists but is disabled
  - deny public direct access to `3000`, `50404`, `44301` via GCE firewall
    rule `deny-internal-services` with target tag `block-direct-ports`
  - local iptables `DOCKER-USER` drops direct `3000,50404`
  - instance tags: `block-direct-ports`, `http-server`, `https-server`

## Restore Order On A New VPS

1. Create a fresh Ubuntu x86_64 VM with at least:
   - 1 vCPU, 1GB RAM, 20GB disk for minimum parity.
   - 2GB swap if using a small free instance.

2. Open firewall ports:
   - `22/tcp`
   - `80/tcp`
   - `443/tcp`
   - keep `3000`, `50404`, `44301` closed to the public internet.
   - keep any direct VPN node port, such as `19591/tcp,udp`, disabled unless
     you intentionally move away from 443 SNI routing.

   On GCE, attach these network tags to the VM:

   ```text
   block-direct-ports,http-server,https-server
   ```

   The `block-direct-ports` tag is required for the high-priority deny rule:

   ```bash
   gcloud compute firewall-rules create deny-internal-services \
     --direction=INGRESS \
     --priority=100 \
     --network=default \
     --action=DENY \
     --rules=tcp:3000,tcp:50404,tcp:44301 \
     --source-ranges=0.0.0.0/0 \
     --target-tags=block-direct-ports \
     --description="Deny public access to bypass-ports; rely on 443 SNI for xray/xui/api"
   ```

3. Upload and unpack the archive:

   ```bash
   sudo tar -C / -xzf hermes-lite-migration-20260623-005006.tar.gz
   sudo chown -R caozuohua99:caozuohua99 /home/caozuohua99/.hermes-lite
   sudo chown -R root:root /root/new-api /etc/x-ui /usr/local/x-ui
   ```

4. Install runtime dependencies:

   ```bash
   sudo apt update
   sudo apt install -y nginx docker.io certbot python3-venv python3-pip sqlite3
   sudo systemctl enable --now docker nginx
   ```

5. Rebuild Hermes runtime:

   ```bash
   cd /home/caozuohua99/.hermes-lite/hermes-agent
   python3 -m venv /home/caozuohua99/.hermes-lite/venv
   /home/caozuohua99/.hermes-lite/venv/bin/pip install -U pip
   /home/caozuohua99/.hermes-lite/venv/bin/pip install -e .
   /home/caozuohua99/.hermes-lite/venv/bin/pip install ddgs
   ```

6. Restore systemd units:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable new-api.service x-ui.service hermes-lite.service iptables-hardening.service
   sudo systemctl restart new-api.service
   sudo systemctl restart x-ui.service
   sudo nginx -t
   sudo systemctl restart nginx.service
   sudo systemctl restart iptables-hardening.service
   sudo systemctl restart hermes-lite.service
   ```

7. Validate locally before DNS cutover:

   ```bash
   systemctl is-active new-api x-ui nginx hermes-lite
   docker ps
   sudo ss -tulpn | grep -E ':(80|443|3000|50404|44301|62789|8443)\b'
   curl -I http://127.0.0.1:3000
   curl -I http://127.0.0.1:50404
   gcloud compute firewall-rules describe deny-internal-services
   sudo journalctl -u hermes-lite -n 100 --no-pager
   ```

8. DNS cutover:
   - Change `api.caozuohua.cloud-ip.cc` and `xui.caozuohua.cloud-ip.cc`
     to the new VPS IP.
   - Keep the old VM running for at least 24 hours after cutover.
   - Reissue certbot certs on the new host if copied certs do not renew cleanly.

9. Final delta backup:
   - Right before shutdown/cutover, stop only the mutable services and copy the
     small databases again:

   ```bash
   sudo systemctl stop hermes-lite new-api x-ui
   sudo sqlite3 /home/caozuohua99/.hermes-lite/state.db ".backup '/tmp/state-final.db'"
   sudo sqlite3 /root/new-api/data/one-api.db ".backup '/tmp/one-api-final.db'"
   sudo sqlite3 /etc/x-ui/x-ui.db ".backup '/tmp/x-ui-final.db'"
   ```
