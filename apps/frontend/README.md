# RankAlpha Frontend Application

## Purpose
The Frontend application provides a modern, responsive web interface for the RankAlpha financial analysis platform. It delivers real-time market insights, stock grading visualizations, signal analysis, and backtesting capabilities through an intuitive user experience.

## Technologies & Tools

### Core Framework
- **Next.js 14**: React framework with App Router for server-side rendering and routing
- **React 18**: Component-based UI library with hooks
- **TypeScript**: Type-safe development with compile-time checking

### UI & Styling
- **Tailwind CSS**: Utility-first CSS framework for rapid styling
- **Radix UI**: Unstyled, accessible component primitives
- **shadcn/ui**: Pre-built component library built on Radix UI
- **Class Variance Authority (CVA)**: Component variant management
- **Lucide Icons**: Comprehensive icon library

### Data Management
- **TanStack Query (React Query)**: Server state management and caching
- **Axios**: HTTP client for API communication
- **OpenAPI TypeScript**: Auto-generated types from API schema

### Data Visualization
- **Recharts**: Composable charting library for React
- **Lightweight Charts**: High-performance financial charts (TradingView)
- **TanStack Table**: Powerful data table with sorting/filtering

### Development Tools
- **ESLint**: Code linting and style enforcement
- **TypeScript Compiler**: Type checking
- **Next.js Dev Server**: Hot module replacement
- **Playwright**: End-to-end browser testing

## Design Principles

### 1. **Component-Based Architecture**
- Reusable UI components with clear separation of concerns
- Composition over inheritance
- Single responsibility principle for each component

### 2. **Type Safety First**
- TypeScript throughout the codebase
- Auto-generated API types from OpenAPI schema
- Runtime validation for critical data flows

### 3. **Server-Side Rendering (SSR)**
- Improved SEO and initial page load performance
- Dynamic metadata generation
- Server Components for reduced client bundle size

### 4. **Responsive Design**
- Mobile-first approach
- Breakpoint-based layouts
- Touch-friendly interactions

### 5. **Performance Optimization**
- Code splitting and lazy loading
- Image optimization with Next.js Image component
- Efficient re-rendering with React Query caching
- Automatic data refresh on backend updates

## Project Structure

### Directory Layout
```
src/
├── app/                    # Next.js App Router pages
│   ├── layout.tsx         # Root layout with providers
│   ├── page.tsx          # Home page
│   ├── ai-analysis/      # AI analysis list + detail routes
│   │   ├── page.tsx      # List & filters (latest analyses)
│   │   ├── [symbol]/     # Latest analysis by symbol
│   │   └── id/[id]/      # Specific analysis by UUID
│   ├── explore/          # Unified leaderboard + screener entry point
│   ├── grades/           # Grading system pages
│   ├── signals/          # Signal analysis pages
│   ├── backtest/         # Backtesting interface
│   └── pipeline/         # Pipeline monitoring
├── components/           # Reusable React components
│   ├── ui/              # Base UI components (shadcn)
│   ├── charts/          # Chart components
│   ├── tables/          # Data table components
│   └── layout/          # Layout components
├── features/             # Cross-route feature modules (e.g., explore)
│   └── explore/          # Shared leaderboard + screener views
├── lib/                 # Utility functions and helpers
│   ├── api.ts          # API client configuration
│   ├── utils.ts        # Common utilities
│   └── hooks/          # Custom React hooks
└── types/              # TypeScript type definitions
    └── api.ts          # Auto-generated API types
```

## Dev Tips

### zsh path globbing (`[]`)
Some paths in the Next.js App Router use dynamic segment folders like `[symbol]`. In `zsh`, unquoted `[]` are treated as glob patterns and can error with `no matches found`.

Use one of:

- Quote the path: `sed -n '1,40p' 'src/app/api/prices/live/[symbol]/route.ts'`
- Escape brackets: `sed -n '1,40p' src/app/api/prices/live/\\[symbol\\]/route.ts`
- Prefix with `noglob`: `noglob rg -n "proxyGetJson" src/app/api/prices/live/[symbol]/route.ts`

