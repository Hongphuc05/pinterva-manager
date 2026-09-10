import { ChevronLeft, ChevronRight } from 'lucide-react'

type PaginationProps = {
  totalItems: number
  currentPage: number
  pageSize?: number
  onPageChange: (page: number) => void
}

export function Pagination({ totalItems, currentPage, pageSize = 100, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))

  if (totalPages <= 1) return null

  const startItem = (currentPage - 1) * pageSize + 1
  const endItem = Math.min(currentPage * pageSize, totalItems)

  // Generate page numbers with ellipsis
  function getPageNumbers(): (number | '...')[] {
    const pages: (number | '...')[] = []
    const maxVisible = 7

    if (totalPages <= maxVisible) {
      for (let i = 1; i <= totalPages; i++) pages.push(i)
    } else {
      pages.push(1)
      if (currentPage > 3) pages.push('...')
      const start = Math.max(2, currentPage - 1)
      const end = Math.min(totalPages - 1, currentPage + 1)
      for (let i = start; i <= end; i++) pages.push(i)
      if (currentPage < totalPages - 2) pages.push('...')
      pages.push(totalPages)
    }
    return pages
  }

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-4 pb-1 px-1">
      <p className="text-xs text-slate-500 font-medium">
        Hiển thị <span className="font-bold text-slate-700">{startItem}–{endItem}</span> / <span className="font-bold text-slate-700">{totalItems}</span> kết quả
      </p>

      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          className="p-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
          title="Trang trước"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>

        {getPageNumbers().map((pageNum, idx) =>
          pageNum === '...' ? (
            <span key={`ellipsis-${idx}`} className="px-1 text-xs text-slate-400 select-none">…</span>
          ) : (
            <button
              key={pageNum}
              type="button"
              onClick={() => onPageChange(pageNum)}
              className={`min-w-[28px] h-7 px-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                pageNum === currentPage
                  ? 'bg-[#0052CC] text-white shadow-sm border border-[#0052CC]'
                  : 'text-slate-600 hover:bg-slate-100 border border-transparent hover:border-slate-200'
              }`}
            >
              {pageNum}
            </button>
          )
        )}

        <button
          type="button"
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          className="p-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
          title="Trang sau"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}

/** Utility: slice an array for the current page */
export function paginate<T>(items: T[], page: number, pageSize = 100): T[] {
  const start = (page - 1) * pageSize
  return items.slice(start, start + pageSize)
}
