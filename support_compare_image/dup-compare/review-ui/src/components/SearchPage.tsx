import { useCallback, useEffect, useRef, useState } from 'react'
import { ImagePlus, Loader2, RefreshCw } from 'lucide-react'
import { searchByImage } from '../api'
import { configEntries, type SearchResult } from '../types'
import { Badge } from './StatusBadge'
import { Figure } from './Figure'
import { Empty } from './Empty'
import { useToast } from './Toaster'

interface Props {
  onZoom: (src: string) => void
}

/** Upload (or drop / paste) one picture from this machine and look for it in the pool. */
export function SearchPage({ onZoom }: Props) {
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<SearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  const run = useCallback(
    async (f: File, refresh = false) => {
      setLoading(true)
      setError(null)
      try {
        setResult(await searchByImage(f, refresh))
      } catch (e) {
        setResult(null)
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  const choose = useCallback(
    (f: File | undefined | null) => {
      if (!f) return
      if (!f.type.startsWith('image/')) {
        toast('Chỉ nhận tệp ảnh.', 'error')
        return
      }
      setPreview((old) => {
        if (old) URL.revokeObjectURL(old)
        return URL.createObjectURL(f)
      })
      setFile(f)
      setFileName(f.name)
      void run(f)
    },
    [run, toast],
  )

  // Ctrl/Cmd+V pastes a screenshot or copied image.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => choose(Array.from(e.clipboardData?.files ?? []).find((f) => f.type.startsWith('image/')))
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [choose])

  return (
    <div className="flex flex-col gap-4">
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          choose(e.dataTransfer.files[0])
        }}
        className={`flex flex-wrap items-center gap-4 rounded-lg border border-dashed p-4 transition ${
          dragging ? 'border-brand bg-brand/10' : 'border-line bg-surface'
        }`}
      >
        {preview ? (
          <Figure imageUrl={preview} code={fileName || 'Ảnh tải lên'} onZoom={onZoom} rawSrc tag={<Badge tone="info">Ảnh của bạn</Badge>} />
        ) : (
          <div className="grid size-36 place-items-center rounded-md border border-line text-dim">
            <ImagePlus className="size-8" />
          </div>
        )}
        <div className="flex min-w-60 flex-1 flex-col gap-2">
          <b className="text-sm">Tìm ảnh trong pool</b>
          <span className="text-dim">
            Kéo thả ảnh vào đây, dán (Ctrl/⌘+V) hoặc chọn từ máy. Ảnh được so với toàn bộ pool bằng cùng model và cùng luật như job.
          </span>
          <div className="flex flex-wrap gap-2">
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              hidden
              data-testid="search-file"
              onChange={(e) => {
                choose(e.target.files?.[0])
                e.target.value = ''
              }}
            />
            <button
              type="button"
              disabled={loading}
              onClick={() => inputRef.current?.click()}
              className="inline-flex h-7 cursor-pointer items-center gap-1.5 rounded bg-brand px-3 text-xs font-medium text-white transition hover:brightness-110 disabled:opacity-50"
            >
              {loading ? <Loader2 className="size-3.5 animate-spin" /> : <ImagePlus className="size-3.5" />}
              Chọn ảnh
            </button>
            {file && (
              <button
                type="button"
                disabled={loading}
                title="Nạp lại pool từ DB rồi tìm lại (nếu vừa có job mới thêm đơn vào pool)"
                onClick={() => void run(file, true)}
                className="inline-flex h-7 cursor-pointer items-center gap-1.5 rounded border border-line bg-raised px-3 text-xs font-medium transition hover:text-fg disabled:opacity-50"
              >
                <RefreshCw className="size-3.5" />Tìm lại (nạp lại pool)
              </button>
            )}
          </div>
          {result && (
            <span className="text-xs text-dim">
              {result.candidates.length} kết quả gần nhất trong {result.pool_count.toLocaleString('vi-VN')} ảnh · {(result.elapsed_ms / 1000).toFixed(1)}s
            </span>
          )}
        </div>
        {result && (result.is_duplicate ? <Badge tone="warn">Model: có ảnh trùng</Badge> : <Badge tone="dim">Model: không thấy trùng</Badge>)}
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 py-10 text-dim">
          <Loader2 className="size-4 animate-spin" />
          Đang tìm… (lần đầu cần nạp model và pool nên có thể mất 30–60 giây)
        </div>
      )}
      {error && <Empty error title="Không tìm được" note={error} />}
      {!loading && result && (
        <div className="flex gap-3 overflow-x-auto rounded-lg border border-line bg-surface p-3">
          {result.candidates.map((c) => {
            const entries = configEntries(c.custom_config)
            return (
              <Figure
                key={`${c.rank}-${c.order_code}`}
                imageUrl={c.image_url}
                code={c.order_code || 'không rõ'}
                name={c.product_name}
                onZoom={onZoom}
                tag={<span className="rounded bg-black/70 px-1 font-mono text-[11px] text-white">{c.rank}</span>}
              >
                <div className="flex items-center justify-between font-mono text-[11px] text-dim">
                  <b className="text-[13px] font-semibold text-fg">{c.similarity.toFixed(3)}</b>
                  <span title="pHash / SSIM">
                    {c.phash_distance ?? '-'} · {c.ssim == null ? '-' : c.ssim.toFixed(2)}
                  </span>
                </div>
                <div className="flex min-h-[18px] flex-wrap gap-1">
                  {c.classification === 'TRUNG' && <Badge tone="warn">Model: trùng</Badge>}
                </div>
                {entries.length > 0 && (
                  <ul className="mt-0.5 space-y-0.5 text-[11px] text-dim">
                    {entries.slice(0, 4).map((e) => (
                      <li key={e.key} className="truncate" title={`${e.key}: ${e.value}`}>
                        <b className="font-medium text-fg/80">{e.key}</b>: {e.value}
                      </li>
                    ))}
                    {entries.length > 4 && <li>… +{entries.length - 4} mục</li>}
                  </ul>
                )}
              </Figure>
            )
          })}
        </div>
      )}
    </div>
  )
}
