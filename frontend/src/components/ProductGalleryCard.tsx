import { useState } from 'react'
import { Images, ExternalLink, Copy, Check, ZoomIn } from 'lucide-react'
import { resolveAssetUrl } from '../api/client'

type ProductGalleryCardProps = {
  images: string[] | null | undefined
  orderTitle?: string | null
  onSelectImage: (index: number) => void
}

export function ProductGalleryCard({ images, orderTitle, onSelectImage }: ProductGalleryCardProps) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)

  if (!images || images.length === 0) return null

  const handleCopy = (e: React.MouseEvent, url: string, idx: number) => {
    e.stopPropagation()
    const resolved = resolveAssetUrl(url)
    if (!resolved) return
    navigator.clipboard.writeText(resolved)
    setCopiedIndex(idx)
    setTimeout(() => setCopiedIndex(null), 1500)
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
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
        <span className="px-2.5 py-0.5 rounded-full bg-orange-100 text-orange-800 text-[11px] font-bold">
          {images.length} ảnh
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {images.map((imgUrl, index) => {
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
                />
              </div>

              {/* Number badge on bottom right (style of CopyImage extension) */}
              <div className="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 rounded bg-slate-900/75 text-white font-mono text-[10px] font-bold shadow-xs">
                #{index + 1}
              </div>

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
      </div>
    </div>
  )
}
