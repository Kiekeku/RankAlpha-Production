'use client'

export const COMPARE_TRAY_OPEN_EVENT = 'rankalpha:compare-tray-open'

export function openCompareTray() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(COMPARE_TRAY_OPEN_EVENT))
}
