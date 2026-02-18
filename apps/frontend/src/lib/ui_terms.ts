export const UI_TERMS = {
  aiTargets: 'AI Targets',
  aiTarget: 'AI Target',
  aiTargetBase: 'AI Target (Base)',
  grade: 'Grade',
  setupHits: 'Setup hits',
} as const

export function formatSetupHitsLabel(days: number): string {
  return `Setup hits (${days}d)`
}

export function formatSetupTag(label: string, days: number): string {
  return `Setup: ${label} (${days}d)`
}
