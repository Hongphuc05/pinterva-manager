import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { saveLink } from '../api'
import type { Item } from '../types'
import { useToast } from '../toast'
import { PairCard } from './PairCard'

/** One order of the "Gắn link" tab: its images and a box to paste the link into the work note. */
export function LinkRow({ item, onSaved, onZoom }: { item: Item; onSaved: () => Promise<unknown>; onZoom: (src: string) => void }) {
  const toast = useToast()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      await saveLink(item.id, url.trim())
      toast('Đã lưu link vào note làm việc.')
      setUrl('')
      await onSaved()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-testid={`link-${item.order_code}`}>
      <PairCard item={item} onZoom={onZoom}>
        {item.link && (
          <a href={item.link} target="_blank" rel="noreferrer" className="mt-2 block truncate text-[12px] font-medium text-emerald-700 underline">
            Đã gắn: {item.link}
          </a>
        )}
        <div className="mt-2 flex gap-2">
          <input
            type="url"
            aria-label={`Link cho ${item.order_code}`}
            placeholder={item.link ? 'Dán link khác để thay' : 'Dán link vào note làm việc'}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
          />
          <button
            type="button"
            disabled={busy || !url.trim()}
            onClick={() => void save()}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy && <Loader2 className="size-3.5 animate-spin" />}
            Lưu link
          </button>
        </div>
      </PairCard>
    </div>
  )
}
