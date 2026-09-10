import { useState, useEffect } from 'react'
import { X, ChevronLeft, ChevronRight, Copy, Check, ExternalLink, Download } from 'lucide-react'
import { resolveAssetUrl } from '../api/client'

type ImageModalProps = {
  isOpen: boolean
  onClose: () => void
  imageUrl?: string | null
  images?: string[] | null
  initialIndex?: number
  altText?: string
  hideExternalLink?: boolean
}

export function ImageModal({
  isOpen,
  onClose,
  imageUrl,
  images,
  initialIndex = 0,
  altText = 'Xem ảnh phóng to',
  hideExternalLink = false,
}: ImageModalProps) {
  // Aggregate images list
  const imageList: string[] = []
  if (images && images.length > 0) {
    images.forEach((img) => {
      if (img && !imageList.includes(img)) imageList.push(img)
    })
  } else if (imageUrl) {
    imageList.push(imageUrl)
  }

  const [currentIndex, setCurrentIndex] = useState(initialIndex)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setCurrentIndex(initialIndex >= 0 && initialIndex < imageList.length ? initialIndex : 0)
    }
  }, [isOpen, initialIndex, imageList.length])

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft') handlePrev()
      else if (e.key === 'ArrowRight') handleNext()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, currentIndex, imageList.length])

  if (!isOpen || imageList.length === 0) return null

  const activeImg = imageList[currentIndex] || imageList[0]
  const resolvedUrl = resolveAssetUrl(activeImg)

  const handlePrev = () => {
    setCurrentIndex((prev) => (prev > 0 ? prev - 1 : imageList.length - 1))
  }

  const handleNext = () => {
    setCurrentIndex((prev) => (prev < imageList.length - 1 ? prev + 1 : 0))
  }

  const handleCopyLink = () => {
    if (!resolvedUrl) return
    navigator.clipboard.writeText(resolvedUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/80 backdrop-blur-sm p-3 md:p-6 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="relative max-w-5xl w-full max-h-[94vh] bg-slate-900/95 border border-slate-700/60 rounded-2xl shadow-2xl overflow-hidden flex flex-col items-center"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header Bar */}
        <div className="w-full flex items-center justify-between px-5 py-3 border-b border-slate-800 bg-slate-950/60 text-slate-300 text-xs">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-white">
              Ảnh {currentIndex + 1} / {imageList.length}
            </span>
            {imageList.length > 1 && (
              <span className="text-[11px] text-slate-400 hidden sm:inline">
                (Dùng phím ← / → để chuyển ảnh)
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {!hideExternalLink && (
              <>
                <button
                  onClick={handleCopyLink}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors cursor-pointer text-xs"
                  title="Sao chép link ảnh"
                >
                  {copied ? (
                    <>
                      <Check className="h-3.5 w-3.5 text-emerald-400" />
                      <span className="text-emerald-400 font-medium">Đã chép</span>
                    </>
                  ) : (
                    <>
                      <Copy className="h-3.5 w-3.5" />
                      <span>Copy link</span>
                    </>
                  )}
                </button>

                <a
                  href={resolvedUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors cursor-pointer text-xs"
                  title="Mở ảnh gốc trong tab mới"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  <span>Mở tab mới</span>
                </a>
              </>
            )}

            <button
              onClick={async () => {
                try {
                  const response = await fetch(resolvedUrl)
                  const blob = await response.blob()
                  const blobUrl = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = blobUrl
                  a.download = `image-${currentIndex + 1}.png`
                  document.body.appendChild(a)
                  a.click()
                  a.remove()
                  URL.revokeObjectURL(blobUrl)
                } catch {
                  window.open(resolvedUrl, '_blank', 'noopener,noreferrer')
                }
              }}
              className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors cursor-pointer text-xs font-semibold"
              title="Tải ảnh về máy"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Tải ảnh</span>
            </button>

            <button
              onClick={onClose}
              className="p-1.5 rounded-md bg-slate-800 hover:bg-red-600/80 hover:text-white text-slate-400 transition-colors cursor-pointer ml-1"
              title="Đóng (Esc)"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Main Image Display Area */}
        <div className="relative w-full flex-1 flex items-center justify-center p-4 min-h-[360px] max-h-[72vh] overflow-hidden select-none">
          {imageList.length > 1 && (
            <button
              onClick={handlePrev}
              className="absolute left-4 z-10 p-2.5 rounded-full bg-slate-800/80 hover:bg-slate-700 text-white shadow-lg border border-slate-600/50 cursor-pointer transition-all hover:scale-105"
              title="Ảnh trước (←)"
            >
              <ChevronLeft className="h-6 w-6" />
            </button>
          )}

          <img
            src={resolvedUrl}
            alt={altText}
            className="max-h-[70vh] max-w-full rounded-lg object-contain shadow-2xl transition-all duration-200"
          />

          {imageList.length > 1 && (
            <button
              onClick={handleNext}
              className="absolute right-4 z-10 p-2.5 rounded-full bg-slate-800/80 hover:bg-slate-700 text-white shadow-lg border border-slate-600/50 cursor-pointer transition-all hover:scale-105"
              title="Ảnh sau (→)"
            >
              <ChevronRight className="h-6 w-6" />
            </button>
          )}
        </div>

        {/* Bottom Thumbnail Strip */}
        {imageList.length > 1 && (
          <div className="w-full px-4 py-2.5 border-t border-slate-800 bg-slate-950/80 flex items-center gap-2 overflow-x-auto justify-center">
            {imageList.map((img, idx) => {
              const isSelected = idx === currentIndex
              return (
                <button
                  key={idx}
                  onClick={() => setCurrentIndex(idx)}
                  className={`relative shrink-0 w-12 h-12 rounded-lg overflow-hidden border-2 transition-all cursor-pointer ${
                    isSelected
                      ? 'border-blue-500 scale-105 ring-2 ring-blue-500/40'
                      : 'border-slate-700 opacity-60 hover:opacity-100 hover:border-slate-500'
                  }`}
                  title={`Ảnh ${idx + 1}`}
                >
                  <img
                    src={resolveAssetUrl(img)}
                    alt=""
                    className="w-full h-full object-cover"
                  />
                  <span className="absolute bottom-0 right-0 bg-black/70 text-white text-[9px] font-mono px-1 rounded-tl">
                    {idx + 1}
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