### `find` with `-o`
If you use `find` with `-o` (OR), wrap the name tests in parentheses so `-type f` applies to both branches:

`find src/app -type f \\( -name 'page.tsx' -o -name 'page.ts' \\)`

### Dark Reader hydration warnings
If you use the Dark Reader browser extension in dev, you may see React hydration warnings like:
`Warning: Extra attributes from the server: data-darkreader-inline-stroke, style`
This is caused by the extension injecting attributes into SVGs before hydration. Disable Dark Reader (or use an extension-free profile) to verify whether a hydration warning is real.

## End-to-End Tests (Playwright)

From `apps/frontend`:

```
pnpm exec playwright install
pnpm test:e2e
pnpm test:e2e:ui
```

By default, the tests will spin up `pnpm dev` on `http://localhost:3000`.

Optional:
- `PLAYWRIGHT_BASE_URL=http://localhost:3000 pnpm test:e2e` (override target URL)
- `PLAYWRIGHT_NO_WEB_SERVER=1 pnpm test:e2e` (skip auto-starting Next)
- `PLAYWRIGHT_REUSE_SERVER=1 pnpm test:e2e` (reuse existing dev server on port 3000)
- `PLAYWRIGHT_MOCKS=1 pnpm test:e2e` (enable mock AI detail payloads when reusing a server)

### Core Features

#### Overview Dashboard
- **Pipeline Health**: Real-time status of data processing components
- **Top Performers**: Highest-rated stocks with grade explanations
- **Key Metrics**: Market trends and summary statistics
- **Data Freshness**: Last update timestamps and refresh controls

#### Explore Leaderboard
- **Multi-Signal Analysis**: `/explore` defaults to the leaderboard tab highlighting momentum, value, and sentiment scores
- **Unified Filters**: Search, grade, and sector filters drive both the standalone leaderboard and the Explore view
- **Sortable Rankings**: Toggle sort by grade or factor scores with responsive pagination controls
- **Regime + Methodology Tabs**: Built-in market structure + methodology context beside the rankings

#### Asset Detail Pages
- **Comprehensive Analysis**: Individual stock deep-dive
- **Interactive Charts**: Price history with technical indicators
- **Live Price Snapshot**: Real-time quote sourced via the broker service proxy
- **Sentiment Timeline**: Historical sentiment with catalysts
- **Peer Comparison**: Compare against sector peers
 - **AI Analysis (new)**: Dedicated pages under `/ai-analysis` to list and view AI outputs
   - `/ai-analysis` – filters + pagination over `vw_ai_analysis_full`
   - `/ai-analysis/[symbol]` – latest for a symbol
   - `/ai-analysis/id/[analysis_id]` – specific record

#### Screener Consensus (Explore Tab)
- **Consensus View**: `/explore?view=screener` renders the latest-day per-symbol aggregation across screener styles/sources
- **Rich Filters**: Min appearances, styles, symbol search, style/source logic toggles, and long/short bias selections
- **Breadth + Changes**: Flow vs. legacy breadth charts plus change feeds live beside the table for quick context

#### Backtest Tool
- **Strategy Builder**: Visual strategy configuration
- **Performance Metrics**: Sharpe ratio, max drawdown, returns
- **Comparison Mode**: Test multiple strategies simultaneously
- **Historical Simulation**: Test strategies on past data

### Custom Hooks

#### `useDataRefresh`
```typescript
// Automatic data refresh when backend updates
const { lastRefresh, isRefreshing } = useDataRefresh({
  pollingInterval: 60000, // Check every minute
  onNewData: () => toast.success("New data available!")
});
```

#### `useManualRefresh`
```typescript
// Manual refresh trigger for user-initiated updates
const { refresh, isRefreshing } = useManualRefresh();
```

#### `useApi`
```typescript
// Type-safe API wrapper
const { data, isLoading, error } = useApi<GradeResponse>({
  endpoint: '/grades',
  params: { symbol: 'AAPL' }
});
```

