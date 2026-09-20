import { useEffect, useRef, useState } from 'react'
import { FileText, ImagePlus, Loader2, Send, X } from 'lucide-react'
import { apiFetch, apiFetchBlob } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { ImageModal } from './ImageModal'
import { LinkifiedText } from './LinkifiedText'

type Attachment = {
  id: string
  filename: string
  content_type: string
  byte_size: number
  url: string
}

type WorkNote = {
  id: string
  body: string
  author_name: string
  author_role: string
  created_at: string
  attachments: Attachment[]
}

type PendingImage = { file: File; preview: string }

export function OrderWorkNotesCard({ orderId }: { orderId: string }) {
  const { user } = useAuth()
  const [notes, setNotes] = useState<WorkNote[]>([])
  const [body, setBody] = useState('')
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([])
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [modalImages, setModalImages] = useState<string[] | null>(null)
  const [attachmentUrls, setAttachmentUrls] = useState<Record<string, string>>({})
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pendingImagesRef = useRef<PendingImage[]>([])
  const attachmentUrlsRef = useRef<Record<string, string>>({})

  async function loadNotes() {
    try {
      const data = await apiFetch<{ notes: WorkNote[] }>(`/orders/${orderId}/work-notes`)
      setNotes(data.notes || [])
      setError(null)
    } catch (caught: any) {
      setError(caught?.message || 'Không thể tải Note làm việc.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    void loadNotes()
  }, [orderId])

  useEffect(() => {
    pendingImagesRef.current = pendingImages
  }, [pendingImages])

  useEffect(() => {
    attachmentUrlsRef.current = attachmentUrls
  }, [attachmentUrls])

  useEffect(() => () => pendingImagesRef.current.forEach((image) => URL.revokeObjectURL(image.preview)), [])
  useEffect(() => () => Object.values(attachmentUrlsRef.current).forEach((url) => URL.revokeObjectURL(url)), [])

  useEffect(() => {
    let cancelled = false
    const missing = notes.flatMap((note) => note.attachments).filter((attachment) => !attachmentUrls[attachment.id])
    if (!missing.length) return

    void Promise.all(missing.map(async (attachment) => [attachment.id, URL.createObjectURL(await apiFetchBlob(attachment.url))] as const))
      .then((loaded) => {
        if (cancelled) {
          loaded.forEach(([, url]) => URL.revokeObjectURL(url))
          return
        }
        setAttachmentUrls((current) => {
          const additions = loaded.filter(([id]) => !current[id])
          loaded.filter(([id]) => current[id]).forEach(([, url]) => URL.revokeObjectURL(url))
          return additions.length ? { ...current, ...Object.fromEntries(additions) } : current
        })
      })
      .catch(() => setError('Không thể tải một hoặc nhiều ảnh Note làm việc.'))
    return () => { cancelled = true }
  }, [notes, attachmentUrls])

  function addImages(files: File[]) {
    const accepted = files.filter((file) => ['image/png', 'image/jpeg', 'image/webp'].includes(file.type))
    if (accepted.length !== files.length) setError('Chỉ nhận ảnh PNG, JPEG hoặc WebP.')
    setPendingImages((current) => {
      const remaining = 5 - current.length
      if (accepted.length > remaining) setError('Tối đa 5 ảnh cho một lần cập nhật.')
      return [...current, ...accepted.slice(0, remaining).map((file) => ({ file, preview: URL.createObjectURL(file) }))]
    })
  }

  function handlePaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const images = Array.from(event.clipboardData.items)
      .filter((item) => item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file))
    if (images.length) {
      event.preventDefault()
      addImages(images)
    }
  }

  function removePendingImage(index: number) {
    setPendingImages((current) => {
      URL.revokeObjectURL(current[index].preview)
      return current.filter((_, itemIndex) => itemIndex !== index)
    })
  }

  async function sendNote() {
    if (!body.trim() && pendingImages.length === 0) return
    setSending(true)
    setError(null)
    try {
      const form = new FormData()
      form.set('body', body)
      form.set('request_id', crypto.randomUUID())
      pendingImages.forEach(({ file }) => form.append('images', file, file.name || 'pasted-image.png'))
      const note = await apiFetch<WorkNote>(`/orders/${orderId}/work-notes`, { method: 'POST', body: form })
      setNotes((current) => [...current, note])
      pendingImages.forEach((image) => URL.revokeObjectURL(image.preview))
      setPendingImages([])
      setBody('')
      window.dispatchEvent(new CustomEvent('orders-updated'))
    } catch (caught: any) {
      setError(caught?.message || 'Không thể cập nhật Note làm việc.')
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="rounded-xl border border-blue-100 bg-blue-50/50 p-4 text-xs space-y-3">
      <div className="flex items-center gap-1.5 font-bold text-slate-800">
        <FileText className="h-4 w-4 text-[#0052CC]" />
        <span>Note làm việc</span>
      </div>
      <p className="text-[11px] text-slate-500">Ghi chú chung của đơn. Mọi cập nhật được giữ lại theo thời gian.</p>

      {loading ? (
        <div className="py-4 text-center text-slate-400">Đang tải note…</div>
      ) : notes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white/70 p-3 text-slate-400">Chưa có ghi chú làm việc.</div>
      ) : (
        <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
          {notes.map((note) => {
            const mine = note.author_role === user?.role && note.author_name === (user.full_name || user.username)
            return (
              <article key={note.id} className={`rounded-lg border p-3 ${mine ? 'border-blue-200 bg-white' : 'border-slate-200 bg-slate-50'}`}>
                <div className="mb-1 flex items-center justify-between gap-3 text-[10px] text-slate-500">
                  <strong className="text-slate-700">{note.author_name} · {note.author_role === 'admin' ? 'Admin' : 'Designer'}</strong>
                  <span>{new Date(note.created_at).toLocaleString('vi-VN')}</span>
                </div>
                {note.body && <p className="whitespace-pre-wrap break-words text-slate-700"><LinkifiedText text={note.body} /></p>}
                {note.attachments.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {note.attachments.map((attachment) => {
                      const imageUrl = attachmentUrls[attachment.id]
                      return (
                        <button key={attachment.id} type="button" disabled={!imageUrl}
                          onClick={() => setModalImages(note.attachments.map((item) => attachmentUrls[item.id]).filter(Boolean))}
                          className="h-20 w-20 overflow-hidden rounded-lg border border-slate-200 bg-white hover:ring-2 hover:ring-[#0052CC] disabled:opacity-50">
                          {imageUrl ? <img src={imageUrl} alt={attachment.filename} className="h-full w-full object-cover" /> : <Loader2 className="m-auto h-4 w-4 animate-spin text-slate-400" />}
                        </button>
                      )
                    })}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}

      <div className="space-y-2 border-t border-blue-100 pt-3">
        <label className="block font-bold text-slate-700">Cập nhật Note làm việc</label>
        <textarea value={body} onChange={(event) => setBody(event.target.value)} onPaste={handlePaste} rows={3}
          placeholder="Nhập ghi chú; Ctrl/Cmd + V để dán ảnh…"
          className="w-full rounded-lg border border-slate-200 bg-white p-2 text-xs focus:border-[#0052CC] focus:outline-none" />
        {pendingImages.length > 0 && <div className="flex flex-wrap gap-2">
          {pendingImages.map((image, index) => <div key={image.preview} className="relative h-16 w-16 overflow-hidden rounded-lg border border-slate-200 bg-white">
            <img src={image.preview} alt="Ảnh chờ gửi" className="h-full w-full object-cover" />
            <button type="button" onClick={() => removePendingImage(index)} className="absolute right-0 top-0 rounded-bl bg-slate-900/70 p-0.5 text-white"><X className="h-3 w-3" /></button>
          </div>)}
        </div>}
        {error && <p className="rounded bg-red-50 p-2 text-red-700">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp" multiple className="hidden" onChange={(event) => addImages(Array.from(event.target.files || []))} />
          <button type="button" onClick={() => fileInputRef.current?.click()} disabled={sending} className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-white px-3 py-1.5 font-bold text-[#0052CC] disabled:opacity-50"><ImagePlus className="h-3.5 w-3.5" /> Thêm ảnh</button>
          <button type="button" onClick={sendNote} disabled={sending || (!body.trim() && pendingImages.length === 0)} className="inline-flex items-center gap-1 rounded-lg bg-[#0052CC] px-3 py-1.5 font-bold text-white disabled:opacity-50">{sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />} Gửi cập nhật</button>
        </div>
      </div>
      <ImageModal isOpen={Boolean(modalImages)} onClose={() => setModalImages(null)} images={modalImages} hideExternalLink />
    </section>
  )
}
