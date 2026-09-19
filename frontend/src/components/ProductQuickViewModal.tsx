import { useEffect, useMemo, useRef, useState } from 'react'
import { X, Eye, Loader2, Images, FileText, Package, ChevronLeft, ChevronRight } from 'lucide-react'
import { apiFetch, resolveAssetUrl } from '../api/client'
import { CustomConfigurationSection } from './CustomConfigurationSection'
import { deduplicateGalleryUrls } from '../utils/galleryHelper'

type Variant = { name: string; value: string }
type ConfigEntry = { key: string; value: string }

type QuickViewOrder = {
  id: string
  product_name: string | null
  deadline_tacahu?: string | null
  order_created_at_ext?: string | null
  created_at_ext?: string | null
  product_category: string | null
  product_variants: Variant[] | null
  product_skus?: { variants?: Variant[] | null }[] | null
  custom_config: { original: ConfigEntry[]; translated_vn?: ConfigEntry[] } | null
  source_files: { name: string; url: string }[] | null
  product_image_urls?: string[] | null
  thumbnail_url: string | null
}

type Props = { orderId: string; onClose: () => void }

function cleanVariantName(name: string) {
  return name.trim().replace(/^[|•·\s]+|[|•·\s]+$/g, '').trim()
}

export function ProductQuickViewModal({ orderId, onClose }: Props) {
  const [order, setOrder] = useState<QuickViewOrder | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const galleryViewportRef = useRef<HTMLDivElement | null>(null)
  const [canScrollGalleryLeft, setCanScrollGalleryLeft] = useState(false)
  const [canScrollGalleryRight, setCanScrollGalleryRight] = useState(false)

  useEffect(() => {
    const html = document.documentElement
    const body = document.body
    const previousHtmlOverflow = html.style.overflow
    const previousBodyOverflow = body.style.overflow
    const previousBodyOverscroll = body.style.overscrollBehavior
    html.style.overflow = 'hidden'
    body.style.overflow = 'hidden'
    body.style.overscrollBehavior = 'none'

    return () => {
      html.style.overflow = previousHtmlOverflow
      body.style.overflow = previousBodyOverflow
      body.style.overscrollBehavior = previousBodyOverscroll
    }
  }, [])

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  useEffect(() => {
    let active = true
    apiFetch<{ order: QuickViewOrder }>(`/orders/${orderId}`)
      .then((data) => {
        if (active) setOrder(data.order)
      })
      .catch((caught: Error) => {
        if (active) setError(caught.message || 'Không thể tải thông tin sản phẩm.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [orderId])

  const variants = useMemo(() => {
    const result = new Map<string, Variant>()
    const variantsFromAllSkus = (order?.product_skus || []).flatMap((sku) => sku.variants || [])
    for (const variant of [...(order?.product_variants || []), ...variantsFromAllSkus]) {
      const name = cleanVariantName(variant.name)
      if (name && variant.value) result.set(`${name.toLowerCase()}-${variant.value.toLowerCase()}`, { name, value: variant.value })
    }
    return [...result.values()]
  }, [order])

  const gallery = deduplicateGalleryUrls([
    ...(order?.product_image_urls || []),
    ...(order?.thumbnail_url ? [order.thumbnail_url] : []),
  ])
  const orderAt = order?.order_created_at_ext || order?.created_at_ext || '—'
  const size = variants.filter((variant) => variant.name.toLowerCase() === 'size').map((variant) => variant.value).join(', ') || '—'
  const type = variants.filter((variant) => variant.name.toLowerCase() === 'type').map((variant) => variant.value).join(', ') || '—'
  const style = variants.filter((variant) => variant.name.toLowerCase() === 'style').map((variant) => variant.value).join(', ') || '—'

  function updateGalleryScrollState() {
    const viewport = galleryViewportRef.current
    if (!viewport) return
    setCanScrollGalleryLeft(viewport.scrollLeft > 4)
    setCanScrollGalleryRight(viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 4)
  }

  function scrollGallery(direction: -1 | 1) {
    const viewport = galleryViewportRef.current
    if (!viewport) return
    viewport.scrollBy({ left: direction * Math.max(220, viewport.clientWidth / 2), behavior: 'smooth' })
  }

  useEffect(() => {
    const viewport = galleryViewportRef.current
    if (!viewport) return
    viewport.scrollLeft = 0
    updateGalleryScrollState()
  }, [gallery.length])

  return (
    <div className="fixed inset-0 z-[60] flex h-[100dvh] w-screen items-center justify-center overflow-hidden bg-slate-950/70 p-3 backdrop-blur-xs sm:p-6" onClick={onClose}>
      <div className="flex max-h-[calc(100dvh-1.5rem)] min-h-0 w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl sm:max-h-[calc(100dvh-3rem)]" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="rounded-xl bg-blue-100 p-2 text-[#0052CC]"><Eye className="h-5 w-5" /></div>
            <div className="min-w-0">
              <h2 className="text-sm font-bold uppercase tracking-wide text-slate-800">Xem nhanh sản phẩm</h2>
              <p className="truncate text-xs text-slate-500">{order?.product_name || 'Đang tải...'}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-500 hover:bg-slate-200 hover:text-slate-800" aria-label="Đóng"><X className="h-5 w-5" /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-5" onWheel={(event) => event.stopPropagation()}>
          {loading && <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500"><Loader2 className="h-5 w-5 animate-spin" /> Đang tải thông tin chi tiết...</div>}
          {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>}
          {order && !loading && (
            <div className="space-y-5">
              <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                <Info label="Tên sản phẩm" value={order.product_name || '—'} />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Info label="Category" value={order.product_category || '—'} />
                  <Info label="Type" value={type} />
                  <Info label="Size" value={size} />
                  <Info label="Style" value={style} />
                </div>
                <Info label="Order at" value={orderAt} />
                <Info label="Hạn chót Tacahu" value={order.deadline_tacahu ? new Date(order.deadline_tacahu).toLocaleString('vi-VN') : '—'} />
              </div>

              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 lg:items-start">
                {order.custom_config?.original?.length ? <CustomConfigurationSection entries={order.custom_config.original} /> : <EmptySection title="CUSTOM CONFIGURATION" />}
                {order.custom_config?.translated_vn?.length ? <CustomConfigurationSection entries={order.custom_config.translated_vn} translated /> : <EmptySection title="BẢN DỊCH TIẾNG VIỆT" />}
              </div>

              <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xs">
                <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-5 py-3"><FileText className="h-4 w-4 text-[#0052CC]" /><h3 className="text-xs font-bold uppercase tracking-wider text-slate-800">SOURCE</h3></div>
                {order.source_files?.length ? <div className="divide-y divide-slate-100">{order.source_files.map((file) => <a key={`${file.name}-${file.url}`} href={resolveAssetUrl(file.url)} target="_blank" rel="noreferrer" className="block px-5 py-3 text-xs font-medium text-[#0052CC] hover:bg-blue-50 hover:underline">{file.name}</a>)}</div> : <p className="px-5 py-4 text-xs text-slate-400">Không có source.</p>}
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
                <div className="mb-3 flex items-center gap-2"><Images className="h-4 w-4 text-orange-600" /><h3 className="text-xs font-bold uppercase tracking-wider text-slate-800">GALLERY</h3><span className="rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-bold text-orange-800">{gallery.length} ảnh</span></div>
                {gallery.length ? (
                  <div className="relative">
                    <button type="button" onClick={() => scrollGallery(-1)} disabled={!canScrollGalleryLeft} className="absolute left-0 top-1/2 z-10 -translate-y-1/2 rounded-full border border-slate-200 bg-white/95 p-1.5 text-slate-600 shadow-md transition hover:bg-blue-50 hover:text-[#0052CC] disabled:pointer-events-none disabled:opacity-0" aria-label="Ảnh trước"><ChevronLeft className="h-4 w-4" /></button>
                    <div ref={galleryViewportRef} onScroll={updateGalleryScrollState} className="-mx-1 flex snap-x snap-mandatory gap-3 overflow-x-hidden px-8 py-1">
                      {gallery.map((image, index) => (
                        <a key={`${image}-${index}`} href={resolveAssetUrl(image)} target="_blank" rel="noreferrer" style={{ flex: '0 0 calc((100% - 60px) / 6.5)' }} className="group aspect-square min-w-0 snap-start overflow-hidden rounded-xl border border-slate-200 bg-slate-100">
                          <img src={resolveAssetUrl(image)} alt={`Gallery ${index + 1}`} className="h-full w-full object-cover transition-transform group-hover:scale-105" />
                        </a>
                      ))}
                    </div>
                    <button type="button" onClick={() => scrollGallery(1)} disabled={!canScrollGalleryRight} className="absolute right-0 top-1/2 z-10 -translate-y-1/2 rounded-full border border-slate-200 bg-white/95 p-1.5 text-slate-600 shadow-md transition hover:bg-blue-50 hover:text-[#0052CC] disabled:pointer-events-none disabled:opacity-0" aria-label="Ảnh tiếp theo"><ChevronRight className="h-4 w-4" /></button>
                  </div>
                ) : <div className="flex items-center gap-2 py-5 text-xs text-slate-400"><Package className="h-4 w-4" /> Không có ảnh gallery.</div>}
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Info({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return <div className={wide ? 'sm:col-span-2 lg:col-span-1' : ''}><p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 break-words text-xs font-semibold text-slate-800">{value}</p></div>
}

function EmptySection({ title }: { title: string }) {
  return <section className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-4"><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">{title}</h3><p className="mt-2 text-xs text-slate-400">Không có dữ liệu.</p></section>
}
