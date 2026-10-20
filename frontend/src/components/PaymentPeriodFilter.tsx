import { useState } from 'react'
import { recentWeeks, type PeriodFilterValue } from '../features/payments/api'

/** Week picker + from/to days used by the Accountant list and the pay popup. */
export function PaymentPeriodFilter({
  value,
  onChange,
  className = '',
}: {
  value: PeriodFilterValue
  onChange: (next: PeriodFilterValue) => void
  className?: string
}) {
  const [weeks] = useState(() => recentWeeks())
  const hasRange = Boolean(value.from || value.to)

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <select
        aria-label="Lọc theo thời gian nộp bài"
        value={hasRange ? '' : value.week}
        onChange={(e) => onChange({ week: e.target.value, from: '', to: '' })}
        className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 shadow-sm"
      >
        <option value="">Tất cả các tuần</option>
        {weeks.map((w) => (
          <option key={w.value} value={w.value}>{w.label}</option>
        ))}
      </select>
      <label className="flex items-center gap-1 text-xs text-slate-600">
        Từ ngày
        <input type="date" aria-label="Từ ngày" value={value.from} max={value.to || undefined}
          onChange={(e) => onChange({ week: '', from: e.target.value, to: value.to })}
          className="rounded-lg border border-slate-300 bg-white px-1.5 py-1 text-xs shadow-sm" />
      </label>
      <label className="flex items-center gap-1 text-xs text-slate-600">
        đến ngày
        <input type="date" aria-label="Đến ngày" value={value.to} min={value.from || undefined}
          onChange={(e) => onChange({ week: '', from: value.from, to: e.target.value })}
          className="rounded-lg border border-slate-300 bg-white px-1.5 py-1 text-xs shadow-sm" />
      </label>
      {hasRange && (
        <button
          type="button"
          onClick={() => onChange({ week: '', from: '', to: '' })}
          className="text-xs font-semibold text-slate-500 underline hover:text-slate-700"
        >
          Xoá ngày
        </button>
      )}
    </div>
  )
}
