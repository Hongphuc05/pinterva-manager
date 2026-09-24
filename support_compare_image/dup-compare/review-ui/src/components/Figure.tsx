import type { ReactNode } from 'react'

const safeUrl = (u: string) => (/^https?:\/\//i.test(u) ? u : '')

interface FigureProps {
  imageUrl: string
  code: string
  name?: string | null
  tag?: ReactNode
  chosen?: boolean
  onZoom: (src: string) => void
  children?: ReactNode
}

/** An image with its order code underneath. Every image in the tool carries a code. */
export function Figure({ imageUrl, code, name, tag, chosen, onZoom, children }: FigureProps) {
  const src = safeUrl(imageUrl)
  return (
    <div className="w-36 flex-none">
      {src ? (
        <button
          type="button"
          title="Bấm để phóng to"
          onClick={() => onZoom(src)}
          className={`relative block size-36 cursor-zoom-in overflow-hidden rounded-md border bg-white p-0 ${
            chosen ? 'border-ok ring-2 ring-ok/40' : 'border-line'
          }`}
        >
          <img src={src} alt={code} loading="lazy" className="size-full object-contain" />
          {tag && <span className="absolute left-1 top-1">{tag}</span>}
        </button>
      ) : (
        <div className="grid size-36 place-items-center rounded-md border border-line bg-surface text-dim">Không có ảnh</div>
      )}
      <div className="mt-1.5 flex flex-col gap-0.5 text-xs">
        <span className="font-mono text-[12px] font-medium text-brand">{code}</span>
        {name && <div className="truncate text-dim" title={name}>{name}</div>}
        {children}
      </div>
    </div>
  )
}
