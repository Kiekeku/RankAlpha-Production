# UFW (Ubuntu) Lockdown Example

Goal: default‑deny inbound; allow only SSH from your IP. All app traffic comes via Cloudflared tunnel → loopback, so no public ports are required.

Assumptions
- Ubuntu 22.04/24.04 with UFW available
- SSH port 22 (adjust if custom)

Commands
```bash
# 1) Enable IPv6 rules as well (if using IPv6)
sudo sed -i 's/^IPV6=.*/IPV6=yes/' /etc/ufw/ufw.conf

# 2) Reset to a clean baseline (DANGEROUS: drops existing rules)
sudo ufw --force reset

# 3) Default‑deny inbound, allow outbound
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 4) Allow SSH only from your admin IP(s)
MY_IP=203.0.113.10
sudo ufw allow from $MY_IP to any port 22 proto tcp

# Optional: allow from a second trusted IP
# sudo ufw allow from 198.51.100.20 to any port 22 proto tcp

# 5) Enable
sudo ufw enable

# 6) Review
sudo ufw status verbose
```

Notes
- Portainer (9443), Docker‑published dev/test ports, RabbitMQ mgmt, Airflow, etc. should NOT be allowed publicly.
- For occasional remote DB access, use SSH port‑forwarding (ssh -L) instead of opening Postgres.
- If you change SSH port, update the rule and test in a second session before closing your current SSH session.

