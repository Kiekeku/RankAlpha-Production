import { RegimePanel } from '@/features/regime'
import { OverviewRegimePrefetch } from '@/components/home-overview-prefetch'

export default function OverviewRegimePage() {
  return (
    <OverviewRegimePrefetch>
      <RegimePanel />
    </OverviewRegimePrefetch>
  )
}
