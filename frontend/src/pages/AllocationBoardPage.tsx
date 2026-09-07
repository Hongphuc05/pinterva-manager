import { useState, type ReactNode } from 'react'
import { DndContext, type DragEndEvent, useDraggable, useDroppable } from '@dnd-kit/core'
import { apiFetch } from '../api/client'

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

function DesignerColumn({ designer, children }: { designer: BoardDesigner; children: ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: designer.id })
  const full = designer.capacity !== null && designer.held >= designer.capacity
  return (
    <div
      ref={setNodeRef}
      className={`border p-2 w-64 min-h-40 ${isOver ? 'bg-blue-50' : ''}`}
    >
      <h3 className="font-bold mb-2">
        {designer.full_name}: {designer.held}/{designer.capacity ?? '∞'}
        {full && <span className="text-red-600 ml-1">Full</span>}
      </h3>
      {children}
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
    try {
      await apiFetch('/allocation/assign', {
        method: 'POST',
        body: JSON.stringify({ order_id: order.external_order_id, designer_id: over.id }),
      })
      await loadBoard(batchId)
    } catch {
      setError('Gán đơn thất bại.')
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
              <DesignerColumn key={d.id} designer={d}>
                {null}
              </DesignerColumn>
            ))}
          </div>
        </DndContext>
      )}
    </div>
  )
}
