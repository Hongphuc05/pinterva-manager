import type { ReactNode } from 'react'
import { isHttpUrl, useProxiedSrc } from './ProxiedImg'

interface FigureProps {
  imageUrl: string
  code: string
  name?: string | null
  tag?: ReactNode
  chosen?: boolean
  /** Receives a URL the lightbox can show directly (a blob: URL). */
  onZoom: (src: string) => void
  /** The image is a local blob: URL (an upload), not something to fetch through the API proxy. */
  rawSrc?: boolean
  children?: ReactNode
}

/** An image with its order code underneath. Every image in the tool carries a code. */
export function Figure({ imageUrl, code, name, tag, chosen, onZoom, rawSrc, children }: FigureProps) {
  const proxied = useProxiedSrc(rawSrc ? null : imageUrl)
  const src = rawSrc ? imageUrl : proxied
  const hasUrl = rawSrc ? Boolean(imageUrl) : isHttpUrl(imageUrl)
  const failed = !rawSrc && hasUrl && proxied === null
  return (
    <div className="w-36 flex-none">
      {src && src !== 'loading' ? (
        <button
          type="button"
          title="Bấm để phóng to"
          onClick={() => onZoom(src)}
          className={`relative block size-36 cursor-zoom-in overflow-hidden rounded-md border bg-white p-0 ${
            chosen ? 'border-dup-ok ring-2 ring-dup-ok/40' : 'border-dup-line'
          }`}
        >
          <img src={src} alt={code} className="size-full object-contain" />
          {tag && <span className="absolute left-1 top-1">{tag}</span>}
        </button>
      ) : (
        <div className="grid size-36 place-content-center gap-1 rounded-md border border-dup-line bg-dup-surface p-2 text-center text-dup-dim">
          <span>{src === 'loading' ? 'Đang tải…' : failed ? 'Không tải được ảnh' : 'Không có ảnh'}</span>
          {failed && (
            <a href={imageUrl} target="_blank" rel="noreferrer" className="text-dup-brand hover:underline">
              Mở link gốc
            </a>
          )}
        </div>
      )}
      <div className="mt-1.5 flex flex-col gap-0.5 text-xs">
        <span className="font-mono text-[12px] font-medium text-dup-brand">{code}</span>
        {name && <div className="truncate text-dup-dim" title={name}>{name}</div>}
        {children}
      </div>
    </div>
  )
}
