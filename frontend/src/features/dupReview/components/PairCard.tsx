import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Item } from '../types'
import { Figure } from './Figure'
import { StatusBadge } from './StatusBadge'

interface Props {
  item: Item
  onZoom: (src: string) => void
  /** Offered while the choice can still change: moves the order back to "Không trùng lặp" to pick again. */
  onReject?: (itemId: string) => void
  busy?: boolean
  children?: ReactNode
}

/** The compact view of a decided order: its original image next to the image picked as the duplicate. */
export function PairCard({ item, onZoom, onReject, busy, children }: Props) {
  const picked = item.candidates.find((c) => c.id === item.selected_candidate_id)
  return (
    <article data-testid={`order-${item.order_code}`} className="mb-3 rounded-lg border border-dup-line bg-dup-surface p-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="font-mono text-[13px] font-medium text-dup-brand">{item.order_code}</span>
        <span className="min-w-0 flex-1 truncate text-dup-dim" title={item.product_name ?? ''}>{item.product_name}</span>
        <StatusBadge item={item} />
        {onReject && (
          <button
            type="button"
            disabled={busy}
            title="Chọn sai: đưa đơn về tab Không trùng lặp để chọn lại"
            onClick={() => onReject(item.id)}
            className="inline-flex h-6 cursor-pointer items-center gap-1 rounded border border-dup-line bg-dup-raised px-2 text-[11px] font-medium text-dup-bad transition hover:border-dup-bad/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy && <Loader2 className="size-3 animate-spin" />}
            Model sai
          </button>
        )}
      </div>
      <div className="mt-3 flex gap-4">
        <Figure
          imageUrl={item.image_url}
          code={item.order_code}
          onZoom={onZoom}
          tag={<span className="rounded bg-dup-brand px-1 text-[11px] font-medium text-white">Gốc</span>}
        />
        {picked && (
          <Figure
            imageUrl={picked.image_url}
            code={picked.order_code || 'không rõ'}
            name={picked.product_name}
            chosen
            onZoom={onZoom}
            tag={<span className="rounded bg-dup-ok px-1 text-[11px] font-medium text-white">Trùng</span>}
          >
            <span className="font-mono text-[11px] text-dup-dim">{picked.similarity.toFixed(3)}</span>
          </Figure>
        )}
      </div>
      {children}
    </article>
  )
}
