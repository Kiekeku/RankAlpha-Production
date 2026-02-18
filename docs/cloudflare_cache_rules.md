# Cloudflare Cache Rules (Frontend `/api/*`)

This project’s Next.js frontend exposes a public BFF under `GET /api/*` (see `apps/frontend/src/app/api/**`). Most responses already send `Cache-Control: s-maxage=...` suitable for a CDN, but Cloudflare will not cache dynamic `/api/*` by default unless you add Cache Rules.

## Goals

- Cache anonymous **GET/HEAD** requests to public `/api/*` at Cloudflare’s edge.
- Never cache user/admin/auth flows (`/api/admin/*`, `/api/auth/*`, contact endpoints, refresh hooks).
- Respect origin caching headers set by the BFF routes (`s-maxage=...` for cacheable endpoints; `no-store` for sensitive/realtime endpoints).
- There is no Cloudflare purge wired into the pipeline; edge freshness depends on your origin `s-maxage` values (or a versioned cache key strategy).

## Rule Order (highest priority first)

> Create these as Cloudflare **Cache Rules** (Rules → Cache Rules). Exact UI labels vary by Cloudflare plan.

### 1) Bypass non-idempotent `/api/*` requests

- **Name:** `api-bypass-non-get`
- **Expression:**
  - `starts_with(http.request.uri.path, "/api/") and not (http.request.method in {"GET" "HEAD"})`
- **Action:** `Bypass cache`

### 2) Bypass sensitive endpoints (auth/admin/contact/refresh)

- **Name:** `api-bypass-sensitive`
- **Expression (example):**
  - `(http.request.method in {"GET" "HEAD"}) and (`
  - `  starts_with(http.request.uri.path, "/api/auth/")`
  - `  or starts_with(http.request.uri.path, "/api/admin/")`
  - `  or starts_with(http.request.uri.path, "/api/contact")`
  - `  or http.request.uri.path == "/api/refresh-data"`
  - `)`
- **Action:** `Bypass cache`

### 3) Cache public `/api/*` (respect origin `Cache-Control`)

This is the main rule for anonymous traffic. The BFF routes already set per-endpoint `Cache-Control` (short TTLs for frequently changing data; `no-store` for sensitive/realtime paths). Prefer **not** overriding TTLs here—configure Cloudflare so `/api/*` is cacheable *only when the origin says it is cacheable*.

- **Name:** `api-cache-public`
- **Expression (example):**
  - `(http.request.method in {"GET" "HEAD"})`
  - `and starts_with(http.request.uri.path, "/api/")`
  - `and not starts_with(http.request.uri.path, "/api/auth/")`
  - `and not starts_with(http.request.uri.path, "/api/admin/")`
  - `and not starts_with(http.request.uri.path, "/api/contact")`
  - `and http.request.uri.path != "/api/refresh-data"`
- **Action:** `Cache eligible`
- **Edge TTL:** **Use origin cache headers** (do not override)
- **Cache key:**
  - Include **query string** (default; required for pagination/filtering endpoints)
  - **Ignore cookies** (shared cache for anonymous + logged-in users)

## Notes / follow-ups

- Do **not** use “Cache everything” (or an Edge TTL override) for `/api/*` unless you are sure you won’t override `Cache-Control: no-store` on endpoints like `/api/prices/live/*` and screener meta/changes routes.
- `POST /api/refresh-data` triggers Next.js tag revalidation (server-side fetch cache). Cloudflare does not get purged by this hook, so edge freshness still depends on your origin `s-maxage` values.
- If you later introduce personalization outside `/api/admin/*`, revisit Rule #2/#3 (either bypass those paths or vary the cache key).
- Best long-term solution (strong freshness without edge purge) is a **versioned cache key**: append a `?v=<published_at>` (or similar) to requests and only bump it after the pipeline fully succeeds.
