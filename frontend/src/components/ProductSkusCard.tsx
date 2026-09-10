import { useState } from 'react'
import { Package, ImageIcon } from 'lucide-react'
import { resolveAssetUrl } from '../api/client'
import { ImageModal } from './ImageModal'

export type ProductSku = {
  sku?: string | null
  image_url?: string | null
  category?: string | null
  variants?: { name: string; value: string }[] | null
  custom_config?: {
    original?: { key: string; value: string }[]
    translated_vn?: { key: string; value: string }[]
  } | null
}

type ProductSkusCardProps = {
  productSkus?: ProductSku[] | null
  fallbackSku?: string | null
  fallbackCategory?: string | null
  fallbackVariants?: { name: string; value: string }[] | null
  isAdmin?: boolean
}

export function productSkuCount(productSkus?: ProductSku[] | null) {
  return productSkus?.length ?? 0
}

export function ProductSkusCard({
  productSkus,
  fallbackSku,
  fallbackCategory,
  fallbackVariants,
  isAdmin = false,
}: ProductSkusCardProps) {
  const [selectedImage, setSelectedImage] = useState<string | null>(null)
  const items = productSkus && productSkus.length > 0
    ? productSkus
    : (fallbackSku || fallbackCategory || (fallbackVariants && fallbackVariants.length > 0)
      ? [{ sku: fallbackSku, category: fallbackCategory, variants: fallbackVariants }]
      : [])

  if (items.length === 0) return null

  return (
    <>
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-blue-50 text-[#0052CC]">
              <Package className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                {isAdmin ? 'Mẫu hàng / SKU' : 'Mẫu Hàng Thiết Kế'}
              </h3>
              <p className="text-[11px] text-slate-400">Mỗi mẫu hàng trong đơn được lưu riêng.</p>
            </div>
          </div>
          <span className="px-2.5 py-0.5 rounded-full bg-blue-100 text-blue-800 text-[11px] font-bold">
            {items.length} mẫu hàng
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {items.map((item, index) => (
            <article key={`${item.sku || 'sku'}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
              <div className="flex gap-3">
                {item.image_url ? (
                  <button
                    type="button"
                    onClick={() => setSelectedImage(item.image_url!)}
                    className="shrink-0 cursor-pointer hover:opacity-90 transition-opacity"
                    title="Click để xem ảnh mẫu"
                  >
                    <img src={resolveAssetUrl(item.image_url)} alt={item.sku || `Mẫu ${index + 1}`} className="h-16 w-16 rounded-lg object-cover border border-slate-200" />
                  </button>
                ) : (
                  <div className="h-16 w-16 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                    <Package className="h-6 w-6" />
                  </div>
                )}
                <div className="min-w-0">
                  <p className="font-mono text-xs font-bold text-slate-800 break-all">
                    {isAdmin ? (item.sku || `Mẫu hàng ${index + 1}`) : (item.category || `Mẫu hàng ${index + 1}`)}
                  </p>
                  {isAdmin && item.category && <p className="text-xs text-slate-600 mt-1"><strong>Category:</strong> {item.category}</p>}
                  {item.image_url && (
                    <button
                      type="button"
                      onClick={() => setSelectedImage(item.image_url!)}
                      className="inline-flex items-center gap-1 text-[11px] font-bold text-[#0052CC] hover:underline mt-1 cursor-pointer"
                    >
                      <ImageIcon className="h-3 w-3" />
                      <span>Xem ảnh mẫu</span>
                    </button>
                  )}
                </div>
              </div>

              {item.variants && item.variants.length > 0 && (
                <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs">
                  {item.variants.map((variant, variantIndex) => (
                    <div key={`${variant.name}-${variantIndex}`} className="contents">
                      <dt className="font-bold text-slate-700">{variant.name}:</dt>
                      <dd className="text-slate-600 break-words">{variant.value}</dd>
                    </div>
                  ))}
                </dl>
              )}

              {item.custom_config?.original && item.custom_config.original.length > 0 && (
                <details className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
                  <summary className="cursor-pointer font-semibold text-slate-700">
                    Cấu hình custom ({item.custom_config.original.length})
                  </summary>
                  <dl className="mt-2 space-y-1.5">
                    {item.custom_config.original.map((entry, configIndex) => (
                      <div key={`${entry.key}-${configIndex}`}>
                        <dt className="font-semibold text-slate-600">{entry.key}</dt>
                        <dd className="mt-0.5 text-slate-500 break-all whitespace-pre-wrap">{entry.value}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              )}
            </article>
          ))}
        </div>
      </section>

      <ImageModal
        isOpen={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
        altText="Ảnh mẫu hàng"
        hideExternalLink={!isAdmin}
      />
    </>
  )
}
