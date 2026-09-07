import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch } from '../api/client'

type OrderDetail = {
  id: string
  external_order_id: string
  state: string
  product_name: string | null
  thumbnail_url: string | null
  sku: string | null
  product_category: string | null
  product_variants: { name: string; value: string }[] | null
  has_template: boolean
  multiple_design: boolean
  double_sided: boolean
  deadline_at_ext: string | null
  note_outsource: string
  order_note: string
  custom_config: { original: { key: string; value: string }[] } | null
  design_tool_url: string | null
  created_at: string
}

type WorkflowEvent = { created_at: string; from_state: string | null; to_state: string }

export function OrderDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [order, setOrder] = useState<OrderDetail | null>(null)
  const [history, setHistory] = useState<WorkflowEvent[]>([])

  useEffect(() => {
    if (!id) return
    apiFetch<{ order: OrderDetail; history: WorkflowEvent[] }>(`/orders/${id}`).then((data) => {
      setOrder(data.order)
      setHistory(data.history)
    })
  }, [id])

  if (!order) return <div className="p-6">Đang tải...</div>

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Đơn {order.external_order_id}</h1>
      {order.thumbnail_url && (
        <img src={order.thumbnail_url} alt="" className="max-h-48 mb-4" />
      )}
      <p>Sản phẩm: {order.product_name ?? '-'}</p>
      <p>SKU: {order.sku ?? '-'}</p>
      <p>Category: {order.product_category ?? '-'}</p>
      {order.product_variants && order.product_variants.length > 0 && (
        <ul className="list-disc pl-5">
          {order.product_variants.map((v, i) => (
            <li key={i}>
              {v.name}: {v.value}
            </li>
          ))}
        </ul>
      )}
      <p>Deadline: {order.deadline_at_ext ?? '-'}</p>
      <p>Template: {order.has_template ? 'Đã có' : 'Chưa có'}</p>
      {order.custom_config && order.custom_config.original.length > 0 && (
        <>
          <h2 className="font-bold mt-4">Custom configuration</h2>
          <table className="border-collapse">
            <tbody>
              {order.custom_config.original.map((entry, i) => (
                <tr key={i}>
                  <td className="pr-4">{entry.key}</td>
                  <td>{entry.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {order.design_tool_url && (
        <p className="mt-4">
          <a
            className="underline"
            href={order.design_tool_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Gen design custom
          </a>
        </p>
      )}
      <p>Note outsource: {order.note_outsource || '-'}</p>
      <p>Order note: {order.order_note || '-'}</p>
      <p>Trạng thái hiện tại: <strong>{order.state}</strong></p>

      <h2 className="font-bold mt-6">Lịch sử</h2>
      <table className="border-collapse w-full">
        <thead>
          <tr className="text-left border-b">
            <th>Thời gian</th>
            <th>Từ</th>
            <th>Đến</th>
          </tr>
        </thead>
        <tbody>
          {history.length === 0 && (
            <tr>
              <td colSpan={3}>Chưa có lịch sử.</td>
            </tr>
          )}
          {history.map((e, i) => (
            <tr key={i} className="border-b">
              <td>{e.created_at}</td>
              <td>{e.from_state ?? '-'}</td>
              <td>{e.to_state}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-4">
        <Link className="underline" to="/orders">
          ← Quay lại danh sách
        </Link>
      </p>
    </div>
  )
}
