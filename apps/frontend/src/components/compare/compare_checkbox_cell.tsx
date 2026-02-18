import { CompareCheckbox } from '@/components/compare/compare_checkbox'
import { cn } from '@/lib/utils'

export function CompareCheckboxCell({
  symbol,
  className,
  cellClassName,
}: {
  symbol: string
  className?: string
  cellClassName?: string
}) {
  return (
    <td
      className={cn('w-10 px-3 py-2 align-middle', cellClassName)}
      onClick={(event) => {
        event.stopPropagation()
        const target = event.target as HTMLElement
        if (target.closest('input[type="checkbox"]')) return
        const cell = event.currentTarget as HTMLTableCellElement
        const checkbox = cell.querySelector<HTMLInputElement>('input[type="checkbox"]')
        if (checkbox && !checkbox.disabled) {
          checkbox.click()
        }
      }}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <CompareCheckbox symbol={symbol} className={className} />
    </td>
  )
}
