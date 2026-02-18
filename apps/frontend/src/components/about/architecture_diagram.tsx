'use client'

import Image from 'next/image'
import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Download, ExternalLink, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'

type ArchitectureDiagramProps = {
  title?: string
  srcSvg?: string
  srcPng?: string
}

export function ArchitectureDiagram({
  title = 'Architecture diagram',
  srcSvg = '/images/rankalpha_infographic.svg',
  srcPng = '/images/rankalpha_infographic.png',
}: ArchitectureDiagramProps) {
  const [scale, setScale] = useState(1)

  const canZoomOut = scale > 0.5
  const canZoomIn = scale < 2.0

  const percentLabel = useMemo(() => `${Math.round(scale * 100)}%`, [scale])

  const openSvg = () => {
    window.open(srcSvg, '_blank', 'noopener,noreferrer')
  }

  const triggerDownload = (href: string) => {
    const a = document.createElement('a')
    a.href = href
    a.download = href.split('/').pop() || 'download'
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  return (
    <div className="space-y-ds-3">
      <div className="flex flex-wrap items-center justify-between gap-ds-2">
        <div className="text-ds-xs text-muted-foreground">Zoom: {percentLabel}</div>
        <div className="flex flex-wrap items-center gap-ds-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setScale((v) => Math.max(0.5, Number((v - 0.1).toFixed(2))))}
            disabled={!canZoomOut}
          >
            <ZoomOut className="mr-2 h-4 w-4" />
            Zoom out
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setScale((v) => Math.min(2.0, Number((v + 0.1).toFixed(2))))}
            disabled={!canZoomIn}
          >
            <ZoomIn className="mr-2 h-4 w-4" />
            Zoom in
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={() => setScale(1)}>
            <Maximize2 className="mr-2 h-4 w-4" />
            Fit
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={openSvg}>
            <ExternalLink className="mr-2 h-4 w-4" />
            Open
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={() => triggerDownload(srcSvg)}>
            <Download className="mr-2 h-4 w-4" />
            Download SVG
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={() => triggerDownload(srcPng)}>
            <Download className="mr-2 h-4 w-4" />
            Download PNG
          </Button>
        </div>
      </div>

      <div className="overflow-auto rounded-lg border border-border/60 bg-background/70 p-ds-2">
        <div
          className="origin-top-left"
          style={{ transform: `scale(${scale})` }}
        >
          <Image
            src={srcSvg}
            alt={title}
            className="h-auto w-full max-w-none select-none"
            width={1600}
            height={900}
            sizes="100vw"
            unoptimized
            draggable={false}
          />
        </div>
      </div>
    </div>
  )
}
