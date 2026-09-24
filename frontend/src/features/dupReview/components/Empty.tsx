import { Loader2 } from 'lucide-react'

export function Loading() {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-dup-dim">
      <Loader2 className="size-4 animate-spin" />Đang tải…
    </div>
  )
}

export function Empty({ title, note, error }: { title: string; note?: string; error?: boolean }) {
  return (
    <div className="rounded-lg border border-dashed border-dup-line px-4 py-14 text-center">
      <b className={`block text-sm ${error ? 'text-dup-bad' : 'text-dup-fg'}`}>{title}</b>
      {note && <span className="mt-1 block text-dup-dim">{note}</span>}
    </div>
  )
}
