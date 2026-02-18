type FlashNoticeStatus = 'success' | 'error'

export function FlashNotice({ status, message }: { status: FlashNoticeStatus; message: string }) {
  if (!message) return null

  return (
    <div
      className={
        status === 'success'
          ? 'rounded-md border border-status-success/30 bg-status-success/10 p-3 text-sm text-status-success-foreground'
          : 'rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive'
      }
    >
      {message}
    </div>
  )
}
