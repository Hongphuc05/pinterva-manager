import { useCallback, useEffect, useState, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, GripVertical, Layers3, Package, RefreshCw, UserRound } from 'lucide-react'
import { ApiError, apiFetch, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'

type DuplicateCard = {
  id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  deadline_at_ext: string | null
  state: string
  assignee_id: string | null
  assignee_name: string | null
}

type DuplicateColumn = {
  id: string
  title: string
  cards: DuplicateCard[]
}

function stateLabel(state: string) {
  const labels: Record<string, string> = {
    OPEN: 'Chờ xử lý',
    WAITING: 'Waiting',
    IN_PROGRESS: 'Doing',
    QC_PENDING: 'Review',
    REVISION: 'Fix',
    DONE: 'Done',
    CANCELLED: 'Đã hủy',
  }
  return labels[state] || state
}

function stateClass(state: string) {
  if (state === 'DONE') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (state === 'REVISION') return 'bg-orange-50 text-orange-700 border-orange-200'
  if (state === 'QC_PENDING') return 'bg-violet-50 text-violet-700 border-violet-200'
  if (state === 'IN_PROGRESS') return 'bg-blue-50 text-blue-700 border-blue-200'
  return 'bg-slate-100 text-slate-600 border-slate-200'
}

export function DuplicateBoardPage() {
  const { user } = useAuth()
  const [columns, setColumns] = useState<DuplicateColumn[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draggedCard, setDraggedCard] = useState<DuplicateCard | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [movingCardId, setMovingCardId] = useState<string | null>(null)

  const isAdmin = user?.role === 'admin'

  const loadBoard = useCallback(async () => {
    setLoading(true)
    try {
      const result = await apiFetch<{ columns: DuplicateColumn[] }>('/duplicate-board')
      setColumns(result.columns)
      setError(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể tải board Đơn trùng lặp.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadBoard()
  }, [loadBoard])

  function canDropTo(column: DuplicateColumn) {
    if (!draggedCard || movingCardId) return false
    if (isAdmin) return true
    if (column.id === user?.id) return true
    return column.id === 'unassigned' && draggedCard.assignee_id === user?.id
  }

  function onDragStart(event: DragEvent<HTMLDivElement>, card: DuplicateCard) {
    setDraggedCard(card)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', card.id)
  }

  function onDragEnd() {
    setDraggedCard(null)
    setDropTarget(null)
  }

  async function onDrop(event: DragEvent<HTMLElement>, column: DuplicateColumn) {
    event.preventDefault()
    if (!draggedCard || !canDropTo(column)) return
    if (column.id === draggedCard.assignee_id || (column.id === 'unassigned' && !draggedCard.assignee_id)) {
      onDragEnd()
      return
    }

    setMovingCardId(draggedCard.id)
    try {
      await apiFetch('/duplicate-board/move', {
        method: 'POST',
        body: JSON.stringify({
          order_id: draggedCard.id,
          target_designer_id: column.id === 'unassigned' ? null : column.id,
        }),
      })
      await loadBoard()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể di chuyển thẻ.')
    } finally {
      setMovingCardId(null)
      onDragEnd()
    }
  }

  return (
    <DashboardLayout>
      <section className="-m-6 min-h-[calc(100vh-4rem)] bg-[#f1f2f4] p-6 lg:-m-8 lg:p-8">
        <header className="mb-6 flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-xs md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-bold text-slate-800">
              <Layers3 className="h-5 w-5 text-violet-600" />
              Board Đơn trùng lặp
            </h1>
            <p className="mt-1 text-xs text-slate-500">
              Kéo thẻ từ <strong>Thiếu form</strong> vào cột của mày để nhận xử lý.
              {isAdmin ? ' Admin có thể phân lại giữa mọi cột.' : ' Mày chỉ có thể nhận hoặc trả đơn của chính mình.'}
            </p>
          </div>
          <button
            type="button"
            onClick={loadBoard}
            disabled={loading || movingCardId !== null}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700 shadow-xs hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Làm mới board
          </button>
        </header>

        {error && (
          <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-700">
            <span className="flex items-center gap-2"><AlertCircle className="h-4 w-4" />{error}</span>
            <button type="button" onClick={() => setError(null)} className="font-bold">Đóng</button>
          </div>
        )}

        {loading && columns.length === 0 ? (
          <div className="flex gap-4 overflow-hidden">
            {[1, 2, 3].map((item) => <div key={item} className="h-96 w-80 shrink-0 animate-pulse rounded-xl bg-slate-200" />)}
          </div>
        ) : (
          <div className="flex min-h-[calc(100vh-15rem)] gap-4 overflow-x-auto pb-5">
            {columns.map((column) => {
              const canDrop = canDropTo(column)
              return (
                <section
                  key={column.id}
                  onDragOver={(event) => {
                    if (canDrop) {
                      event.preventDefault()
                      event.dataTransfer.dropEffect = 'move'
                      setDropTarget(column.id)
                    }
                  }}
                  onDragLeave={() => setDropTarget((current) => current === column.id ? null : current)}
                  onDrop={(event) => onDrop(event, column)}
                  className={`flex w-80 shrink-0 flex-col rounded-xl border p-3 transition-colors ${
                    dropTarget === column.id && canDrop
                      ? 'border-violet-400 bg-violet-100 ring-2 ring-violet-300/60'
                      : 'border-slate-200 bg-slate-200/80'
                  }`}
                >
                  <div className="mb-3 flex items-center justify-between gap-2 px-1">
                    <h2 className="truncate text-sm font-bold text-slate-700">{column.title}</h2>
                    <span className="rounded-full bg-white px-2 py-0.5 font-mono text-[11px] font-bold text-slate-500 shadow-xs">
                      {column.cards.length}
                    </span>
                  </div>
                  <div className="min-h-28 space-y-2">
                    {column.cards.map((card) => (
                      <div
                        key={card.id}
                        draggable={!movingCardId}
                        onDragStart={(event) => onDragStart(event, card)}
                        onDragEnd={onDragEnd}
                        className={`group rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition-shadow hover:shadow-md ${
                          draggedCard?.id === card.id ? 'opacity-45' : ''
                        } ${movingCardId === card.id ? 'pointer-events-none opacity-60' : 'cursor-grab active:cursor-grabbing'}`}
                      >
                        <div className="flex gap-2.5">
                          <GripVertical className="mt-0.5 h-4 w-3 shrink-0 text-slate-300 group-hover:text-slate-500" />
                          {card.thumbnail_url ? (
                            <img src={resolveAssetUrl(card.thumbnail_url)} alt="" className="h-11 w-11 rounded-md border border-slate-200 object-cover" />
                          ) : (
                            <div className="flex h-11 w-11 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-400">
                              <Package className="h-5 w-5" />
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <Link to={`/orders/${card.id}`} draggable={false} className="block truncate font-mono text-xs font-bold text-[#0052CC] hover:underline">
                              {card.external_order_id}
                            </Link>
                            <p className="mt-0.5 line-clamp-2 text-[11px] font-medium leading-relaxed text-slate-600">
                              {card.product_name || 'Đơn chưa có tên sản phẩm'}
                            </p>
                          </div>
                        </div>
                        <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-100 pt-2">
                          <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${stateClass(card.state)}`}>
                            {stateLabel(card.state)}
                          </span>
                          {card.deadline_at_ext && <span className="text-[10px] font-medium text-slate-400">{new Date(card.deadline_at_ext).toLocaleDateString('vi-VN')}</span>}
                        </div>
                      </div>
                    ))}
                    {column.cards.length === 0 && (
                      <div className={`rounded-lg border border-dashed p-5 text-center text-xs ${dropTarget === column.id ? 'border-violet-400 text-violet-700' : 'border-slate-300 text-slate-400'}`}>
                        <UserRound className="mx-auto mb-1 h-4 w-4 opacity-60" />
                        {column.id === 'unassigned' ? 'Chưa có đơn thiếu form' : 'Kéo đơn vào đây'}
                      </div>
                    )}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </section>
    </DashboardLayout>
  )
}
