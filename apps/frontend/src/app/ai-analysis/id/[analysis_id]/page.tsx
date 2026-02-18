import { notFound, permanentRedirect } from 'next/navigation'
import { buildUpstreamUrl } from '@/app/api/_utils/upstream'
import { AiAnalysisItem } from '@/lib/api'

export const revalidate = 86400

export default async function AnalysisDetailPage({ params }: { params: { analysis_id: string } }) {
  const analysisId = (params.analysis_id || '').trim()
  if (!analysisId) notFound()

  const target = buildUpstreamUrl(`/api/v1/ai-analysis/id/${encodeURIComponent(analysisId)}`)
  const res = await fetch(target, {
    next: { revalidate, tags: ['ai-analysis', analysisId] },
  })

  if (!res.ok) notFound()
  const data = (await res.json()) as AiAnalysisItem

  const symbol = (data?.symbol || '').trim().toUpperCase()
  if (!symbol) notFound()

  permanentRedirect(`/ai-analysis/${encodeURIComponent(symbol)}?analysis_id=${encodeURIComponent(analysisId)}`)
}