## State Management

### Server State (React Query)
```typescript
// Query configuration with smart caching
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      cacheTime: 10 * 60 * 1000, // 10 minutes
      refetchOnWindowFocus: false,
    },
  },
});
```

## Caching & Symbol Normalization

- **Symbol normalization:** frontend requests normalize ticker symbols to uppercase (`aapl` → `AAPL`) so routing and caching stay consistent.
- **BFF/API caching:** Next.js `app/api/*` routes proxy to the FastAPI backend and set `s-maxage` / `stale-while-revalidate` on most read endpoints.
- **Live prices:** `/api/prices/live/:symbol` is treated as user-specific and is served with `Cache-Control: no-store` (API-side Redis caching still applies for authenticated users).
- **API base + prefix:** server-side API calls use `INTERNAL_API_URL` + a fixed backend prefix of `/api/v1` (see `apps/frontend/src/lib/api/index.ts`). When setting `INTERNAL_API_URL`, provide the **host only** (e.g., `http://localhost:6080`), not `/api/v1`.

## Running the Application

### Local Development
```bash
cd apps/frontend
pnpm install
pnpm dev
# Opens at http://localhost:3000
```

### Production Build
```bash
pnpm build
pnpm start
```

### Docker Deployment
```bash
# Multi-stage build for optimized image
docker build -t rankalpha-frontend .
docker run -p 3000:3000 -e NEXT_PUBLIC_API_URL=http://localhost:6080 rankalpha-frontend
```

#### Docker build-time env vs runtime env

Next.js bakes many `process.env.*` values into the production bundle at **build time** (during `pnpm run build` in the Dockerfile).
That means:

- **Runtime** env (Compose `env_file:` / `environment:` or `docker run -e ...`) affects the running container, but **does not** change values already baked into the JS bundle.
- To ensure canonicals/sitemaps/analytics IDs are correct, you must also pass those values at **build time** via Docker build args (or via Compose `build.args`).

Example build with explicit args:

```bash
docker build \
  --build-arg NEXT_PUBLIC_API_URL=http://api:6080 \
  --build-arg NEXT_PUBLIC_SITE_URL=https://rankalpha.example.com \
  --build-arg NEXTAUTH_URL=https://rankalpha.example.com \
  --build-arg NEXT_PUBLIC_GTM_ID=GTM-XXXXXXX \
  -t rankalpha-frontend .
```

### Type Generation
```bash
# Generate TypeScript types from OpenAPI schema
pnpm generate-types
```

## Environment Variables

The frontend reads the following environment variables. Many of these are **build-time** values for Next.js, so in Docker/CI you should pass them as **build args** (see above) or via Compose `build.args`.

| Variable | Required | Purpose | Default / Fallback |
| -------- | -------- | ------- | ------------------- |
| `NEXT_PUBLIC_API_URL` | Yes (production) | Base URL for the RankAlpha API that the browser should call. Needed for client-side fetches and React Query hooks. | Defaults to `http://api:6080` when unspecified (suitable for Docker Compose network).
| `NEXT_PUBLIC_SITE_URL` | Recommended (production) | Public base URL of the frontend used to build absolute canonicals and sitemap URLs. | Falls back to `NEXTAUTH_URL`, then `VERCEL_URL`, else `http://localhost:3000`.
| `NEXTAUTH_URL` | Recommended (production) | NextAuth base URL; also used as a fallback canonical base when `NEXT_PUBLIC_SITE_URL` is not set. | Empty.
| `NEXT_PUBLIC_GTM_ID` | Optional | Google Tag Manager container ID for analytics. Enables pageview events when provided. | Falls back to `GTM-K3NWTMW8` (current shared container).
| `NEXT_PUBLIC_SHOW_RAW_DATA` | Optional | Toggle raw market data display (prices/fundamentals). When `false`, raw values are hidden and price charts normalize to a 100-index trend. | Defaults to `true`.
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | Optional | Cloudflare Turnstile site key for the contact form challenge. Without it, the form renders without bot protection. | Empty string disables the Turnstile widget.

