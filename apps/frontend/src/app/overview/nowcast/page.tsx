import { RegimeSummary } from '@/features/regime'
import { HeadlinesStrip } from '@/components/overview/headlines_strip'
import { EarningsStrip } from '@/components/overview/earnings_strip'
import { OverviewNowcastPrefetch } from '@/components/home-overview-prefetch'

export default function OverviewNowcastPage() {
  return (
    <OverviewNowcastPrefetch>
      <section className="space-y-4">
        <HeadlinesStrip />
        <EarningsStrip />
        <RegimeSummary />
      </section>
    </OverviewNowcastPrefetch>
  )
}
