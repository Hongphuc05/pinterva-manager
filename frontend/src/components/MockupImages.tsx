import { useEffect, useRef, useState } from 'react'
import { ImagePlus, Loader2, X } from 'lucide-react'
import { apiFetch, apiFetchBlob } from '../api/client'

export type ResultImage = {
  id: string
  filename: string
  width: number | null
  height: number | null
  submitted_at: string | null
  on_printerval: boolean
  url: string
}

type ImagesResponse = { staged: ResultImage[]; submitted?: ResultImage[]; max_images?: number }

export const MAX_MOCKUPS = 3
const ACCEPTED = ['image/png', 'image/jpeg']

/** A private image, fetched with the session (the file URL needs authorization). */
function AuthedThumb({ image, className }: { image: ResultImage; className: string }) {
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    let objectUrl: string | null = null
    let alive = true
    apiFetchBlob(image.url)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        if (alive) setSrc(objectUrl)
        else URL.revokeObjectURL(objectUrl)
      })
      .catch(() => {})
    return () => {
      alive = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [image.url])
  if (!src) return <div className={`${className} flex items-center justify-center bg-slate-50`}><Loader2 className="h-4 w-4 animate-spin text-slate-400" /></div>
  return (
    <a href={src} target="_blank" rel="noreferrer noopener" title={image.filename}>
      <img src={src} alt={image.filename} className={`${className} object-cover`} />
    </a>
  )
}

/**
 * Designer: the 1-3 mockup images Printerval requires before Review (Design column). Images are uploaded
 * as soon as they are chosen or pasted, and their ids are reported through `onChange` for the submission.
 */
export function MockupPicker({
  orderId,
  onChange,
  disabled = false,
}: {
  orderId: string
  onChange: (imageIds: string[]) => void
  disabled?: boolean
}) {
  const [staged, setStaged] = useState<ResultImage[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  function apply(images: ResultImage[]) {
    setStaged(images)
    onChangeRef.current(images.map((image) => image.id))
  }

  useEffect(() => {
    apiFetch<ImagesResponse>(`/orders/${orderId}/result-images`)
      .then((data) => apply(Array.isArray(data?.staged) ? data.staged : []))
      .catch(() => {})
  }, [orderId])

  async function upload(files: File[]) {
    setError(null)
    const accepted = files.filter((file) => ACCEPTED.includes(file.type))
    if (accepted.length !== files.length) setError('Ảnh mockup phải là PNG hoặc JPEG.')
    const room = MAX_MOCKUPS - staged.length
    if (accepted.length > room) setError(`Tối đa ${MAX_MOCKUPS} ảnh mockup.`)
    const chosen = accepted.slice(0, Math.max(0, room))
    if (!chosen.length) return
    const form = new FormData()
    chosen.forEach((file) => form.append('images', file, file.name || 'mockup.png'))
    setBusy(true)
    try {
      const data = await apiFetch<ImagesResponse>(`/orders/${orderId}/result-images`, { method: 'POST', body: form })
      apply(Array.isArray(data?.staged) ? data.staged : [])
    } catch (caught: any) {
      setError(caught?.message || 'Không tải được ảnh mockup.')
    } finally {
      setBusy(false)
    }
  }

  async function remove(imageId: string) {
    setBusy(true)
    try {
      const data = await apiFetch<ImagesResponse>(`/orders/${orderId}/result-images/${imageId}`, { method: 'DELETE' })
      apply(Array.isArray(data?.staged) ? data.staged : [])
    } catch (caught: any) {
      setError(caught?.message || 'Không xoá được ảnh.')
    } finally {
      setBusy(false)
    }
  }

  function onPaste(event: React.ClipboardEvent<HTMLDivElement>) {
    const files = Array.from(event.clipboardData.items)
      .filter((item) => item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file))
    if (files.length) {
      event.preventDefault()
      void upload(files)
    }
  }

  return (
    <div className="space-y-1.5" onPaste={onPaste} aria-label="Ảnh mockup">
      <div className="flex flex-wrap items-center gap-1.5">
        {staged.map((image) => (
          <div key={image.id} className="relative h-12 w-12 overflow-hidden rounded-md border border-slate-200">
            <AuthedThumb image={image} className="h-12 w-12" />
            <button
              type="button"
              onClick={() => void remove(image.id)}
              disabled={busy || disabled}
              aria-label={`Bỏ ảnh ${image.filename}`}
              className="absolute right-0 top-0 rounded-bl bg-slate-900/70 p-0.5 text-white disabled:opacity-50"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
        {staged.length < MAX_MOCKUPS && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy || disabled}
            className="inline-flex h-12 items-center gap-1 rounded-md border border-dashed border-slate-300 bg-white px-2 text-[11px] font-semibold text-slate-600 hover:border-[#0052CC] hover:text-[#0052CC] disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />}
            Ảnh mockup ({staged.length}/{MAX_MOCKUPS})
          </button>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg"
          multiple
          hidden
          aria-label="Chọn ảnh mockup"
          onChange={(event) => {
            void upload(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />
      </div>
      <p className="text-[10px] text-slate-500">Bắt buộc 1–{MAX_MOCKUPS} ảnh (PNG/JPEG). Có thể dán ảnh bằng Ctrl/Cmd + V. Ảnh được đưa lên cột Design trên Printerval khi nộp.</p>
      {error && <p className="rounded bg-red-50 px-2 py-1 text-[11px] text-red-700">{error}</p>}
    </div>
  )
}

/** Admin and the order's Designer: the mockups submitted so far, and whether each is on Printerval yet. */
export function SubmittedMockups({ orderId }: { orderId: string }) {
  const [images, setImages] = useState<ResultImage[]>([])
  useEffect(() => {
    apiFetch<ImagesResponse>(`/orders/${orderId}/result-images`)
      .then((data) => setImages(data.submitted ?? []))
      .catch(() => setImages([]))
  }, [orderId])
  if (!images.length) return null
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 text-xs space-y-2" aria-label="Ảnh mockup đã nộp">
      <h3 className="font-bold text-slate-800">Ảnh mockup đã nộp</h3>
      <div className="flex flex-wrap gap-2">
        {images.map((image) => (
          <figure key={image.id} className="w-20 space-y-0.5">
            <AuthedThumb image={image} className="h-20 w-20 rounded-md border border-slate-200" />
            <figcaption className={`text-[10px] ${image.on_printerval ? 'text-emerald-700' : 'text-amber-700'}`}>
              {image.on_printerval ? 'Đã lên Printerval' : 'Chưa lên Printerval'}
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  )
}
