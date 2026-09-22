import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, Image as ImageIcon, Loader2, X } from 'lucide-react'
import { apiFetch, apiFetchBlob, ApiError } from '../api/client'
import type { BankQrImage } from './BankQrManager'

type Props = {
  isOpen: boolean
  onClose: () => void
  designerId: string
  designerName: string
}

export function BankQrViewerModal({ isOpen, onClose, designerId, designerName }: Props) {
  const [urls, setUrls] = useState<string[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setCurrentIndex(0)
    void apiFetch<{ images: BankQrImage[] }>(`/users/${designerId}/bank-qr`)
      .then(async (response) => {
        const nextUrls = await Promise.all(response.images.map((image) => apiFetchBlob(image.url).then((blob) => URL.createObjectURL(blob))))
        if (cancelled) {
          nextUrls.forEach((url) => URL.revokeObjectURL(url))
          return
        }
        setUrls(nextUrls)
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof ApiError ? caught.message : 'Không thể tải ảnh QR.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [designerId, isOpen])

  useEffect(() => () => urls.forEach((url) => URL.revokeObjectURL(url)), [urls])

  useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'ArrowLeft' && urls.length > 1) setCurrentIndex((index) => (index > 0 ? index - 1 : urls.length - 1))
      if (event.key === 'ArrowRight' && urls.length > 1) setCurrentIndex((index) => (index < urls.length - 1 ? index + 1 : 0))
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose, urls.length])

  if (!isOpen) return null

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/80 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="relative flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-4">
          <div className="flex items-center gap-2"><ImageIcon className="h-5 w-5 text-[#0052CC]" /><div><h3 className="text-sm font-bold text-slate-900">QR tài khoản ngân hàng</h3><p className="text-xs text-slate-500">{designerName}</p></div></div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-200 hover:text-slate-700" aria-label="Đóng QR"><X className="h-5 w-5" /></button>
        </div>
        <div className="relative flex min-h-[360px] items-center justify-center bg-slate-100 p-6">
          {loading ? <Loader2 className="h-8 w-8 animate-spin text-[#0052CC]" /> : error ? <p className="text-sm text-rose-700">{error}</p> : urls.length === 0 ? <p className="text-sm text-slate-500">Designer chưa thêm ảnh QR.</p> : <>
            {urls.length > 1 && <button type="button" onClick={() => setCurrentIndex((index) => (index > 0 ? index - 1 : urls.length - 1))} className="absolute left-4 rounded-full bg-white p-2 text-slate-700 shadow hover:bg-blue-50" aria-label="Ảnh QR trước"><ChevronLeft className="h-6 w-6" /></button>}
            <img src={urls[currentIndex]} alt={`QR ${currentIndex + 1} của ${designerName}`} className="max-h-[62vh] max-w-full rounded-lg object-contain shadow" />
            {urls.length > 1 && <button type="button" onClick={() => setCurrentIndex((index) => (index < urls.length - 1 ? index + 1 : 0))} className="absolute right-4 rounded-full bg-white p-2 text-slate-700 shadow hover:bg-blue-50" aria-label="Ảnh QR sau"><ChevronRight className="h-6 w-6" /></button>}
          </>}
        </div>
        {urls.length > 1 && <div className="border-t border-slate-200 px-4 py-3 text-center text-xs font-semibold text-slate-500">Ảnh {currentIndex + 1} / {urls.length}</div>}
      </div>
    </div>,
    document.body,
  )
}
