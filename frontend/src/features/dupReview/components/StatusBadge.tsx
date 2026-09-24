import type { ReactNode } from 'react'
import type { ReviewStatus } from '../types'

const base = 'inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-px text-[11px] font-medium'

export const tones = {
  ok: 'bg-dup-ok/15 text-dup-ok',
  warn: 'bg-dup-warn/15 text-dup-warn',
  bad: 'bg-dup-bad/15 text-dup-bad',
  info: 'bg-dup-brand/15 text-dup-brand',
  dim: 'bg-white/8 text-dup-dim',
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
