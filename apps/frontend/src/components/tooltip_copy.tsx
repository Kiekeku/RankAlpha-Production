'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'

import { InfoTooltipButton } from '@/components/info_tooltip_button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { get_tooltip_copy, type TooltipKey } from '@/lib/tooltip_copy'

export function TooltipCopyContent({
  tooltipKey,
  className,
}: {
  tooltipKey: TooltipKey
  className?: string
}) {
  const copy = get_tooltip_copy(tooltipKey)
  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="text-xs font-semibold text-foreground">{copy.title}</div>
      <div className="text-xs leading-relaxed text-muted-foreground">{copy.body}</div>
      {copy.learnMorePath ? (
        <div className="pt-1">
          <Link href={copy.learnMorePath} className="text-xs font-semibold text-primary hover:underline">
            Learn more
          </Link>
        </div>
      ) : null}
    </div>
  )
}

export function TooltipCopyButton({
  tooltipKey,
  label,
  iconSize = 'h-3.5 w-3.5',
  buttonClassName,
}: {
  tooltipKey: TooltipKey
  label?: string
  iconSize?: string
  buttonClassName?: string
}) {
  const router = useRouter()
  const copy = get_tooltip_copy(tooltipKey)
  const learnMorePath = copy.learnMorePath
  return (
    <InfoTooltipButton
      label={label ?? copy.title}
      iconSize={iconSize}
      buttonClassName={buttonClassName}
      contentClassName="max-w-sm px-3 py-2"
      description={<TooltipCopyContent tooltipKey={tooltipKey} />}
      learnMore={
        learnMorePath
          ? {
              onClick: () => router.push(learnMorePath),
            }
          : undefined
      }
    />
  )
}

export function TooltipCopy({
  tooltipKey,
  children,
  contentClassName = 'max-w-sm px-3 py-2',
}: {
  tooltipKey: TooltipKey
  children: React.ReactElement
  contentClassName?: string
}) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent className={contentClassName}>
          <TooltipCopyContent tooltipKey={tooltipKey} />
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
