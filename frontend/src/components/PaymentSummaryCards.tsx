import { CheckCircle2, Clock, CreditCard } from 'lucide-react'
import type { PaymentSummary } from '../features/payments/api'

const money = (n: number) => `${n.toLocaleString('vi-VN')} đ`

/** The Admin finance page's three KPI cards, so the Accountant can see where the money stands. */
export function PaymentSummaryCards({ summary }: { summary: PaymentSummary | null }) {
  const cards = [
    {
      key: 'credited',
      title: 'Tổng đơn tính công',
      count: summary?.credited_count ?? 0,
      amount: summary?.credited_amount ?? 0,
      note: 'Vào Review + Có link bài',
      color: 'text-[#0052CC]',
      amountColor: 'text-slate-500',
      iconBox: 'border-blue-100 bg-blue-50 text-[#0052CC]',
      Icon: CheckCircle2,
    },
    {
      key: 'unpaid',
      title: 'Chưa thanh toán',
      count: summary?.unpaid_count ?? 0,
      amount: summary?.unpaid_amount ?? 0,
      note: 'Chờ thanh toán công',
      color: 'text-amber-600',
      amountColor: 'text-amber-700',
      iconBox: 'border-amber-100 bg-amber-50 text-amber-600',
      Icon: Clock,
    },
    {
      key: 'paid',
      title: 'Đã thanh toán',
      count: summary?.paid_count ?? 0,
      amount: summary?.paid_amount ?? 0,
      note: 'Đã được xác nhận thanh toán',
      color: 'text-emerald-600',
      amountColor: 'text-emerald-700',
      iconBox: 'border-emerald-100 bg-emerald-50 text-emerald-600',
      Icon: CreditCard,
    },
  ]
  return (
    <div data-testid="payment-summary" className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      {cards.map(({ key, title, count, amount, note, color, amountColor, iconBox, Icon }) => (
        <div key={key} className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</p>
            <div className="mt-1 flex items-baseline gap-2">
              <h3 className={`font-mono text-2xl font-bold ${color}`}>{count}</h3>
              <span className={`font-mono text-xs font-bold ${amountColor}`}>({money(amount)})</span>
            </div>
            <p className="mt-0.5 text-[11px] text-slate-400">{note}</p>
          </div>
          <div className={`rounded-xl border p-3 ${iconBox}`}>
            <Icon className="h-6 w-6" />
          </div>
        </div>
      ))}
    </div>
  )
}
