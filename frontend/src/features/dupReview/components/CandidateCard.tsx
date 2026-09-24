import { Loader2 } from 'lucide-react'
import type { Candidate, Item } from '../types'
import { Badge } from './StatusBadge'
import { Figure } from './Figure'

interface Props {
  item: Item
  candidate: Candidate
  canAct: boolean
  busy: boolean
  onSelect: (itemId: string, candidateId: string) => void
  onZoom: (src: string) => void
}

export function CandidateCard({ item, candidate: c, canAct, busy, onSelect, onZoom }: Props) {
  const chosen = item.selected_candidate_id === c.id
  return (
    <Figure
      imageUrl={c.image_url}
      code={c.order_code || 'không rõ'}
      name={c.product_name}
      chosen={chosen}
      onZoom={onZoom}
      tag={<span className="rounded bg-black/70 px-1 font-mono text-[11px] text-white">{c.rank}</span>}
    >
      <div className="flex items-center justify-between font-mono text-[11px] text-dup-dim">
        <b className="text-[13px] font-semibold text-dup-fg">{c.similarity.toFixed(3)}</b>
        <span title="pHash / SSIM">
          {c.phash_distance ?? '-'} · {c.ssim == null ? '-' : c.ssim.toFixed(2)}
        </span>
      </div>
      <div className="flex min-h-[18px] flex-wrap gap-1">
        {c.classification === 'TRUNG' && <Badge tone="warn">Model: trùng</Badge>}
        {chosen && <Badge tone="ok">{c.sent_to_telegram ? 'Đã gửi Telegram' : 'Chờ gửi (≤60s)'}</Badge>}
      </div>
      {canAct && !c.sent_to_telegram && (
        <button
          type="button"
          disabled={busy}
          title={`Chọn ảnh này là trùng (phím ${c.rank})`}
          onClick={() => onSelect(item.id, c.id)}
          className="mt-1 inline-flex h-6 cursor-pointer items-center justify-center gap-1 rounded bg-dup-brand px-2 text-[11px] font-medium text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy && <Loader2 className="size-3 animate-spin" />}
          Chọn trùng
        </button>
      )}
    </Figure>
  )
}