## Backend APIs used
- `GET /api/v1/ai-analysis` (and `/id/{analysis_id}`, `/{symbol}`)
- `GET /api/v1/screener/consensus`
 - Regime (intensity): `GET /api/v1/screener/regime/latest`, `GET /api/v1/screener/regime/series`
 - Regime (rules, flow‑based): `GET /api/v1/screener/regime-rules/latest`, `GET /api/v1/screener/regime-rules/series`
 - Breadth (legacy): `GET /api/v1/screener/breadth`
 - Breadth (flow): `GET /api/v1/screener/breadth/flow`

The Explore screener tab defaults to the new flow breadth and rules regime. Override via URL flags:
- `?breadth=legacy` to show the legacy breadth snapshot
- `?regime=intensity` to show the EMA/hysteresis intensity regime instead of the rules regime

## Authentication & Roles (optional)

- Google sign-in is still optional - anonymous users browse the same UI. When a user signs in, the header shows their primary role and server-side calls include a bearer token with that role set.
- The frontend issues JWT sessions via NextAuth and keeps the API in sync by calling `/api/v1/auth/sync`. Configure the following secrets (see `env/example/frontend.env.example`):

  ```env
  NEXTAUTH_URL=http://localhost:3000
  NEXTAUTH_SECRET= # openssl rand -hex 32 – must match the API's value
  GOOGLE_CLIENT_ID=
  GOOGLE_CLIENT_SECRET=
  AUTH_SERVICE_TOKEN= # shared with the API; accepted by admin/operator routes (recommended)
  AUTH_ROLE_REFRESH_INTERVAL_MS=300000 # optional, defaults to 5 minutes
  ```

- After sign-in, the JWT contains `roles` and `userId`; the React Query hooks stay unchanged because public data queries still succeed without tokens.
- Admin endpoints (refresh, cache warmers, etc.) accept `AUTH_SERVICE_TOKEN`. A signed-in user with the `admin` role can access them without a static token when the frontend forwards a session JWT (future enhancement); today the admin UI uses the service token for server-side calls.
- Rolling out roles:
  1. Run migration `V84__auth_role_based_access.sql` and assign roles via `/api/v1/auth/users` or SQL.
  2. Deploy matching `NEXTAUTH_SECRET` and `AUTH_SERVICE_TOKEN` values to both API and frontend.
  3. (Optional) Gate UI sections with the helpers in `@/lib/roles`.

### Code Quality Checks
```bash
# Type checking
pnpm type-check

# Linting
pnpm lint
```

## Environment Configuration

### Required Variables
```env
NEXT_PUBLIC_API_URL=http://localhost:6080
INTERNAL_API_URL=http://api:6080 # used when running inside Docker
PORT=3000                         # override when the container should listen on a different port
```

The frontend proxies requests through its own `/api/*` routes, so browser calls
always go back to the same origin/port that served the UI. `INTERNAL_API_URL`
lets the server runtime reach the FastAPI container when you run under Docker
Compose.

When running via Docker Compose, set `FRONTEND_PORT` in `.compose.env` to choose
both the host and container port. The compose file forwards that value to the
frontend service as `PORT`, keeping health checks and inter-service calls in
sync.

### Optional Variables
```env
NEXT_PUBLIC_WS_URL=ws://localhost:6080
NEXT_PUBLIC_ENABLE_DEVTOOLS=true
```

### Contact Form & Email

Recommended: send email via the backend API. The FastAPI service exposes `POST /api/v1/ops/email`, which uses a shared SMTP/Gmail client and centralized secrets. The UI calls this endpoint when `BACKEND_EMAIL=true` and authenticates with `AUTH_SERVICE_TOKEN`; no SMTP secrets are needed in the frontend.

If you prefer to keep the existing frontend-only flow, the built-in contact route still supports Resend or SMTP. Copy `apps/frontend/.env.local.example` to `.env.local` and set values as needed.

