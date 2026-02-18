import { Suspense } from 'react'

import { ComparePageView } from '@/features/compare/compare-page-view'

export default function ComparePage() {
  return (
    <Suspense fallback={null}>
      <ComparePageView />
    </Suspense>
  )
}

