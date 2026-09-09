import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Loader2, Check } from 'lucide-react'
import { apiFetch } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export type StatusOption = {
  key: string
  label: string
  badgeClass: string
  dotColor: string
  adminOnly?: boolean
  description: string
}

export const STATUS_OPTIONS: StatusOption[] = [
  {
    key: 'WAITING',
    label: 'Waiting',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-300',
    dotColor: 'bg-slate-400',
    description: 'Chờ Designer bắt đầu làm',
  },
  {
    key: 'IN_PROGRESS',
    label: 'Doing',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-300',
    dotColor: 'bg-blue-500',
    description: 'Đang làm thiết kế',
  },
  {
    key: 'QC_PENDING',
    label: 'Review',
    badgeClass: 'bg-purple-100 text-purple-800 border-purple-300',
    dotColor: 'bg-purple-500',
    description: 'Làm xong, gửi Admin duyệt',
  },
  {
    key: 'REVISION',
    label: 'Fix',
    badgeClass: 'bg-orange-100 text-orange-800 border-orange-300',
    dotColor: 'bg-orange-500',
    adminOnly: true,
    description: 'Bài chưa đạt, yêu cầu Des sửa lại',
  },
  {
    key: 'DONE',
    label: 'Done',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-300',
    dotColor: 'bg-emerald-500',
    adminOnly: true,
    description: 'Duyệt hoàn thành đơn hàng',
  },
]

type StatusDropdownProps = {
  orderId: string
  externalOrderId?: string
  currentState: string
  onStatusChanged?: (newState: string) => void
  disabled?: boolean
}

export function StatusDropdown({
  orderId,
  externalOrderId: _externalOrderId,
  currentState,
  onStatusChanged,
  disabled = false,
}: StatusDropdownProps) {
  const { user } = useAuth()
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [localState, setLocalState] = useState(currentState)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setLocalState(currentState)
  }, [currentState])

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  const isAdmin = user?.role === 'admin'

  // Determine current option display
  const normalizedState = localState.toUpperCase()
  let currentOpt = STATUS_OPTIONS.find((opt) => {
    if (opt.key === normalizedState) return true
    if (opt.key === 'WAITING' && (normalizedState === 'ASSIGNED' || normalizedState === 'WAITING')) return true
    if (opt.key === 'IN_PROGRESS' && (normalizedState === 'DOING' || normalizedState === 'IN_PROGRESS')) return true
    if (opt.key === 'QC_PENDING' && (normalizedState === 'REVIEW' || normalizedState === 'RESULT_SUBMITTED' || normalizedState === 'SUBMITTING_TO_SITE')) return true
    if (opt.key === 'REVISION' && (normalizedState === 'FIX' || normalizedState === 'REVISION_REQUESTED')) return true
    if (opt.key === 'DONE' && (normalizedState === 'SKIPPED' || normalizedState === 'DONE')) return true
    return false
  })

  // Fallback for OPEN or other states
  const displayLabel = currentOpt ? currentOpt.label : normalizedState === 'OPEN' ? 'Chờ phân công' : localState
  const displayBadgeClass = currentOpt
    ? currentOpt.badgeClass
    : normalizedState === 'OPEN'
    ? 'bg-amber-100 text-amber-800 border-amber-300'
    : 'bg-slate-100 text-slate-700 border-slate-300'

  async function handleSelect(opt: StatusOption) {
    if (disabled || loading) return
    if (!isAdmin && opt.adminOnly) return

    setLoading(true)
    setIsOpen(false)
    const oldState = localState

    // Optimistic UI update
    setLocalState(opt.key)
    try {
      await apiFetch<{ ok: boolean; state: string }>(`/orders/${orderId}/state`, {
        method: 'PATCH',
        body: JSON.stringify({ state: opt.key }),
      })
      onStatusChanged?.(opt.key)
      window.dispatchEvent(new CustomEvent('orders-updated'))
    } catch (err: any) {
      setLocalState(oldState)
      alert(err.message || 'Không thể đổi trạng thái đơn hàng.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      <button
        type="button"
        disabled={disabled || loading}
        onClick={(e) => {
          e.stopPropagation()
          setIsOpen(!isOpen)
        }}
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold rounded-lg border transition-all cursor-pointer shadow-2xs select-none hover:shadow-xs hover:scale-102 ${displayBadgeClass} ${
          disabled || loading ? 'opacity-70 cursor-not-allowed' : ''
        }`}
        title="Click để đổi trạng thái đơn hàng"
      >
        {loading ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <span className="truncate">{displayLabel}</span>
        )}
        <ChevronDown className={`h-3 w-3 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div
          className="absolute left-0 top-full mt-1.5 w-52 rounded-xl bg-white p-1.5 shadow-xl border border-slate-200 z-50 animate-in fade-in zoom-in-95 duration-150 text-xs"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-2.5 py-1.5 border-b border-slate-100 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
            {isAdmin ? 'Đổi trạng thái (Admin)' : 'Đổi trạng thái (Designer)'}
          </div>

          <div className="space-y-0.5 py-1">
            {STATUS_OPTIONS.map((opt) => {
              const isSelected =
                opt.key === normalizedState ||
                (opt.key === 'IN_PROGRESS' && normalizedState === 'ASSIGNED') ||
                (opt.key === 'QC_PENDING' && (normalizedState === 'RESULT_SUBMITTED' || normalizedState === 'SUBMITTING_TO_SITE')) ||
                (opt.key === 'REVISION' && normalizedState === 'REVISION_REQUESTED') ||
                (opt.key === 'DONE' && normalizedState === 'SKIPPED')

              const isLocked = !isAdmin && opt.adminOnly

              return (
                <button
                  key={opt.key}
                  type="button"
                  disabled={isLocked || loading}
                  onClick={() => handleSelect(opt)}
                  className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg text-left transition-colors ${
                    isLocked
                      ? 'opacity-40 cursor-not-allowed bg-slate-50'
                      : isSelected
                      ? 'bg-blue-50 font-bold text-slate-900'
                      : 'hover:bg-slate-100 text-slate-700 cursor-pointer'
                  }`}
                  title={isLocked ? 'Chỉ Admin mới có quyền duyệt trạng thái này' : opt.description}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`h-2 w-2 rounded-full shrink-0 ${opt.dotColor}`} />
                    <div className="truncate">
                      <div className="font-semibold text-xs leading-none">{opt.label}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5 truncate">{opt.description}</div>
                    </div>
                  </div>

                  <div className="shrink-0 flex items-center gap-1 pl-1">
                    {isLocked && (
                      <span className="text-[9px] font-bold uppercase tracking-wider text-slate-400 bg-slate-200/80 px-1 py-0.5 rounded">
                        Chỉ Admin
                      </span>
                    )}
                    {isSelected && <Check className="h-3.5 w-3.5 text-[#0052CC]" />}
                  </div>
                </button>
              )
            })}
          </div>

          {!isAdmin && (
            <div className="px-2.5 py-1.5 border-t border-slate-100 bg-slate-50/80 rounded-b-lg text-[10px] text-slate-500">
              💡 Des chỉ được chuyển <strong className="text-blue-600">Doing</strong> hoặc <strong className="text-purple-600">Review</strong>.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
