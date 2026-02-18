# RankAlpha Frontend Design System (Dashboards)

This app is Tailwind-first and component-driven. The goal of the design system is to keep the dashboard UI consistent as the surface area grows, without turning styling into a “framework within a framework”.

## Tokens

### Spacing scale (use these increments)

Use Tailwind spacing utilities that map to the canonical scale:

- 4px = `*-ds-1`
- 8px = `*-ds-2`
- 12px = `*-ds-3`
- 16px = `*-ds-4`
- 20px = `*-ds-5`
- 24px = `*-ds-6`
- 32px = `*-ds-7`
- 40px = `*-ds-8`
- 48px = `*-ds-9`
- 64px = `*-ds-10`

Examples: `p-ds-4`, `gap-ds-3`, `mt-ds-2`.

### Type scale

Use:

- 12px = `text-ds-xs`
- 14px = `text-ds-sm`
- 16px = `text-ds-md`
- 20px = `text-ds-lg`
- 28px = `text-ds-xl`

### Status tokens (semantic colors)

Use these status tokens for pills, callouts, and stateful UI:

- `status.success`
- `status.danger`
- `status.warning`
- `status.info`
- `status.model`

Tailwind helpers:

- Text: `text-status-<token>` or `text-status-<token>-foreground`
- Border: `border-status-<token>/…`
- Background: `bg-status-<token>/…`

## Components

Core dashboard building blocks live under `src/components/dashboard/*`:

- `MetricCard`
- `ChartCard`
- `ListCard`
- `InfoTooltip` (icon trigger + hover/click + rich content)
- `StatusBadge`

