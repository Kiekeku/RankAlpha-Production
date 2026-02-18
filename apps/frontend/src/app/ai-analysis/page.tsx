import { Suspense } from 'react'

import AiAnalysisPage from '@/features/ai-analysis/ai-analysis-view'

export default function AiAnalysisRoutePage() {
  return (
    <Suspense fallback={null}>
      <AiAnalysisPage />
    </Suspense>
  )
}
