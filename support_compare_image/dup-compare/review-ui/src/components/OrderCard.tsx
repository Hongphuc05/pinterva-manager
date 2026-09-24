import { Loader2, Maximize2 } from 'lucide-react'
import { isDone, isSent, isTodo, type Item } from '../types'
import { StatusBadge } from './StatusBadge'
import { CandidateCard } from './CandidateCard'
import { Figure } from './Figure'

interface Props {
  item: Item
  active: boolean
  busy: boolean
  onSelect: (itemId: string, candidateId: string) => void
  onReject: (itemId: string) => void
  onZoom: (src: string) => void
  onFocus: () => void
  onDetail: (itemId: string) => void
}

export function OrderCard({ item, active, busy, onSelect, onReject, onZoom, onFocus, onDetail }: Props) {
  const canAct = !isSent(item) && (isTodo(item) || isDone(item))
  return (
    <article
      data-testid={`order-${item.order_code}`}
      onMouseDown={onFocus}
      className={`mb-3 rounded-lg border bg-surface ${active ? 'border-brand/60' : 'border-line'}`}
    >
      <div className="flex items-center gap-2.5 border-b border-line px-3 py-2">
        <span className="font-mono text-[13px] font-medium text-brand">{item.order_code}</span>
        <span className="min-w-0 flex-1 truncate text-dim" title={item.product_name ?? ''}>{item.product_name}</span>
        <StatusBadge status={item.review_status} />
        {item.candidates.length > 0 && (
          <button
            type="button"
            title="So sánh ảnh gốc với từng ảnh trong top (phím D)"
            onClick={() => onDetail(item.id)}
            className="inline-flex h-6 cursor-pointer items-center gap-1 rounded border border-line bg-raised px-2 text-[11px] font-medium transition hover:border-brand/60 hover:text-brand"
          >
            <Maximize2 className="size-3" />
            Chi tiết
          </button>
        )}
        {canAct && (
          <button
            type="button"
            disabled={busy}
            title="Model đoán sai: đơn nằm cùng nhóm không thấy trùng cho tới khi gõ /handle (phím X)"
            onClick={() => onReject(item.id)}
            className="inline-flex h-6 cursor-pointer items-center gap-1 rounded border border-line bg-raised px-2 text-[11px] font-medium text-bad transition hover:border-bad/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy && <Loader2 className="size-3 animate-spin" />}
            Model sai
          </button>
        )}
      </div>

      <div className="flex gap-3 p-3">
        <Figure imageUrl={item.image_url} code={item.order_code} onZoom={onZoom} tag={<span className="rounded bg-brand px-1 text-[11px] font-medium text-white">Gốc</span>} />
        <div className="w-px flex-none bg-line" />
        <div className="flex min-w-0 flex-1 gap-3 overflow-x-auto pb-1">
          {item.candidates.length ? (
            item.candidates.map((c) => (
              <CandidateCard key={c.id} item={item} candidate={c} canAct={canAct} busy={busy} onSelect={onSelect} onZoom={onZoom} />
            ))
          ) : (
            <div className="py-6 text-dim">Không có candidate</div>
          )}
        </div>
      </div>
    </article>
  )
}
