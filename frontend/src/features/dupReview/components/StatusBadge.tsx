import type { ReactNode } from 'react'
import type { Item } from '../types'

const base = 'inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-px text-[11px] font-medium'

export const tones = {
  ok: 'bg-dup-ok/15 text-dup-ok',
  warn: 'bg-dup-warn/15 text-dup-warn',
  bad: 'bg-dup-bad/15 text-dup-bad',
  info: 'bg-dup-brand/15 text-dup-brand',
  dim: 'bg-slate-100 text-dup-dim',
} as const

export function Badge({ tone, children }: { tone: keyof typeof tones; children: ReactNode }) {
  return <span className={`${base} ${tones[tone]}`}>{children}</span>
}

export function StatusBadge({ item }: { item: Item }) {
  switch (item.stage) {
    case 'unsent':
      return <Badge tone="warn">Chưa gửi</Badge>
    case 'waiting':
      return <Badge tone="info">Đang chờ</Badge>
    case 'verified':
      return <Badge tone="ok">Đã verify trùng</Badge>
    case 'linked':
      return <Badge tone="ok">Đã chuyển Trùng lặp</Badge>
    case 'not_duplicate':
      if (item.review_status === 'ai_wrong') return <Badge tone="bad">Model sai</Badge>
      if (item.review_status === 'no_match') return <Badge tone="info">Không thấy trùng</Badge>
      return <Badge tone="dim">Bị từ chối</Badge>
    default:
      return <Badge tone="warn">Chờ duyệt</Badge>
  }
}
