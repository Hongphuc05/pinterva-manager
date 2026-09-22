import { useCallback, useEffect, useRef, useState } from 'react'
import { Image as ImageIcon, Loader2, Plus, RefreshCw, Trash2, Upload, X } from 'lucide-react'
import { apiFetch, apiFetchBlob, type ApiError } from '../api/client'

export type BankQrImage = {
  id: string
  filename: string
  content_type: string
  byte_size: number
  sort_order: number
  url: string
}

type BankQrListResponse = { images: BankQrImage[] }

function errorMessage(error: unknown): string {
  return error && typeof error === 'object' && 'message' in error
    ? String((error as ApiError).message)
    : 'Không thể cập nhật ảnh QR.'
}

export function BankQrManager() {
  const [images, setImages] = useState<BankQrImage[]>([])
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [replaceImageId, setReplaceImageId] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const loadImages = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch<BankQrListResponse>('/users/me/bank-qr')
      const nextUrls: Record<string, string> = {}
      await Promise.all(response.images.map(async (image) => {
        const blob = await apiFetchBlob(image.url)
        nextUrls[image.id] = URL.createObjectURL(blob)
      }))
      setPreviewUrls((previous) => {
        Object.values(previous).forEach((url) => URL.revokeObjectURL(url))
        return nextUrls
      })
      setImages(response.images)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadImages()
  }, [loadImages])

  useEffect(() => () => {
    Object.values(previewUrls).forEach((url) => URL.revokeObjectURL(url))
  }, [previewUrls])

  const openPicker = (imageId: string | null = null) => {
    setReplaceImageId(imageId)
    inputRef.current?.click()
  }

  const uploadFile = async (file: File, replacingId: string | null) => {
    const form = new FormData()
    form.append('file', file)
    const route = replacingId
      ? `/users/me/bank-qr?replace_image_id=${encodeURIComponent(replacingId)}`
      : '/users/me/bank-qr'
    return apiFetch<BankQrImage>(route, { method: 'POST', body: form })
  }

  const handleFiles = async (selectedFiles: FileList | null) => {
    if (!selectedFiles || selectedFiles.length === 0) return
    const files = Array.from(selectedFiles)
    const availableSlots = 3 - images.length + (replaceImageId ? 1 : 0)
    if (files.length > availableSlots) {
      setError(`Tối đa 3 ảnh QR. Hiện còn ${availableSlots} vị trí trống.`)
      return
    }
    setBusy(true)
    setError(null)
    try {
      let replacement = replaceImageId
      for (const file of files) {
        if (!file.type.startsWith('image/')) throw new Error('Chỉ được chọn file ảnh.')
        await uploadFile(file, replacement)
        replacement = null
      }
      await loadImages()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
      setReplaceImageId(null)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const removeImage = async (image: BankQrImage) => {
    if (!window.confirm(`Xóa ảnh QR “${image.filename}”?`)) return
    setBusy(true)
    setError(null)
    try {
      await apiFetch(`/users/me/bank-qr/${image.id}`, { method: 'DELETE' })
      await loadImages()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-2xs">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-4">
        <div className="flex items-start gap-3">
          <div className="rounded-xl border border-blue-100 bg-blue-50 p-2 text-[#0052CC]"><ImageIcon className="h-5 w-5" /></div>
          <div>
            <h2 className="text-sm font-bold text-slate-800">Mã QR tài khoản ngân hàng</h2>
            <p className="mt-1 text-xs text-slate-500">Thêm tối đa 3 ảnh để Admin tiện thanh toán công.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void loadImages()} disabled={loading || busy} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 disabled:opacity-50" title="Tải lại ảnh QR" aria-label="Tải lại ảnh QR">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button type="button" onClick={() => openPicker()} disabled={busy || images.length >= 3} className="inline-flex items-center gap-1.5 rounded-lg bg-[#0052CC] px-3 py-2 text-xs font-bold text-white hover:bg-[#003D99] disabled:cursor-not-allowed disabled:opacity-50">
            <Plus className="h-4 w-4" /> Thêm ảnh
          </button>
        </div>
      </div>

      <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={(event) => void handleFiles(event.target.files)} className="hidden" />

      {error && (
        <div className="mt-4 flex items-start justify-between gap-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-800">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Đóng thông báo lỗi"><X className="h-4 w-4" /></button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-10 text-xs text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Đang tải ảnh QR...</div>
      ) : images.length === 0 ? (
        <button type="button" onClick={() => openPicker()} className="mt-4 flex w-full flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 py-9 text-xs text-slate-500 hover:border-blue-300 hover:bg-blue-50/40">
          <Upload className="mb-2 h-6 w-6 text-slate-400" /> Chưa có ảnh QR — bấm để thêm ảnh
        </button>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {images.map((image) => (
            <div key={image.id} className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
              <div className="flex h-44 items-center justify-center bg-white p-3">
                {previewUrls[image.id] ? <img src={previewUrls[image.id]} alt={image.filename} className="h-full w-full object-contain" /> : <Loader2 className="h-5 w-5 animate-spin text-slate-400" />}
              </div>
              <div className="flex items-center justify-between gap-2 border-t border-slate-200 px-3 py-2">
                <span className="min-w-0 truncate text-[11px] font-medium text-slate-600" title={image.filename}>{image.filename}</span>
                <div className="flex shrink-0 items-center gap-1">
                  <button type="button" onClick={() => openPicker(image.id)} disabled={busy} className="rounded-md px-2 py-1 text-[11px] font-bold text-[#0052CC] hover:bg-blue-100 disabled:opacity-50">Đổi ảnh</button>
                  <button type="button" onClick={() => void removeImage(image)} disabled={busy} className="rounded-md p-1.5 text-rose-600 hover:bg-rose-100 disabled:opacity-50" title="Xóa ảnh QR" aria-label={`Xóa ${image.filename}`}><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
