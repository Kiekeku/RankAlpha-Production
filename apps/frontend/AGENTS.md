<INSTRUCTIONS>
# Frontend (Next.js) Agent Guidelines

This directory (`apps/frontend`) is a Next.js 14 App Router project (TypeScript + Tailwind + shadcn/ui + React Query).

## Reuse-first rule (formatting + utilities)
Before adding *any* new helper for formatting or “small math”, search and reuse existing utilities:
- `src/lib/format.ts` (numbers, percents, currency, signed deltas)
- `src/lib/date.ts` (date formatting)
- `src/lib/time.ts` (time constants)
- `src/lib/nowcast-utils.ts` (nowcast math helpers: deltas, mean/std, etc.)
- `src/lib/utils.ts` (shared UI helpers like `cn`)
- `src/features/stock-detail/stock_detail_format.ts` (stock-detail-specific formatting)

If you still need a new helper:
- Put it in the *most central* appropriate module above (don’t create a new “utils2” file).
- Keep helpers pure and unit-consistent (document whether inputs are 0–1 fractions vs 0–100 percents).

## App Router + data fetching conventions
- Prefer **Server Components** by default; add `'use client'` only when needed (hooks, local state, event handlers).
- Client-side data fetching uses **React Query** (`@tanstack/react-query`).
  - Use stable, deterministic `queryKey`s and reuse existing keys when possible.
  - Avoid accidental key collisions (same key but different params).
- The browser should call the frontend proxy routes under `src/app/api/**` (paths like `/api/...`).
  - These routes proxy to the upstream API and apply `revalidate` + `tags`.
  - Don’t add `cache: 'no-store'` unless freshness truly requires it; prefer `revalidate` + SWR caching.

## API client usage
- Use `src/lib/api/index.ts` (`api.*`) for client calls.
- On the server, the API client is configured to hit the upstream (`INTERNAL_API_URL` / `NEXT_PUBLIC_API_URL`) with `/api/v1`.
- In the browser, the API client uses `/api/*` routes (frontend proxy).

## UI & styling conventions
- Use existing shared UI components first:
  - shadcn components in `src/components/ui/*`
  - shared components like `src/components/page-hero.tsx`, `src/components/route-modal.tsx`
- Styling is Tailwind-first; keep class strings readable and consistent with nearby code.
- Use `cn(...)` (`src/lib/utils.ts`) for conditional classes.
- Accessibility: keep `sr-only` labels for icon-only buttons; ensure focus rings remain visible.

## Design system conventions (dark UI)

### Design tokens (avoid UI drift)
- Prefer the design-system token classes over ad-hoc spacing/type choices:
  - Spacing scale: `*-ds-1..ds-10` (4px..64px). Examples: `p-ds-4`, `gap-ds-3`, `mt-ds-2`.
  - Type scale: `text-ds-xs|ds-sm|ds-md|ds-lg|ds-xl` (12/14/16/20/28).
- Prefer semantic status tokens (do not hardcode Tailwind hues like `bg-emerald-*`, `text-amber-*` for meaning):
  - Tokens: `status.success|danger|warning|info|model` (via Tailwind classes like `bg-status-warning/10`, `text-status-info-foreground`).
  - Badges: use `Badge` variants (`success|danger|warning|info|model`) and avoid custom per-callsite color strings.

### Surfaces and elevation (avoid gradient canvas)
- Canvas should be flat: rely on `bg-background` on `body` (no global gradients or grids).
- Use elevation levels through surface contrast, not thicker borders:
  - Level 0 (Canvas): `bg-background`
  - Level 1 (Containers / panels): `Card` with default styles, optionally `className="border-outline/8"`
  - Level 2 (Nested cards / rows): prefer `bg-secondary/15` or `bg-secondary/20` with a subtle border
  - Level 3 (Chips): use `Badge` (pill), not mini-cards

### Borders (thin, opacity-based)
- Default: `border-outline/8` to `border-outline/10`
- Hover for interactive cards/rows: `hover:border-outline/16` or a subtle brand tint like `hover:border-primary/20`
- Selected/active states: `border-outline/22` to `border-outline/28` (optional tiny glow if needed, keep it restrained)
- Parent containers should have weaker borders than their child rows.

### Card usage
- Prefer `Card` (`src/components/ui/card.tsx`) instead of hand-rolling border + background.
- For interactive rows (Rankings, AI list rows, tables-as-cards):
  - Default: subtle border + slightly elevated surface
  - Hover: add a small lift and stronger border (do not increase border thickness)

### Status pills / badges (canonical semantic system)
- Use `Badge` (`src/components/ui/badge.tsx`) for all status pills, with standardized variants:
  - `success` = risk-on / constructive
  - `danger` = risk-off / deteriorating
  - `warning` = caution / transition
  - `info` = informational / baseline
  - `model` = model/AI/sentiment only (keep it special)
- Avoid ad-hoc badge class strings (e.g., `border-emerald-* bg-emerald-* ...`) unless you are extending the canonical variants.

### Dashboard component primitives (standardize layouts)
- Prefer the dashboard card wrappers in `src/components/dashboard/*` for dashboard-style panels:
  - `MetricCard`, `ChartCard`, `ListCard` (shared header layout + tokenized spacing/type).
- Tooltip pattern: use `InfoTooltip` from `src/components/info_tooltip_button.tsx` (icon trigger + rich content).

### Charts (gridlines should not shout)
- Avoid hard-coded bright chart scaffolding (e.g., `#e5e7eb`) in dark mode.
- Prefer theme tokens for strokes and labels (e.g., `hsl(var(--border) / ...)`, `hsl(var(--outline) / ...)`, `hsl(var(--muted-foreground))`).
- Gridlines should be barely present (very low opacity), so the data line reads first.

## "As-of" date policy (avoid duplicated timestamps)
- The UI should display **one** primary “As of <date/time>” indicator in the global chrome (navbar/header).
- Do **not** add additional “As of …” timestamps inside Overview/Home cards (Nowcast, Macro tiles, etc.) unless there is a strong reason.
- Allowed exceptions (when a second timestamp is useful and non-redundant):
  - A detail page or drilldown where multiple panels have **different data as-of dates** and you’re explicitly calling it out.
  - A context section where the timestamp refers to a **different clock** than the global indicator (e.g., “Last pipeline run”, “Last cache purge”).
- When in doubt: remove per-card “As of …” text and rely on the global indicator; surface staleness via badges/coverage instead.

## Dash / punctuation policy (avoid em-dash)
- Do **not** use the em-dash character (U+2014) in UI copy, titles, or prose (it reads as AI-generated in this project).
- If you need a dash in prose, use a plain hyphen `-` with spaces (`foo - bar`) or rewrite using commas/parentheses.
- Missing-value placeholders should use `-` (not an em-dash).

## Modals & overlays
- Route-based modals use `src/components/route-modal.tsx` (Radix Dialog).
- If changing dialog close affordances, ensure it doesn’t overlap key content (use padding/gutters for affected headers).

## Validation commands (run from repo root)
- Typecheck: `pnpm -C apps/frontend type-check`
- Lint: `pnpm -C apps/frontend lint`

## Imports / paths
- Prefer `@/` absolute imports (configured in `tsconfig`).
- Keep file naming consistent with the existing area (some `snake_case.tsx` in `features/*`).
</INSTRUCTIONS>
