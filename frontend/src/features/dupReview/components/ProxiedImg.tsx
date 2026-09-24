import { useEffect, useState } from 'react'
import { apiFetchBlob } from '../../../api/client'

// Third-party CDNs may block hotlinking, so images go through the API (/support-review/img), which
// needs the bearer token: fetch them as blobs. A small pool keeps 100+ thumbnails from flooding it.
const MAX_PARALLEL = 6
const cache = new Map<string, Promise<string>>()
let active = 0
const waiting: (() => void)[] = []

function acquire(): Promise<void> {
  if (active < MAX_PARALLEL) {
    active++
    return Promise.resolve()
  }
  return new Promise((resolve) => waiting.push(() => { active++; resolve() }))
}

function release() {
  active--
  waiting.shift()?.()
}

export function loadProxied(url: string): Promise<string> {
  let hit = cache.get(url)
  if (!hit) {
    hit = acquire().then(async () => {
      try {
        const blob = await apiFetchBlob(`/support-review/img?url=${encodeURIComponent(url)}`)
        return URL.createObjectURL(blob)
      } finally {
        release()
      }
    })
    cache.set(url, hit)
    hit.catch(() => cache.delete(url)) // a failed image may be retried later
  }
  return hit
}

/** Forget every loaded image (tests, or after the session changes). */
export function clearProxiedCache() {
  cache.clear()
}

export const isHttpUrl = (u: string) => /^https?:\/\//i.test(u)

/** Blob URL of a proxied image ('loading' until fetched, null when it cannot be loaded). */
export function useProxiedSrc(url: string | null | undefined): string | null | 'loading' {
  const [state, setState] = useState<{ url: string; src: string | null } | null>(null)
  useEffect(() => {
    if (!url || !isHttpUrl(url)) return
    let alive = true
    loadProxied(url).then(
      (src) => alive && setState({ url, src }),
      () => alive && setState({ url, src: null }),
    )
    return () => {
      alive = false
    }
  }, [url])
  if (!url || !isHttpUrl(url)) return null
  return state?.url === url ? state.src : 'loading'
}

interface Props {
  url: string
  alt: string
  className?: string
  onLoadedSrc?: (src: string) => void
}

export function ProxiedImg({ url, alt, className, onLoadedSrc }: Props) {
  const src = useProxiedSrc(url)
  useEffect(() => {
    if (src && src !== 'loading') onLoadedSrc?.(src)
  }, [src, onLoadedSrc])
  if (src === 'loading') return <span className="text-[11px] text-dup-dim">Đang tải…</span>
  if (!src) return <span className="text-[11px] text-dup-dim">Không tải được ảnh</span>
  return <img src={src} alt={alt} className={className} />
}
