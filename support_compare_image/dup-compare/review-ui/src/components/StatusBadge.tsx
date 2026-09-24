import type { ReactNode } from 'react'
import type { ReviewStatus } from '../types'

const base = 'inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-px text-[11px] font-medium'

export const tones = {
  ok: 'bg-ok/15 text-ok',
  warn: 'bg-warn/15 text-warn',
  bad: 'bg-bad/15 text-bad',
  info: 'bg-brand/15 text-brand',
  dim: 'bg-white/8 text-dim',
} as const

export function Badge({ tone, children }: { tone: keyof typeof tones; children: ReactNode }) {
  return <span className={`${base} ${tones[tone]}`}>{children}</span>
}

export function StatusBadge({ status }: { status: ReviewStatus | null }) {
  if (status === 'ai_wrong') return <Badge tone="bad">Model sai</Badge>
  if (status === 'selected_duplicate') return <Badge tone="ok">Đã chọn</Badge>
  if (status === 'no_match') return <Badge tone="info">Không thấy trùng</Badge>
  return <Badge tone="warn">Chờ duyệt</Badge>
}
