import { useState, type ReactNode } from 'react'

const safeUrl = (u: string) => (/^https?:\/\//i.test(u) ? u : '')
// Images go through the local server, which fetches them the way the worker does (no Referer).
export const proxied = (u: string) => `/review/img?url=${encodeURIComponent(u)}`

interface FigureProps {
  imageUrl: string
  code: string
  name?: string | null
  tag?: ReactNode
  chosen?: boolean
  onZoom: (src: string) => void
  /** The image is a local blob: URL (an upload), not something to fetch through the proxy. */
  rawSrc?: boolean
  children?: ReactNode
}

/** An image with its order code underneath. Every image in the tool carries a code. */
export function Figure({ imageUrl, code, name, tag, chosen, onZoom, rawSrc, children }: FigureProps) {
  const src = rawSrc ? imageUrl : safeUrl(imageUrl)
  const show = (u: string) => (rawSrc ? u : proxied(u))
  const [failed, setFailed] = useState(false)
  return (
    <div className="w-36 flex-none">
      {src && !failed ? (
        <button
          type="button"
          title="Bấm để phóng to"
          onClick={() => onZoom(show(src))}
          className={`relative block size-36 cursor-zoom-in overflow-hidden rounded-md border bg-white p-0 ${
            chosen ? 'border-ok ring-2 ring-ok/40' : 'border-line'
          }`}
        >
          <img
            src={show(src)}
            alt={code}
            loading="lazy"
            onError={() => setFailed(true)}
            className="size-full object-contain"
          />
          {tag && <span className="absolute left-1 top-1">{tag}</span>}
        </button>
      ) : (
        <div className="grid size-36 place-content-center gap-1 rounded-md border border-line bg-surface p-2 text-center text-dim">
          <span>{src ? 'Không tải được ảnh' : 'Không có ảnh'}</span>
          {src && (
            <a href={src} target="_blank" rel="noreferrer" className="text-brand hover:underline">
              Mở link gốc
            </a>
          )}
        </div>
      )}
      <div className="mt-1.5 flex flex-col gap-0.5 text-xs">
        <span className="font-mono text-[12px] font-medium text-brand">{code}</span>
        {name && <div className="truncate text-dim" title={name}>{name}</div>}
        {children}
      </div>
    </div>
  )
}
