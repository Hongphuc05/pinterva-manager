import React, { useState, useEffect, useRef } from 'react'
import {
  Images,
  ExternalLink,
  Copy,
  Check,
  ZoomIn,
  Upload,
  Plus,
  Trash2,
  Loader2,
  Save,
  AlertCircle,
} from 'lucide-react'
import { resolveAssetUrl, apiFetch, ApiError } from '../api/client'
import { deduplicateGalleryUrls } from '../utils/galleryHelper'

type ProductGalleryCardProps = {
  orderId?: string
  images: string[] | null | undefined
  orderTitle?: string | null
  isAdmin?: boolean
  onSelectImage: (index: number) => void
  onGalleryUpdated?: (newImages: string[]) => void
}

export function ProductGalleryCard({
  orderId,
  images,
  orderTitle,
  isAdmin = false,
  onSelectImage,
  onGalleryUpdated,
}: ProductGalleryCardProps) {
  const [galleryList, setGalleryList] = useState<string[]>(() => deduplicateGalleryUrls(images || []))
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Sync internal state when external images change
  useEffect(() => {
    setGalleryList(deduplicateGalleryUrls(images || []))
  }, [images])

  // Convert File to base64 data URL
  function readFileAsBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result as string)
      reader.onerror = (err) => reject(err)
      reader.readAsDataURL(file)
    })
  }

  // Handle single / multiple local image file upload
  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0 || !orderId) return

    setIsUploading(true)
    setErrorMessage(null)
    setSaveSuccess(false)

    const uploadedUrls: string[] = []

    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        const base64Data = await readFileAsBase64(file)

        const res = await apiFetch<{ ok: boolean; image_url: string }>(
          `/orders/${orderId}/upload-gallery-image`,
          {
            method: 'POST',
            body: JSON.stringify({
              filename: file.name,
              content_base64: base64Data,
            }),
          }
        )

        if (res.image_url) {
          uploadedUrls.push(res.image_url)
        }
      }

      if (uploadedUrls.length > 0) {
        setGalleryList((prev) => [...prev, ...uploadedUrls])
      }
    } catch (err: any) {
      setErrorMessage(err?.message || 'Không thể tải ảnh từ máy tính')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  // Remove single image from list
  function handleRemoveImage(indexToRemove: number) {
    setGalleryList((prev) => prev.filter((_, idx) => idx !== indexToRemove))
    setSaveSuccess(false)
  }

  function handleImageLoadError(failedUrl: string) {
    // Gallery imports can contain a URL that passes format validation but is no
    // longer available upstream. Do not leave a broken tile in the designer or
    // admin view; admin can persist this cleaned list with the existing update
    // action if the source image is permanently unavailable.
    setGalleryList((prev) => prev.filter((url) => url !== failedUrl))
    setSaveSuccess(false)
    setErrorMessage(
      isAdmin
        ? 'Đã ẩn một ảnh không thể tải. Bấm “Cập nhật” để lưu danh sách ảnh hợp lệ.'
        : 'Đã ẩn một ảnh không thể tải.',
    )
  }

  // Save changes to backend
  async function handleSaveGallery() {
    if (!orderId) return
    setIsSaving(true)
    setErrorMessage(null)
    setSaveSuccess(false)

    try {
      const res = await apiFetch<{ ok: boolean; image_count: number }>(`/orders/${orderId}/gallery`, {
        method: 'PATCH',
        body: JSON.stringify({ image_urls: galleryList }),
      })

      setSaveSuccess(true)
      onGalleryUpdated?.(galleryList)
      window.dispatchEvent(new CustomEvent('orders-updated'))
      window.dispatchEvent(
        new CustomEvent('gallery-sync-notify', {
          detail: {
            type: 'success',
            message: `Đã cập nhật bộ ${res.image_count} ảnh chi tiết sản phẩm thành công!`,
          },
        })
      )

      setTimeout(() => setSaveSuccess(false), 3500)
    } catch (err: any) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Lỗi khi lưu bộ ảnh.')
    } finally {
      setIsSaving(false)
    }
  }

  const handleCopy = (e: React.MouseEvent, url: string, idx: number) => {
    e.stopPropagation()
    const resolved = resolveAssetUrl(url)
    if (!resolved) return
    navigator.clipboard.writeText(resolved)
    setCopiedIndex(idx)
    setTimeout(() => setCopiedIndex(null), 1500)
  }

  // If not admin and no images, hide card
  if (!isAdmin && galleryList.length === 0) return null

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
      {/* Hidden file input */}
      {isAdmin && (
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*"
          onChange={handleFileUpload}
          className="hidden"
        />
      )}

      {/* Card Header */}
      <div className="flex items-center justify-between border-b border-slate-100 pb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-orange-50 text-orange-600">
            <Images className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">
              Ảnh Chi Tiết Sản Phẩm (Product Gallery)
            </h3>
            {orderTitle && (
              <p className="text-[11px] text-slate-400 font-medium truncate max-w-md">
                {orderTitle}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isAdmin && (
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading || isSaving}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-blue-50 hover:bg-blue-100 text-[#0052CC] font-bold text-xs border border-blue-200 shadow-2xs transition-all cursor-pointer disabled:opacity-50"
              title="Chọn ảnh từ máy tính để thêm vào bộ ảnh đơn hàng này"
            >
              {isUploading ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Đang tải ảnh...</span>
                </>
              ) : (
                <>
                  <Upload className="h-3.5 w-3.5" />
                  <span>Thêm ảnh từ máy</span>
                </>
              )}
            </button>
          )}

          <span
            className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold ${
              galleryList.length > 1
                ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                : 'bg-orange-100 text-orange-800 border border-orange-200'
            }`}
          >
            {galleryList.length} ảnh
          </span>
        </div>
      </div>

      {/* Error alert */}
      {errorMessage && (
        <div className="p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs flex items-center justify-between shadow-2xs">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-red-600 shrink-0" />
            <span>{errorMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="text-red-500 hover:text-red-700 font-bold"
          >
            ✕
          </button>
        </div>
      )}

      {/* Gallery Grid */}
      {galleryList.length === 0 ? (
        <div
          onClick={() => isAdmin && fileInputRef.current?.click()}
          className={`py-8 px-4 rounded-xl border-2 border-dashed border-slate-200 flex flex-col items-center justify-center text-center space-y-2 ${
            isAdmin ? 'hover:border-[#0052CC] hover:bg-blue-50/40 cursor-pointer transition-all' : ''
          }`}
        >
          <div className="p-3 rounded-full bg-slate-100 text-slate-400">
            <Images className="h-6 w-6" />
          </div>
          <p className="text-xs font-semibold text-slate-600">
            Chưa có ảnh chi tiết sản phẩm nào được đồng bộ.
          </p>
          {isAdmin && (
            <p className="text-[11px] text-[#0052CC] font-bold">
              + Bấm vào đây hoặc nút "Thêm ảnh từ máy" để tải ảnh lên
            </p>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {galleryList.map((imgUrl, index) => {
            const resolved = resolveAssetUrl(imgUrl)
            const isCopied = copiedIndex === index

            return (
              <div
                key={index}
                onClick={() => onSelectImage(index)}
                className="group relative rounded-xl border border-slate-200 hover:border-[#0052CC] bg-slate-50 overflow-hidden cursor-pointer shadow-2xs hover:shadow-md transition-all hover:scale-[1.02]"
              >
                {/* Image box */}
                <div className="aspect-square w-full bg-slate-100 flex items-center justify-center overflow-hidden">
                  <img
                    src={resolved}
                    alt={`Product view ${index + 1}`}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    loading="lazy"
                    onError={() => handleImageLoadError(imgUrl)}
                  />
                </div>

                {/* Number badge on bottom right */}
                <div className="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 rounded bg-slate-900/75 text-white font-mono text-[10px] font-bold shadow-xs">
                  #{index + 1}
                </div>

                {/* Delete button (Admin only, top right) */}
                {isAdmin && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleRemoveImage(index)
                    }}
                    className="absolute top-1.5 right-1.5 p-1 rounded-lg bg-rose-600/90 hover:bg-rose-700 text-white shadow opacity-0 group-hover:opacity-100 transition-all cursor-pointer hover:scale-110"
                    title="Xóa ảnh này khỏi bộ ảnh"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}

                {/* Hover overlay with action buttons */}
                <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2 p-1">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      onSelectImage(index)
                    }}
                    className="p-1.5 rounded-full bg-white/90 hover:bg-white text-slate-800 shadow cursor-pointer transition-transform hover:scale-110"
                    title="Phóng to ảnh"
                  >
                    <ZoomIn className="h-3.5 w-3.5" />
                  </button>

                  <button
                    type="button"
                    onClick={(e) => handleCopy(e, imgUrl, index)}
                    className="p-1.5 rounded-full bg-white/90 hover:bg-white text-slate-800 shadow cursor-pointer transition-transform hover:scale-110"
                    title="Sao chép đường link"
                  >
                    {isCopied ? (
                      <Check className="h-3.5 w-3.5 text-emerald-600" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </button>

                  <a
                    href={resolved}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="p-1.5 rounded-full bg-white/90 hover:bg-white text-slate-800 shadow cursor-pointer transition-transform hover:scale-110"
                    title="Mở tab mới"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                </div>
              </div>
            )
          })}

          {/* Quick upload slot card for Admin */}
          {isAdmin && (
            <div
              onClick={() => fileInputRef.current?.click()}
              className="group flex flex-col items-center justify-center aspect-square rounded-xl border-2 border-dashed border-slate-200 hover:border-[#0052CC] bg-slate-50 hover:bg-blue-50/50 cursor-pointer transition-all p-3 text-center"
              title="Thêm ảnh khác từ máy tính"
            >
              {isUploading ? (
                <Loader2 className="h-6 w-6 animate-spin text-[#0052CC]" />
              ) : (
                <>
                  <Plus className="h-6 w-6 text-slate-400 group-hover:text-[#0052CC] transition-colors" />
                  <span className="text-[11px] font-bold text-slate-500 group-hover:text-[#0052CC] mt-1">
                    Thêm ảnh
                  </span>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Card Footer: Update / Save Button on Bottom Right */}
      {isAdmin && (
        <div className="pt-3 border-t border-slate-100 flex items-center justify-between flex-wrap gap-2">
          <p className="text-[11px] text-slate-400">
            * Bấm <strong>"Cập nhật"</strong> để lưu bộ ảnh và đồng bộ tức thì cho Designer.
          </p>

          <button
            type="button"
            onClick={handleSaveGallery}
            disabled={isSaving || isUploading}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#0052CC] hover:bg-[#0041A3] text-white text-xs font-bold shadow-2xs transition-all cursor-pointer disabled:opacity-50 hover:shadow"
          >
            {isSaving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Đang cập nhật...</span>
              </>
            ) : saveSuccess ? (
              <>
                <Check className="h-3.5 w-3.5 text-emerald-300" />
                <span>Đã cập nhật!</span>
              </>
            ) : (
              <>
                <Save className="h-3.5 w-3.5" />
                <span>Cập nhật</span>
              </>
            )}
          </button>
        </div>
      )}
    </div>
  )
}
