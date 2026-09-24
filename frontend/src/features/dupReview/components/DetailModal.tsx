import { useEffect } from 'react'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { isDone, isSent, isTodo, configEntries, type Item } from '../types'
import { Badge } from './StatusBadge'
import { ProxiedImg } from './ProxiedImg'

interface Props {
  item: Item
  index: number
  busy: boolean
  onIndex: (index: number) => void
  onClose: () => void
  onSelect: (itemId: string, candidateId: string) => void
}

function Pane({ title, code, name, src, overlay, children }: { title: string; code: string; name?: string | null; src: string; overlay?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <Badge tone="info">{title}</Badge>
        <span className="font-mono text-[13px] font-medium text-dup-brand">{code}</span>
        {name && <span className="min-w-0 flex-1 truncate text-dup-dim" title={name}>{name}</span>}
      </div>
      <div className="relative grid aspect-square w-full place-items-center overflow-hidden rounded-md border border-dup-line bg-white">
        {/^https?:\/\//i.test(src) ? (
          <ProxiedImg url={src} alt={code} className="size-full object-contain" />
        ) : (
          <span className="text-dup-dim">Không có ảnh</span>
        )}
        {overlay}
      </div>
      {children}
    </div>
  )
}

function ConfigList({ entries }: { entries: { key: string; value: string }[] }) {
  if (!entries.length) return <span className="text-[12px] text-dup-dim">Không có cấu hình</span>
  return (
    <ul className="space-y-0.5 text-[12px] text-dup-dim">
      {entries.slice(0, 6).map((e) => (
        <li key={e.key} className="truncate" title={`${e.key}: ${e.value}`}>
          <b className="font-medium text-dup-fg/80">{e.key}</b>: {e.value}
        </li>
      ))}
      {entries.length > 6 && <li>… +{entries.length - 6} mục</li>}
    </ul>
  )
}

/** Side-by-side view: the original on the left, one of the top candidates on the right, arrows to walk the list. */
export function DetailModal({ item, index, busy, onIndex, onClose, onSelect }: Props) {
  const total = item.candidates.length
  const candidate = item.candidates[index]
  const canAct = !isSent(item) && (isTodo(item) || isDone(item))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') onIndex(Math.min(index + 1, total - 1))
      else if (e.key === 'ArrowLeft') onIndex(Math.max(index - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, total, onIndex, onClose])

  if (!candidate) return null
  const entries = configEntries(candidate.custom_config)
  return (
    <div
      role="dialog"
      aria-label={`Chi tiết đơn ${item.order_code}`}
      className="fixed inset-0 z-[85] flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-full w-full max-w-5xl flex-col gap-3 overflow-y-auto rounded-lg border border-dup-line bg-dup-surface p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <b className="text-sm">Chi tiết đơn</b>
          <span className="font-mono text-[13px] text-dup-brand">{item.order_code}</span>
          <span className="text-dup-dim">
            Ảnh {index + 1}/{total} trong top {total}
          </span>
          <span className="ml-auto hidden text-[11px] text-dup-dim md:block">
            <kbd className="font-mono">←</kbd>/<kbd className="font-mono">→</kbd> chuyển ảnh · <kbd className="font-mono">Esc</kbd> đóng
          </span>
          <button
            type="button"
            aria-label="Đóng"
            onClick={onClose}
            className="grid size-7 cursor-pointer place-items-center rounded border border-dup-line bg-dup-raised text-dup-dim transition hover:text-dup-fg"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="flex flex-col gap-4 md:flex-row md:items-start">
          <Pane title="Ảnh gốc" code={item.order_code} name={item.product_name} src={item.image_url}>
            <ConfigList entries={configEntries(item.custom_config)} />
          </Pane>
          <Pane
            title={`#${candidate.rank}`}
            code={candidate.order_code || 'không rõ'}
            name={candidate.product_name}
            src={candidate.image_url}
            overlay={
              <>
                <button
                  type="button"
                  aria-label="Ảnh trước"
                  disabled={index === 0}
                  onClick={() => onIndex(index - 1)}
                  className="absolute left-2 top-1/2 grid size-9 -translate-y-1/2 cursor-pointer place-items-center rounded-full border border-dup-line bg-dup-bg/80 text-dup-fg backdrop-blur transition hover:text-dup-brand disabled:cursor-not-allowed disabled:opacity-30"
                >
                  <ChevronLeft className="size-5" />
                </button>
                <button
                  type="button"
                  aria-label="Ảnh sau"
                  disabled={index === total - 1}
                  onClick={() => onIndex(index + 1)}
                  className="absolute right-2 top-1/2 grid size-9 -translate-y-1/2 cursor-pointer place-items-center rounded-full border border-dup-line bg-dup-bg/80 text-dup-fg backdrop-blur transition hover:text-dup-brand disabled:cursor-not-allowed disabled:opacity-30"
                >
                  <ChevronRight className="size-5" />
                </button>
              </>
            }
          >
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[12px] text-dup-dim">
              <span>
                Độ giống <b className="text-[14px] text-dup-fg">{candidate.similarity.toFixed(3)}</b>
              </span>
              <span>pHash {candidate.phash_distance ?? '-'}</span>
              <span>SSIM {candidate.ssim == null ? '-' : candidate.ssim.toFixed(2)}</span>
              {candidate.classification === 'TRUNG' ? <Badge tone="warn">Model: trùng</Badge> : <Badge tone="dim">Model: khác</Badge>}
            </div>
            <ConfigList entries={entries} />
            {canAct && !candidate.sent_to_telegram && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onSelect(item.id, candidate.id)}
                className="inline-flex h-7 w-fit cursor-pointer items-center rounded bg-dup-brand px-3 text-xs font-medium text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Chọn ảnh này là trùng
              </button>
            )}
          </Pane>
        </div>

        <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Danh sách top ảnh">
          {item.candidates.map((c, i) => (
            <button
              key={c.id}
              type="button"
              aria-label={`Ảnh ${i + 1}`}
              aria-current={i === index}
              onClick={() => onIndex(i)}
              className={`relative size-14 flex-none cursor-pointer overflow-hidden rounded border bg-white p-0 ${
                i === index ? 'border-dup-brand ring-2 ring-dup-brand/40' : 'border-dup-line opacity-70 hover:opacity-100'
              }`}
            >
              <ProxiedImg url={c.image_url} alt="" className="size-full object-contain" />
              <span className="absolute left-0.5 top-0.5 rounded bg-black/70 px-1 font-mono text-[10px] text-white">{i + 1}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
