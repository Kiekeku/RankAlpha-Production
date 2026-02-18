import { MacroDashboard } from '@/features/macro'
import { OverviewMacroPrefetch } from '@/components/home-overview-prefetch'

export default function OverviewMacroPage() {
  return (
    <OverviewMacroPrefetch>
      <MacroDashboard />
    </OverviewMacroPrefetch>
  )
}
