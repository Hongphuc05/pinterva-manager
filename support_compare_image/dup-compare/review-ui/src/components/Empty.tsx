import { AlertTriangle, Loader2, Package } from 'lucide-react'

export function Loading() {
  return (
    <div className="flex items-center justify-center gap-2 py-14 text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />Đang tải…
    </div>
  )
}

export function Empty({ title, note, error }: { title: string; note?: string; error?: boolean }) {
  const Icon = error ? AlertTriangle : Package
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-14 text-center text-muted-foreground shadow-sm">
      <Icon className="mx-auto mb-2 size-10 text-muted-foreground/60" />
      <b className="mb-0.5 block text-[15px] text-foreground">{title}</b>
      <span>{note}</span>
    </div>
  )
}
