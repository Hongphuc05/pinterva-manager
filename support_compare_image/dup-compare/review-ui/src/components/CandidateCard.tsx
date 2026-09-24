import { Loader2, Send } from 'lucide-react'
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
      tag={<Badge tone="muted">#{c.rank}</Badge>}
    >
      <div className="flex justify-between">
        <span className="text-muted-foreground">Độ giống</span>
        <b className="font-mono">{c.similarity.toFixed(3)}</b>
      </div>
      <div className="flex justify-between">
        <span className="text-muted-foreground">pHash / SSIM</span>
        <span className="font-mono">
          {c.phash_distance ?? '-'} / {c.ssim == null ? '-' : c.ssim.toFixed(2)}
        </span>
      </div>
      <div>
        {c.classification === 'TRUNG' ? (
          <Badge tone="pending">Model: TRÙNG</Badge>
        ) : (
          <Badge tone="muted">Model: khác</Badge>
        )}
      </div>
      {chosen && (
        <div>
          <Badge tone="success">
            <Send className="size-3" />
            {c.sent_to_telegram ? 'Đã gửi Telegram' : 'Chờ gửi Telegram (≤60s)'}
          </Badge>
        </div>
      )}
      {canAct && !c.sent_to_telegram && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onSelect(item.id, c.id)}
          className="mt-1.5 inline-flex h-8 w-full cursor-pointer items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy && <Loader2 className="size-3.5 animate-spin" />}
          Chọn ảnh này là trùng
        </button>
      )}
    </Figure>
  )
}
