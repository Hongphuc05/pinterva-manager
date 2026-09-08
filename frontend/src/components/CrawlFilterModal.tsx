import { useState } from 'react'
import { X, Search, RotateCcw } from 'lucide-react'

// Mirrors Printerval's own filter bar (docs/phase0-field-map.md §4). Only "Tất cả 2D &
// 3D" is confirmed safe on the fast HTTP crawl path — picking any other value routes
// the crawl through the slower, DOM-verified Playwright fallback instead (see
// PrintervalApiAdapter.discover_orders). Status/Designer stay fixed: crawling is
// specifically for claiming *new* orders, which only ever matters for "Waiting" (an
// order with a designer already set isn't a candidate to claim) — so those two
// controls wouldn't do anything real here, shown disabled for visual parity with the
// site rather than silently ignored. Date range (created_at) IS wired — live-confirmed
// 2026-09-08 against the real find endpoint.
const JOB_TYPES = ['Tất cả 2D & 3D', '2D', '3D', 'ART', 'WOOD', 'CALENDAR', 'EMBROIDERY', 'AI']

type CrawlFilterModalProps = {
  isOpen: boolean
  onClose: () => void
  onSearch: (jobType: string, dateFrom: string, dateTo: string) => void
  loading: boolean
}

export function CrawlFilterModal({ isOpen, onClose, onSearch, loading }: CrawlFilterModalProps) {
  const [jobType, setJobType] = useState(JOB_TYPES[0])
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl overflow-hidden border border-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
          <h2 className="text-base font-bold text-slate-800">Quét đơn theo bộ lọc</h2>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-xs text-slate-500">
            Giống bộ lọc bên Printerval — chỉ quét thêm đơn khớp bộ lọc vào CSDL, không đụng tới đơn cũ đã có sẵn.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-700 block">Status</label>
              <input
                disabled
                value="Waiting"
                title="Quét luôn nhắm vào đơn Waiting (đơn mới, chưa có designer) — đây là đối tượng duy nhất có thể claim."
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 bg-slate-50 text-slate-400"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-700 block">Designer</label>
              <input
                disabled
                value="Chưa chia cho ai"
                title="Đơn Waiting luôn chưa có designer — không có gì để lọc thêm."
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 bg-slate-50 text-slate-400"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-bold text-slate-700 block">Loại design job</label>
            <select
              value={jobType}
              onChange={(e) => setJobType(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
            >
              {JOB_TYPES.map((jt) => (
                <option key={jt} value={jt}>
                  {jt}
                </option>
              ))}
            </select>
            <p className="text-[10px] text-slate-400">
              "Tất cả 2D & 3D" dùng đường quét nhanh (API). Chọn 1 loại cụ thể sẽ chậm hơn (đi qua trình duyệt để lọc đúng như bên Printerval).
            </p>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-bold text-slate-700 block">Ngày tạo — Date from/to</label>
            <div className="grid grid-cols-2 gap-3">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
              />
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
              />
            </div>
            <p className="text-[10px] text-slate-400">
              Bỏ trống = quét tất cả. Chỉ lọc theo "Ngày tạo" (created_at), chỉ áp dụng khi Loại design job = "Tất cả 2D & 3D".
            </p>
          </div>

          <div className="pt-2 flex justify-end gap-2 border-t border-slate-100">
            <button
              type="button"
              onClick={() => {
                setJobType(JOB_TYPES[0])
                setDateFrom('')
                setDateTo('')
              }}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl cursor-pointer"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Clear form
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={() => onSearch(jobType, dateFrom, dateTo)}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl disabled:opacity-50 cursor-pointer"
            >
              <Search className="h-3.5 w-3.5" />
              {loading ? 'Đang quét...' : 'Search'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
