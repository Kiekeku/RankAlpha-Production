Secure Production Run (Cloudflared)

- Use the override compose file `compose/docker-compose.prod.yml` to avoid publishing internal ports.
- Frontend binds to `127.0.0.1:3000` and should be the only service exposed via Cloudflare Tunnel.

Prereqs
- Cloudflared Tunnel installed and configured.
- A Cloudflare Access policy is recommended for the hostname.

Run
```
export ADMIN_BEARER_TOKEN=$(openssl rand -hex 32)
export CORS_ORIGINS='["https://your.cloudflare.domain"]'
make up-prod
```

Sample cloudflared config
- See `docs/cloudflared.config.example.yml` for a full example.

Cloudflared ingress
```
ingress:
  - hostname: your.cloudflare.domain
    service: http://localhost:3000
  - service: http_status:404
```

Verify
```
docker ps
ss -tulpen | rg ':3000 ' | rg 'LISTEN'
```

Admin endpoints (token‑gated)
```
docker compose -f compose/docker-compose.yml -f compose/docker-compose.prod.yml exec api \
  sh -lc 'curl -s -H "Authorization: Bearer '$ADMIN_BEARER_TOKEN'" -X POST http://localhost:6080/api/v1/admin/weights/recompute'
```

Stop
```
make down-prod
```

Host firewall (UFW)
- Lock down inbound to SSH only; see `docs/UFW_EXAMPLE.md`.
