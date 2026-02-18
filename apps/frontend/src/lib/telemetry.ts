export type TelemetryEvent = {
  event: string
  [key: string]: unknown
}

export function emitTelemetry(event: TelemetryEvent): void {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent('rankalpha:telemetry', { detail: event }))
  } catch {
    // no-op
  }

  try {
    const dataLayer = (window as typeof window & { dataLayer?: Array<Record<string, unknown>> }).dataLayer
    if (Array.isArray(dataLayer)) {
      dataLayer.push({ ...event, event: 'rankalpha.telemetry' })
    }
  } catch {
    // no-op
  }
}
