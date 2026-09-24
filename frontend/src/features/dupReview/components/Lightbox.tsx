import { useEffect } from 'react'

export function Lightbox({ src, onClose }: { src: string | null; onClose: () => void }) {
  useEffect(() => {
    if (!src) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [src, onClose])

  if (!src) return null
  return (
    <div
      role="dialog"
      aria-label="Xem ảnh lớn"
      className="fixed inset-0 z-[90] flex cursor-zoom-out items-center justify-center bg-black/85 p-6"
      onClick={onClose}
    >
      <img src={src} alt="" className="max-h-full max-w-full rounded-lg bg-white" />
    </div>
  )
}
