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
    <div className="w-[188px] flex-none">
      {src ? (
        <button
          type="button"
          title="Bấm để phóng to"
          onClick={() => onZoom(src)}
          className={`relative block size-[188px] cursor-zoom-in overflow-hidden rounded-xl border bg-tertiary p-0 ${
            chosen ? 'border-accent ring-[3px] ring-accent/25' : 'border-border'
          }`}
        >
          <img src={src} alt={code} loading="lazy" className="size-full object-contain" />
          {tag && <span className="absolute left-2 top-2">{tag}</span>}
        </button>
      ) : (
        <div className="grid size-[188px] place-items-center rounded-xl border border-border bg-tertiary text-xs text-muted-foreground">
          Không có ảnh
        </div>
      )}
      <div className="mt-2 flex flex-col gap-1 text-xs">
        <span className="self-start rounded-md border border-border bg-white px-2 py-0.5 font-mono text-[13px] font-medium text-primary">
          {code}
        </span>
        {name && <div className="truncate text-muted-foreground" title={name}>{name}</div>}
        {children}
      </div>
    </div>
  )
}
