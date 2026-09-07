import { useState } from 'react'
import { DndContext, type DragEndEvent, useDraggable, useDroppable } from '@dnd-kit/core'
import { apiFetch } from '../api/client'
import { useAuth } from '../auth/AuthContext'

type BoardOrder = {
  id: string
  external_order_id: string
  thumbnail_url: string | null
  sku: string | null
  deadline_at_ext: string | null
}

type BoardDesigner = {
  id: string
  full_name: string
  capacity: number | null
  held: number
  pending_approvals: { approval_id: string; order: BoardOrder }[]
}

type BoardData = { unassigned: BoardOrder[]; designers: BoardDesigner[] }

function OrderCard({ order }: { order: BoardOrder }) {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({ id: order.id })
  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined
  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className="border p-2 mb-2 bg-white cursor-grab"
    >
      {order.thumbnail_url && <img src={order.thumbnail_url} alt="" className="h-10 mb-1" />}
      <div className="text-sm font-mono">{order.external_order_id}</div>
      <div className="text-xs text-gray-500">{order.sku ?? '-'}</div>
    </div>
  )
}

function DesignerColumn({
  designer,
  onOffer,
  onDecide,
}: {
  designer: BoardDesigner
  onOffer: (designerId: string, quantity: number) => Promise<void>
  onDecide: (approvalId: string, decision: 'approve' | 'cancel', reason?: string) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: designer.id })
  const { user } = useAuth()
  const [quantity, setQuantity] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const full = designer.capacity !== null && designer.held >= designer.capacity
  const isSelf = user?.id === designer.id

  async function handleClickOffer() {
    setSubmitting(true)
    try {
      await onOffer(designer.id, quantity)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div ref={setNodeRef} className={`border p-2 w-64 min-h-40 ${isOver ? 'bg-blue-50' : ''}`}>
      <h3 className="font-bold mb-2">
        {designer.full_name}: {designer.held}/{designer.capacity ?? '∞'}
        {full && <span className="text-red-600 ml-1">Full</span>}
      </h3>
      {isSelf && (
        <div className="mb-2 flex gap-1">
          <input
            type="number"
            min={1}
            className="border w-16 p-1"
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
          />
          <button
            className="bg-green-600 text-white px-2 disabled:opacity-50"
            disabled={submitting}
            onClick={handleClickOffer}
          >
            Nhận
          </button>
        </div>
      )}
      {designer.pending_approvals.map((p) => (
        <div key={p.approval_id} className="border p-2 mb-2 bg-yellow-50">
          <div className="text-sm font-mono">{p.order.external_order_id}</div>
          <div className="flex gap-1 mt-1">
            <button
              className="bg-green-600 text-white px-2 text-xs"
              onClick={() => onDecide(p.approval_id, 'approve')}
            >
              Approve
            </button>
            <button
              className="bg-red-600 text-white px-2 text-xs"
              onClick={() => {
                const reason = window.prompt('Lý do huỷ:')
                if (reason) onDecide(p.approval_id, 'cancel', reason)
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

export function AllocationBoardPage() {
  const [batchId, setBatchId] = useState('')
  const [board, setBoard] = useState<BoardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function loadBoard(id: string) {
    if (!id) return
    try {
      const data = await apiFetch<BoardData>(`/allocation/board?batch_id=${id}`)
      setBoard(data)
      setError(null)
    } catch {
      setError('Không tải được board — kiểm tra batch ID.')
    }
  }

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || !board) return
    const order = board.unassigned.find((o) => o.id === active.id)
    if (!order) return
    const requestId = crypto.randomUUID()
    try {
      await apiFetch('/allocation/assign', {
        method: 'POST',
        body: JSON.stringify({
          order_id: order.external_order_id,
          designer_id: over.id,
          request_id: requestId,
        }),
      })
      await loadBoard(batchId)
    } catch {
      setError('Gán đơn thất bại.')
    }
  }

  async function handleOffer(_designerId: string, quantity: number) {
    const requestId = crypto.randomUUID()
    try {
      await apiFetch('/allocation/offer', {
        method: 'POST',
        body: JSON.stringify({ batch_id: batchId, quantity, request_id: requestId }),
      })
      await loadBoard(batchId)
    } catch {
      setError('Offer thất bại — có thể vượt capacity.')
    }
  }

  async function handleDecide(approvalId: string, decision: 'approve' | 'cancel', reason?: string) {
    try {
      const result = await apiFetch<{ decided_by_me: boolean }>(`/approvals/${approvalId}/decide`, {
        method: 'POST',
        body: JSON.stringify({ decision, reason }),
      })
      if (!result.decided_by_me) {
        setError('Đơn này đã được admin khác xử lý trước đó.')
      }
      await loadBoard(batchId)
    } catch {
      setError('Quyết định thất bại.')
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Phân bổ đơn</h1>
      <div className="mb-4">
        <input
          className="border p-1"
          placeholder="Batch ID"
          value={batchId}
          onChange={(e) => setBatchId(e.target.value)}
        />
        <button className="bg-blue-600 text-white px-3 py-1 ml-2" onClick={() => loadBoard(batchId)}>
          Tải
        </button>
      </div>
      {error && <p className="text-red-600 mb-4">{error}</p>}
      {board && (
        <DndContext onDragEnd={handleDragEnd}>
          <div className="flex gap-4">
            <div className="border p-2 w-64 min-h-40">
              <h3 className="font-bold mb-2">Kho đơn chưa gán ({board.unassigned.length})</h3>
              {board.unassigned.map((o) => (
                <OrderCard key={o.id} order={o} />
              ))}
            </div>
            {board.designers.map((d) => (
              <DesignerColumn key={d.id} designer={d} onOffer={handleOffer} onDecide={handleDecide} />
            ))}
          </div>
        </DndContext>
      )}
    </div>
  )
}
