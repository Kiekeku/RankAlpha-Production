import type { TableHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

export function DataTable({ className, ...props }: TableHTMLAttributes<HTMLTableElement>) {
  return <table className={cn('data-table w-full text-sm', className)} {...props} />
}
