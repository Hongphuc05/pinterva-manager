import { useState } from 'react'
import { DndContext, type DragEndEvent, useDraggable, useDroppable } from '@dnd-kit/core'
import { ApiError, apiFetch } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { 
  Kanban, 
  Search, 
  UserCheck, 
  CheckCircle2, 
  XCircle, 
  GripVertical, 
  Package, 
  AlertCircle,
  Plus
} from 'lucide-react'

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
type DecideResult = {
  decided_by_me: boolean
  decided_by_name: string
  decided_at: string
}

function OrderCard({ order }: { order: BoardOrder }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: order.id })
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`group rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs hover:shadow-md transition-all cursor-grab active:cursor-grabbing ${
        isDragging ? 'opacity-50 ring-2 ring-[#0052CC] z-50 shadow-xl' : ''
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="text-slate-300 group-hover:text-slate-500 pt-0.5 transition-colors">
          <GripVertical className="h-4 w-4" />
        </div>
        {order.thumbnail_url ? (
          <img src={order.thumbnail_url} alt="" className="h-10 w-10 rounded-lg object-cover border border-slate-200 shrink-0" />
        ) : (
          <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
            <Package className="h-5 w-5" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-mono font-bold text-[#0052CC] truncate">{order.external_order_id}</p>
          <p className="text-[11px] text-slate-500 font-mono truncate mt-0.5">{order.sku ?? 'No SKU'}</p>
        </div>
      </div>
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
    <div
      ref={setNodeRef}
      className={`rounded-xl border border-slate-200 bg-white p-4 w-80 shrink-0 flex flex-col shadow-xs transition-colors ${
        isOver ? 'bg-blue-50/60 border-[#0052CC] ring-2 ring-[#0052CC]/20' : ''
      }`}
    >
      {/* Column Header */}
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-blue-50 text-[#0052CC]">
            <UserCheck className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-xs font-bold text-slate-800">{designer.full_name}</h3>
            <p className="text-[10px] text-slate-400 font-mono">ID: {designer.id.slice(0, 8)}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded-md bg-slate-100 text-slate-700">
            {designer.held}/{designer.capacity ?? '∞'}
          </span>
          {full && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700 uppercase">
              Full
            </span>
          )}
        </div>
      </div>

      {/* Offer Input (if designer looking at self) */}
      {isSelf && (
        <div className="mb-3 p-2 bg-slate-50 rounded-xl border border-slate-200 flex items-center gap-2">
          <input
            type="number"
            min={1}
            className="w-16 px-2 py-1 text-xs border border-slate-200 rounded-lg bg-white font-mono text-center focus:outline-none focus:border-[#0052CC]"
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
          />
          <button
            className="flex-1 py-1 px-3 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-colors shadow-2xs flex items-center justify-center gap-1 disabled:opacity-50"
            disabled={submitting}
            onClick={handleClickOffer}
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Đăng ký nhận</span>
          </button>
        </div>
      )}

      {/* Pending Approvals */}
      <div className="space-y-2.5 flex-1 min-h-[160px]">
        {designer.pending_approvals.length === 0 ? (
          <div className="h-full flex items-center justify-center p-6 border-2 border-dashed border-slate-100 rounded-xl text-center text-slate-400">
            <p className="text-xs font-medium">Kéo đơn vào đây để gán cho designer</p>
          </div>
        ) : (
          designer.pending_approvals.map((p) => (
            <div key={p.approval_id} className="rounded-xl border border-amber-200 bg-amber-50/60 p-3 shadow-2xs space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs font-bold text-amber-900">{p.order.external_order_id}</span>
                <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded">
                  Chờ Duyệt
                </span>
              </div>
              <p className="text-[11px] text-slate-500 font-mono">{p.order.sku ?? 'No SKU'}</p>
              <div className="flex items-center gap-2 pt-1 border-t border-amber-200/50">
                <button
                  className="flex-1 py-1 px-2 text-[11px] font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-md transition-colors flex items-center justify-center gap-1 shadow-2xs"
                  onClick={() => onDecide(p.approval_id, 'approve')}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>Duyệt</span>
                </button>
                <button
                  className="flex-1 py-1 px-2 text-[11px] font-semibold text-white bg-red-600 hover:bg-red-700 rounded-md transition-colors flex items-center justify-center gap-1 shadow-2xs"
                  onClick={() => {
                    const reason = window.prompt('Lý do huỷ phân bổ:')
                    if (reason) onDecide(p.approval_id, 'cancel', reason)
                  }}
                >
                  <XCircle className="h-3.5 w-3.5" />
                  <span>Hủy</span>
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export function AllocationBoardPage() {
  const [batchId, setBatchId] = useState('')
  const [board, setBoard] = useState<BoardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function loadBoard(id: string, clearError = true) {
    if (!id) return
    setLoading(true)
    try {
      const data = await apiFetch<BoardData>(`/allocation/board?batch_id=${encodeURIComponent(id)}`)
      setBoard(data)
      if (clearError) setError(null)
    } catch {
      setError('Không tải được bảng phân bổ — kiểm tra mã Batch ID.')
    } finally {
      setLoading(false)
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
      setError('Thao tác gán đơn thất bại. Có thể do đơn đã được gán hoặc bị khóa.')
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
      setError('Đăng ký nhận đơn thất bại — số lượng có thể vượt capacity cho phép.')
    }
  }

  async function handleDecide(approvalId: string, decision: 'approve' | 'cancel', reason?: string) {
    try {
      const result = await apiFetch<DecideResult>(`/approvals/${approvalId}/decide`, {
        method: 'POST',
        body: JSON.stringify({ decision, reason }),
      })
      if (!result.decided_by_me) {
        const decidedAt = new Intl.DateTimeFormat('vi-VN', {
          dateStyle: 'short', timeStyle: 'medium',
        }).format(new Date(result.decided_at))
        setError(`Đơn này đã được ${result.decided_by_name} xử lý lúc ${decidedAt}.`)
      }
      await loadBoard(batchId, result.decided_by_me)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Duyệt phân đơn thất bại.')
    }
  }

  return (
    <DashboardLayout>
      {/* Header Selector Bar */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <Kanban className="h-5 w-5 text-[#0052CC]" />
            <span>Bảng Phân Bổ Kéo-Thả (Allocation Board)</span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">Kéo thả các đơn từ kho chưa gán vào cột Designer để phê duyệt</p>
        </div>

        <div className="flex items-center gap-2">
          <input
            className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-mono font-medium focus:outline-none focus:border-[#0052CC] w-48"
            placeholder="Nhập Batch ID..."
            value={batchId}
            onChange={(e) => setBatchId(e.target.value)}
          />
          <button
            className="px-4 py-2 text-xs font-semibold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-lg transition-colors shadow-2xs flex items-center gap-1.5"
            onClick={() => loadBoard(batchId)}
            disabled={loading}
          >
            <Search className="h-3.5 w-3.5" />
            <span>{loading ? 'Đang tải...' : 'Tải Bảng'}</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-600" />
          <span>{error}</span>
        </div>
      )}

      {/* Board Layout with DnD Context */}
      {board ? (
        <DndContext onDragEnd={handleDragEnd}>
          <div className="flex gap-6 overflow-x-auto pb-4">
            {/* Unassigned Orders Store Column */}
            <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4 w-80 shrink-0 flex flex-col shadow-xs">
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-200">
                <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">Kho Đơn Chưa Gán</h3>
                <span className="font-mono text-xs font-bold px-2 py-0.5 rounded-full bg-blue-100 text-[#0052CC]">
                  {board.unassigned.length}
                </span>
              </div>
              <div className="space-y-2.5 flex-1 min-h-[300px]">
                {board.unassigned.length === 0 ? (
                  <div className="h-full flex items-center justify-center p-6 text-center text-slate-400">
                    <p className="text-xs font-medium">Không có đơn nào chưa gán trong Batch này</p>
                  </div>
                ) : (
                  board.unassigned.map((o) => (
                    <OrderCard key={o.id} order={o} />
                  ))
                )}
              </div>
            </div>

            {/* Designer Target Columns */}
            {board.designers.map((d) => (
              <DesignerColumn key={d.id} designer={d} onOffer={handleOffer} onDecide={handleDecide} />
            ))}
          </div>
        </DndContext>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center text-slate-400">
          <Kanban className="h-12 w-12 mx-auto mb-3 opacity-25 text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-700">Chưa tải dữ liệu phân bổ</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">Vui lòng nhập Batch ID ở thanh công cụ phía trên và bấm "Tải Bảng" để khởi chạy bảng kéo thả.</p>
        </div>
      )}
    </DashboardLayout>
  )
}
