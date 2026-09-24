import { Loader2, X } from 'lucide-react'
import { isDone, isSent, isTodo, type Item } from '../types'
import { Badge } from './StatusBadge'
import { StatusBadge } from './StatusBadge'
import { CandidateCard } from './CandidateCard'
import { Figure } from './Figure'

interface Props {
  item: Item
  busy: boolean
  onSelect: (itemId: string, candidateId: string) => void
  onReject: (itemId: string) => void
  onZoom: (src: string) => void
}

export function OrderCard({ item, busy, onSelect, onReject, onZoom }: Props) {
  const canAct = !isSent(item) && (isTodo(item) || isDone(item))
  return (
    <article
      data-testid={`order-${item.order_code}`}
      className="mb-4 overflow-hidden rounded-xl border border-border bg-card shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-border/70 bg-muted/50 px-5 py-3">
        <span className="rounded-md border border-border bg-white px-2 py-0.5 font-mono text-[13px] font-medium text-primary">
          {item.order_code}
        </span>
        <span className="min-w-40 flex-1 text-[13px] text-muted-foreground">{item.product_name}</span>
        <StatusBadge status={item.review_status} />
      </div>

      <div className="flex flex-col gap-5 p-5 md:flex-row md:items-start">
        <Figure
          imageUrl={item.image_url}
          code={item.order_code}
          onZoom={onZoom}
          tag={<Badge tone="info">Ảnh gốc</Badge>}
        />
        <div className="hidden w-px self-stretch bg-border md:block" />
        <div className="flex min-w-0 flex-1 gap-3.5 overflow-x-auto pb-1">
          {item.candidates.length ? (
            item.candidates.map((c) => (
              <CandidateCard
                key={c.id}
                item={item}
                candidate={c}
                canAct={canAct}
                busy={busy}
                onSelect={onSelect}
                onZoom={onZoom}
              />
            ))
          ) : (
            <div className="py-6 text-sm text-muted-foreground">Không có candidate</div>
          )}
        </div>
      </div>

      {canAct && (
        <div className="flex items-center justify-end gap-2.5 border-t border-border/70 px-5 py-3">
          <span className="mr-auto text-xs text-muted-foreground">
            Model đoán sai? Đơn {item.order_code} sẽ nằm cùng nhóm "không thấy trùng" cho tới khi bạn gõ /handle.
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => onReject(item.id)}
            className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-destructive/50 bg-white px-3 text-xs font-semibold text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : <X className="size-3.5" />}
            Model sai
          </button>
        </div>
      )}
    </article>
  )
}
