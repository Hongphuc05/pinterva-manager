import { useState, useEffect } from 'react'
import { X, CheckCircle2, RotateCcw, AlertTriangle, Loader2 } from 'lucide-react'
import { apiFetch } from '../api/client'

interface AdminFixActionModalProps {
  isOpen: boolean
  mode: 'approve' | 'reject'
  orderId: string
  externalOrderId: string
  currentNote: string
  previousNote?: string | null
  onClose: () => void
  onSuccess: (updatedNote: string) => void
}

export function AdminFixActionModal({
  isOpen,
  mode,
  orderId,
  externalOrderId,
  currentNote,
  previousNote,
  onClose,
  onSuccess,
}: AdminFixActionModalProps) {
  const isApprove = mode === 'approve'
  const [noteText, setNoteText] = useState(currentNote || previousNote || '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setNoteText(currentNote || previousNote || '')
      setError(null)
    }
  }, [isOpen, mode, currentNote, previousNote])

  if (!isOpen) return null

  async function handleConfirm() {
    setLoading(true)
    setError(null)
    try {
      if (isApprove) {
        const res = await apiFetch<{ ok: boolean; note_outsource: string; message: string }>(
          `/orders/${orderId}/approve-fix`,
          {
            method: 'POST',
            body: JSON.stringify({ note_outsource: noteText.trim() }),
          }
        )
        onSuccess(res.note_outsource || noteText.trim())
      } else {
        const res = await apiFetch<{ ok: boolean; note_outsource: string; message: string }>(
          `/orders/${orderId}/reject-fix-to-review`,
          {
            method: 'POST',
            body: JSON.stringify({ note_outsource: noteText.trim() }),
          }
        )
        onSuccess(res.note_outsource || noteText.trim())
      }
      onClose()
    } catch (err: any) {
      setError(err?.message || 'Không thể thực hiện thao tác.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[999999] flex items-center justify-center bg-black/50 backdrop-blur-xs p-4 animate-in fade-in duration-150">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-lg overflow-hidden flex flex-col">
        {/* Header */}
        <div
          className={`px-5 py-4 flex items-center justify-between border-b ${
            isApprove ? 'bg-emerald-50/75 border-emerald-100' : 'bg-orange-50/75 border-orange-100'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <div
              className={`w-9 h-9 rounded-xl flex items-center justify-center ${
                isApprove ? 'bg-emerald-100 text-emerald-700' : 'bg-orange-100 text-orange-700'
              }`}
            >
              {isApprove ? <CheckCircle2 className="w-5 h-5" /> : <RotateCcw className="w-5 h-5" />}
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">
                {isApprove
                  ? `Check & Duyệt Đơn Fix (#${externalOrderId})`
                  : `Hủy Fix & Trả Về Review (#${externalOrderId})`}
              </h3>
              <p className="text-[11px] text-slate-500">
                {isApprove
                  ? 'Kiểm tra & chỉnh sửa Note outsource gửi cho Designer làm (Lưu ý: Không đẩy lên Printerval)'
                  : 'Chỉnh sửa Note outsource và cập nhật ngược lại lên Printerval cùng trạng thái Review'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 text-xs">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-xl text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-red-500" />
              <span>{error}</span>
            </div>
          )}

          {isApprove ? (
            <div className="p-3 bg-emerald-50/80 border border-emerald-200 text-emerald-950 rounded-xl space-y-1">
              <div className="font-bold flex items-center gap-1.5 text-xs text-emerald-900">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>Quy trình duyệt gửi Designer:</span>
              </div>
              <p className="text-[11px] text-emerald-800 leading-relaxed">
                Bạn có thể để nguyên Note từ Printerval hoặc chỉnh sửa thêm chỉ dẫn. Khi bấm <strong>Check & Duyệt</strong>, Note này sẽ hiển thị cho Designer xem tại Todo, <strong>tuyệt đối không đẩy ngược lại lên Printerval</strong>.
              </p>
            </div>
          ) : (
            <div className="p-3 bg-orange-50/80 border border-orange-200 text-orange-950 rounded-xl space-y-1">
              <div className="font-bold flex items-center gap-1.5 text-xs text-orange-900">
                <RotateCcw className="w-4 h-4 text-orange-600 shrink-0" />
                <span>Đồng bộ ngược lại Printerval:</span>
              </div>
              <p className="text-[11px] text-orange-800 leading-relaxed">
                Hệ thống sẽ <strong>ghi đè Note outsource này lên Printerval</strong> và tự động cập nhật trạng thái đơn hàng trên Printerval về <strong>Review (Chờ duyệt)</strong>.
              </p>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="font-semibold text-slate-800 block text-xs">
              {isApprove ? 'Nội dung Note outsource gửi cho Designer:' : 'Nội dung Note outsource gửi lên Printerval:'}
            </label>
            <textarea
              rows={6}
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Nhập nội dung note outsource, link drive, link ảnh mockup..."
              className="w-full p-3 text-xs border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#0052CC] font-mono leading-relaxed bg-white"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 bg-slate-50 border-t border-slate-100 flex items-center justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-200/60 rounded-xl transition-colors cursor-pointer"
          >
            Đóng
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={loading}
            className={`inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white rounded-xl shadow-xs transition-all cursor-pointer disabled:opacity-50 ${
              isApprove
                ? 'bg-emerald-600 hover:bg-emerald-700'
                : 'bg-orange-600 hover:bg-orange-700'
            }`}
          >
            {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            <span>
              {isApprove
                ? 'Check & Duyệt'
                : 'Gửi & Cập nhật Printerval'}
            </span>
          </button>
        </div>
      </div>
    </div>
  )
}
