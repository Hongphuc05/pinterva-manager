import { useEffect, useMemo, useState } from 'react'
import { X, Eye, Loader2, Images, FileText, Package } from 'lucide-react'
import { apiFetch, resolveAssetUrl } from '../api/client'
import { CustomConfigurationSection } from './CustomConfigurationSection'
import { deduplicateGalleryUrls } from '../utils/galleryHelper'

type Variant = { name: string; value: string }
type ConfigEntry = { key: string; value: string }

type QuickViewOrder = {
  id: string
  product_name: string | null
  order_created_at_ext?: string | null
  created_at_ext?: string | null
  product_category: string | null
  product_variants: Variant[] | null
  custom_config: { original: ConfigEntry[]; translated_vn?: ConfigEntry[] } | null
  source_files: { name: string; url: string }[] | null
  product_image_urls?: string[] | null
  thumbnail_url: string | null
}

type Props = { orderId: string; onClose: () => void }

function cleanVariantName(name: string) {
  return name.trim().replace(/^[|•·\s]+|[|•·\s]+$/g, '').trim()
}

export function ProductQuickViewButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        onClick()
      }}
      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-1.5 py-1 text-[10px] font-bold text-[#0052CC] transition-colors hover:bg-blue-100"
      title="Xem nhanh thông tin sản phẩm"
      aria-label="Xem nhanh thông tin sản phẩm"
    >
      <Eye className="h-3 w-3" />
      Xem nhanh
    </button>
  )
}

export function ProductQuickViewModal({ orderId, onClose }: Props) {
  const [order, setOrder] = useState<QuickViewOrder | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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
    for (const variant of order?.product_variants || []) {
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

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/60 p-3 backdrop-blur-xs sm:p-6" onClick={onClose}>
      <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
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

        <div className="overflow-y-auto p-5">
          {loading && <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500"><Loader2 className="h-5 w-5 animate-spin" /> Đang tải thông tin chi tiết...</div>}
          {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>}
          {order && !loading && (
            <div className="space-y-5">
              <div className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-4 sm:grid-cols-2 lg:grid-cols-5">
                <Info label="Tên sản phẩm" value={order.product_name || '—'} wide />
                <Info label="Order at" value={orderAt} />
                <Info label="Category" value={order.product_category || '—'} />
                <Info label="Type" value={type} />
                <Info label="Size" value={size} />
              </div>

              {order.custom_config?.original?.length ? <CustomConfigurationSection entries={order.custom_config.original} /> : <EmptySection title="CUSTOM CONFIGURATION" />}
              {order.custom_config?.translated_vn?.length ? <CustomConfigurationSection entries={order.custom_config.translated_vn} translated /> : <EmptySection title="BẢN DỊCH TIẾNG VIỆT" />}

              <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xs">
                <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-5 py-3"><FileText className="h-4 w-4 text-[#0052CC]" /><h3 className="text-xs font-bold uppercase tracking-wider text-slate-800">SOURCE</h3></div>
                {order.source_files?.length ? <div className="divide-y divide-slate-100">{order.source_files.map((file) => <a key={`${file.name}-${file.url}`} href={resolveAssetUrl(file.url)} target="_blank" rel="noreferrer" className="block px-5 py-3 text-xs font-medium text-[#0052CC] hover:bg-blue-50 hover:underline">{file.name}</a>)}</div> : <p className="px-5 py-4 text-xs text-slate-400">Không có source.</p>}
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
                <div className="mb-3 flex items-center gap-2"><Images className="h-4 w-4 text-orange-600" /><h3 className="text-xs font-bold uppercase tracking-wider text-slate-800">GALLERY</h3><span className="rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-bold text-orange-800">{gallery.length} ảnh</span></div>
                {gallery.length ? <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">{gallery.map((image, index) => <a key={`${image}-${index}`} href={resolveAssetUrl(image)} target="_blank" rel="noreferrer" className="group aspect-square overflow-hidden rounded-xl border border-slate-200 bg-slate-100"><img src={resolveAssetUrl(image)} alt={`Gallery ${index + 1}`} className="h-full w-full object-cover transition-transform group-hover:scale-105" /></a>)}</div> : <div className="flex items-center gap-2 py-5 text-xs text-slate-400"><Package className="h-4 w-4" /> Không có ảnh gallery.</div>}
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
