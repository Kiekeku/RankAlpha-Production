# UI primitives

Use the primitives in this folder to keep interaction and styling consistent across pages. If you need a new pattern, add it here first and then reuse it. Utility class merging should use `cn` from `apps/frontend/src/lib/utils.ts` (no duplicate helpers).

Core components
- `button.tsx`: primary/secondary/outline/ghost variants.
- `icon-button.tsx`: icon-only button with square sizing presets (`size="sm"` or default 44px hit target).
- `card.tsx`: card shell used across pages.
- `dialog.tsx`: modal with consistent overlay, padding, and close behavior.
- `tooltip.tsx`: tooltip wrapper with shared styling.
- `toast.tsx` + `use-toast.ts`: toasts and actions.
- `skeleton.tsx`: loading placeholders.
- `tab-nav.tsx`: shared tab navigation and active-state pills.
- `data-table.tsx`: base table element with consistent typography.

Guidelines
- Prefer `TabNav`/`TabLink` for any page-level tabs or sticky section tabs.
- Use `IconButton` for icon-only actions; pass `label` for accessibility.
- Keep tables wrapped in `DataTable` so typography stays aligned.
- For new patterns, add a small primitive here and replace ad‑hoc styling in pages.
