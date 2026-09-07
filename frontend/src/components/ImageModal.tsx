import { X } from 'lucide-react'

type ImageModalProps = {
  isOpen: boolean
  onClose: () => void
  imageUrl: string | null
  altText?: string
}

export function ImageModal({ isOpen, onClose, imageUrl, altText = 'Xem ảnh phóng to' }: ImageModalProps) {
  if (!isOpen || !imageUrl) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="relative max-w-4xl max-h-[90vh] bg-white rounded-2xl p-4 shadow-2xl overflow-hidden flex flex-col items-center border border-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-10 p-2 rounded-full bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900 transition-colors cursor-pointer"
          title="Đóng cửa sổ"
        >
          <X className="h-5 w-5" />
        </button>

        <img
          src={imageUrl}
          alt={altText}
          className="max-h-[80vh] max-w-full rounded-xl object-contain shadow-xs"
        />
      </div>
    </div>
  )
}