```env
# Resend (preferred)
RESEND_API_KEY=
RESEND_FROM=RankAlpha <no-reply@example.com>
RESEND_TO=info@example.com

# Optional overrides (take precedence over RESEND_*)
#CONTACT_FROM=RankAlpha <no-reply@example.com>
#CONTACT_TO=info@example.com

# SMTP fallback (frontend-local)
#SMTP_HOST=
#SMTP_PORT=587
#SMTP_USER=
#SMTP_PASS=
#SMTP_SECURE=false
#SMTP_DEBUG=false  # verbose SMTP logs for troubleshooting

# Cloudflare Turnstile (anti-bot)
#NEXT_PUBLIC_TURNSTILE_SITE_KEY=
#TURNSTILE_SECRET_KEY=
```

## Performance Features

### Data Refresh System
- **Automatic Polling**: Checks `/api/refresh-data` every minute
- **Smart Cache Invalidation**: Only refetches changed data
- **User Notifications**: Toast messages for new data
- **Manual Override**: Force refresh button for immediate updates

Security for refresh endpoint:
- `/api/refresh-data` accepts `POST` only and requires a bearer token via `FRONTEND_REFRESH_TOKEN`.
- Airflow uses this token via the `Authorization: Bearer ${FRONTEND_REFRESH_TOKEN}` header (see DAG).

```env
# Frontend refresh (protects /api/refresh-data)
FRONTEND_REFRESH_TOKEN=change-me-long-random
```

### Optimization Strategies
- **Code Splitting**: Dynamic imports reduce initial bundle
- **Image Optimization**: Next.js Image component with lazy loading
- **React Query Cache**: Intelligent caching with background refetch
- **Bundle Analysis**: Regular monitoring of JavaScript bundle size

## Security Considerations

- **Content Security Policy**: Strict CSP headers
- **XSS Protection**: React's automatic escaping
- **HTTPS Enforcement**: SSL/TLS in production
- **Input Sanitization**: Validation on all user inputs
- **Secure Authentication**: JWT tokens with refresh mechanism
- **Admin route telemetry**: `/admin*` page gates and frontend `/api/admin/*` handlers (including unknown `/api/admin/*` probes) emit async security events (`frontend_admin_access`) for bot/scrape monitoring in Loki/Grafana.

### Frontend Admin Telemetry Knobs

```env
# Async admin-access security telemetry (stdout -> Loki)
FRONTEND_ADMIN_SECURITY_LOG_ENABLED=true
FRONTEND_ADMIN_SECURITY_LOG_AUTHORIZED=false
FRONTEND_ADMIN_SECURITY_LOG_QUEUE_MAX=5000
FRONTEND_ADMIN_SECURITY_LOG_BATCH_SIZE=200
FRONTEND_ADMIN_SECURITY_LOG_FLUSH_MS=1000
FRONTEND_ADMIN_SECURITY_LOG_INCLUDE_USER_AGENT=false
```

## Browser Support

- Chrome/Edge (latest 2 versions)
- Firefox (latest 2 versions)
- Safari (latest 2 versions)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Future Enhancements

### Planned Features
- WebSocket integration for real-time updates
- Advanced charting with drawing tools
- Portfolio management interface
- Mobile app using React Native
- Offline support with service workers
- Multi-language internationalization
- Advanced data export with templates
- Collaborative analysis features

## Troubleshooting

### Common Issues

1. **API Connection Failed**
   - Verify API is running on port 6080
   - Check NEXT_PUBLIC_API_URL in environment
   - Ensure CORS is configured on backend

2. **Type Generation Error**
   - Confirm API is accessible
   - Check OpenAPI endpoint (/openapi.json)
   - Verify network connectivity

3. **Build Failures**
   - Clear .next directory
   - Run `pnpm type-check` to find issues
   - Check all dependencies are installed

## Contributing

### Development Standards
- Use functional components with TypeScript
- Follow existing component patterns
- Add unit tests for new features
- Update types when API changes
- Document complex logic with comments
- Ensure accessibility compliance
