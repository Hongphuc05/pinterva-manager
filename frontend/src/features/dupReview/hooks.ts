import { useCallback, useEffect, useRef, useState } from 'react'
import { searchByImage, type SearchStage } from './api'
import type { SearchResult } from './types'

export interface HistoryEntry {
  id: string
  name: string
  at: string
  /** Small JPEG of the uploaded picture (data URL) so the search can be looked at again after a reload. */
  thumb: string | null
  result: SearchResult
}

const KEY = 'dupreview.search.history.v1'
const MAX_ENTRIES = 30

function load(): HistoryEntry[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.slice(0, MAX_ENTRIES) : []
  } catch {
    return []
  }
}

function save(entries: HistoryEntry[]) {
  // Storage is small: drop the oldest searches until it fits.
  for (let list = entries; ; list = list.slice(0, -1)) {
    try {
      localStorage.setItem(KEY, JSON.stringify(list))
      return
    } catch {
      if (!list.length) return
    }
  }
}

/** Downscale the upload to a ≤512px JPEG. Null when the browser cannot (the entry still works). */
async function makeThumb(file: File): Promise<string | null> {
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, 512 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', 0.82)
  } catch {
    return null
  }
}

/**
 * Search-by-image state that lives in App, so it survives switching tabs (the request keeps running
 * too), and is stored in localStorage so past searches can be reopened after a reload.
 */
export function useSearchHistory() {
  const [entries, setEntries] = useState<HistoryEntry[]>(load)
  const [activeId, setActiveId] = useState<string | null>(() => load()[0]?.id ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<{ name: string; url: string } | null>(null)
  const [stage, setStage] = useState<SearchStage>('queued')
  const files = useRef(new Map<string, File>())

  useEffect(() => save(entries), [entries])

  const search = useCallback(async (file: File, opts: { replaceId?: string } = {}) => {
    setLoading(true)
    setError(null)
    setStage('queued')
    const url = URL.createObjectURL(file)
    setPending({ name: file.name, url })
    try {
      const [result, thumb] = await Promise.all([searchByImage(file, setStage), makeThumb(file)])
      const entry: HistoryEntry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        name: file.name || 'Ảnh dán',
        at: new Date().toISOString(),
        thumb,
        result,
      }
      files.current.set(entry.id, file)
      setEntries((prev) => [entry, ...prev.filter((e) => e.id !== opts.replaceId)].slice(0, MAX_ENTRIES))
      setActiveId(entry.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      URL.revokeObjectURL(url)
      setPending(null)
      setLoading(false)
    }
  }, [])

  const remove = useCallback(
    (id: string) => {
      setEntries((prev) => prev.filter((e) => e.id !== id))
      files.current.delete(id)
      setActiveId((cur) => (cur === id ? (entries.find((e) => e.id !== id)?.id ?? null) : cur))
    },
    [entries],
  )

  const clear = useCallback(() => {
    setEntries([])
    files.current.clear()
    setActiveId(null)
  }, [])

  /** Search the same file again (only while the file is still in memory). */
  const retry = useCallback(
    (id: string) => {
      const file = files.current.get(id)
      return file ? search(file, { replaceId: id }) : undefined
    },
    [search],
  )

  const active = entries.find((e) => e.id === activeId) ?? null
  return { entries, active, activeId, setActiveId, loading, stage, error, pending, search, remove, clear, retry, canRetry: (id: string) => files.current.has(id) }
}

export type SearchHistory = ReturnType<typeof useSearchHistory>
