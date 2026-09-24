import type { ReactNode } from 'react'
import { CheckCircle2, Clock, XCircle } from 'lucide-react'
import type { ReviewStatus } from '../types'

const base = 'inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-semibold'

export const tones = {
  success: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  pending: 'bg-amber-100 text-amber-800 border-amber-200',
  danger: 'bg-red-100 text-red-800 border-red-200',
  info: 'bg-blue-100 text-blue-800 border-blue-200',
  muted: 'bg-tertiary text-muted-foreground border-border',
} as const

export function Badge({ tone, children }: { tone: keyof typeof tones; children: ReactNode }) {
  return <span className={`${base} ${tones[tone]}`}>{children}</span>
}

export function StatusBadge({ status }: { status: ReviewStatus | null }) {
  if (status === 'ai_wrong')
    return <Badge tone="danger"><XCircle className="size-3" />Model sai</Badge>
  if (status === 'selected_duplicate')
    return <Badge tone="success"><CheckCircle2 className="size-3" />Đã chọn</Badge>
  if (status === 'no_match') return <Badge tone="info">Không thấy trùng</Badge>
  return <Badge tone="pending"><Clock className="size-3" />Chờ duyệt</Badge>
}
