import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiFetch } from '../api/client'

type Card = {
  id: string; external_order_id: string; state: string; product_name: string | null
  thumbnail_url: string | null; job_type: string | null; designer_name: string | null
  deadline_at_ext: string | null; alerts: string[]
}
type Column = { id: string; title: string; cards: Card[] }

export function KanbanPage() {
  const [columns, setColumns] = useState<Column[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    apiFetch<{ columns: Column[] }>('/kanban')
      .then((data) => setColumns(data.columns))
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Không tải được Kanban.'))
  }, [])
  return (
    <main className="p-6">
      <h1 className="text-xl font-bold">Kanban vận hành</h1>
      <p className="mt-1 mb-4 text-sm text-gray-600">Bảng chỉ đọc; trạng thái chỉ đổi qua các thao tác workflow tương ứng.</p>
      {error && <p className="text-red-600">{error}</p>}
      <div className="flex gap-4 overflow-x-auto pb-4">
        {columns.map((column) => (
          <section key={column.id} className="w-72 shrink-0 rounded border bg-gray-50 p-3">
            <h2 className="font-semibold">{column.title} ({column.cards.length})</h2>
            <div className="mt-3 grid gap-3">
              {column.cards.map((card) => (
                <Link key={card.id} to={`/orders/${card.id}`} className="block rounded border bg-white p-3 hover:border-blue-500">
                  <div className="flex gap-2">
                    {card.thumbnail_url && <img src={card.thumbnail_url} alt="" className="h-12 w-12 object-cover" />}
                    <div><strong>{card.external_order_id}</strong><p className="text-sm">{card.product_name ?? card.job_type ?? '-'}</p></div>
                  </div>
                  <p className="mt-2 text-xs text-gray-600">{card.designer_name ?? 'Chưa có designer'} · {card.state}</p>
                  {card.deadline_at_ext && <p className="text-xs text-gray-600">Deadline: {card.deadline_at_ext}</p>}
                  {card.alerts.map((alert) => <span key={alert} className="mt-2 mr-1 inline-block rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">{alert}</span>)}
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  )
}
