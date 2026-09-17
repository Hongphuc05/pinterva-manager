import { useState } from 'react'
import { Check, Copy, Languages, Settings2 } from 'lucide-react'

export type CustomConfigurationEntry = { key: string; value: string }

type Props = {
  entries: CustomConfigurationEntry[]
  translated?: boolean
}

function isInternalOrPriceEntry(key: string, value: string): boolean {
  const k = key.toLowerCase().trim()
  if (
    k === 'price_addtocart' ||
    k === 'giá_thêm_vào_giỏ_hàng' ||
    k === 'price' ||
    k === 'prx_discount' ||
    k === 'discount' ||
    k.startsWith('price_') ||
    k.startsWith('giá_thêm_') ||
    k.includes('addtocart')
  ) {
    return true
  }
  const v = value.trim()
  if (v.startsWith('{') && v.endsWith('}')) {
    if (v.includes('"price"') || v.includes('"prx_discount"') || v.includes('"type": "image"')) {
      return true
    }
  }
  // Image URL in text configuration (should be in Gallery/Source files)
  if (v.startsWith('http') && (v.includes('assets.printerval.com') || /\.(jpg|jpeg|png|webp)/i.test(v))) {
    return true
  }
  return false
}

function RowCopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // fallback
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? 'Đã sao chép!' : 'Sao chép giá trị'}
      className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-all cursor-pointer shrink-0"
    >
      {copied ? <Check className="h-4 w-4 text-emerald-600 stroke-[2.5]" /> : <Copy className="h-4 w-4" />}
    </button>
  )
}

export function CustomConfigurationSection({ entries, translated = false }: Props) {
  // Filter out internal metadata / image JSON objects
  const filteredEntries = entries.filter((e) => !isInternalOrPriceEntry(e.key, e.value))

  if (filteredEntries.length === 0) {
    return null
  }

  const containerBorder = translated ? 'border-blue-200' : 'border-slate-200'
  const headerBg = translated ? 'bg-blue-50/70 border-blue-200 text-blue-900' : 'bg-slate-50 border-slate-200 text-slate-800'
  const badgeBg = translated ? 'bg-blue-200/80 text-blue-900' : 'bg-slate-200 text-slate-700'

  return (
    <div className={`overflow-hidden rounded-2xl border ${containerBorder} bg-white shadow-xs`}>
      {/* Header */}
      <div className={`flex items-center justify-between border-b px-5 py-3 ${headerBg}`}>
        <div className="flex items-center gap-2">
          {translated ? (
            <Languages className="h-4 w-4 text-blue-700" />
          ) : (
            <Settings2 className="h-4 w-4 text-slate-700" />
          )}
          <h3 className="text-xs font-bold uppercase tracking-wider">
            {translated ? 'BẢN DỊCH TIẾNG VIỆT' : 'CUSTOM CONFIGURATION'}
          </h3>
        </div>
        <span className={`rounded-md px-2 py-0.5 text-[11px] font-bold font-mono ${badgeBg}`}>
          {translated ? 'VN' : 'Original'}
        </span>
      </div>

      {/* Rows Table */}
      <div className="divide-y divide-slate-100">
        {filteredEntries.map((entry, index) => {
          // Clean any potential remaining domain strings from display value
          const displayValue = entry.value
            .replace(/https?:\/\/assets\.printerval\.com[^\s]*/gi, '')
            .trim()

          return (
            <div
              key={`${entry.key}-${index}`}
              className="grid grid-cols-[minmax(180px,1.2fr)_minmax(0,2.5fr)_auto] items-center gap-4 px-5 py-3 text-xs hover:bg-slate-50/60 transition-colors"
            >
              {/* Key Label */}
              <span className="font-bold text-slate-800 break-words">
                {entry.key}
              </span>

              {/* Custom Value */}
              <span className="font-medium text-slate-600 break-words whitespace-pre-wrap">
                {displayValue || '—'}
              </span>

              {/* Copy Button */}
              <div>
                <RowCopyButton value={displayValue || entry.value} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
