import { useState, useEffect } from 'react'
import { X, CheckCircle2, RotateCcw, AlertTriangle, Loader2 } from 'lucide-react'
import { apiFetch } from '../api/client'
import { LinkifiedText } from './LinkifiedText'
import { FixTemplateQuestion, useFixTemplate } from './FixTemplateQuestion'

/** QC's messages of the order's latest Fix round, read from its chat (Admin only); null when there are none. */
export function useFixChat(orderId: string | null) {
  const [state, setState] = useState<{ text: string | null; loading: boolean }>({ text: null, loading: false })
  useEffect(() => {
    if (!orderId) return
    let alive = true
    setState({ text: null, loading: true })
    apiFetch<{ text: string | null }>(`/orders/${orderId}/fix-chat`)
      .then((data) => alive && setState({ text: data?.text ?? null, loading: false }))
      .catch(() => alive && setState({ text: null, loading: false }))
    return () => {
      alive = false
    }
  }, [orderId])
  return state
}

/** Read-only box showing that Fix text where the old "Note Outsource (QC)" field used to be. */
export function FixChatBox({ text, loading }: { text: string | null; loading: boolean }) {
  return (
    <div className="space-y-1.5">
      <label className="font-semibold text-slate-800 block text-xs flex items-center justify-between">
        <span>Nội dung Fix (khung chat)</span>
        <span className="text-[11px] font-normal text-slate-500">Chỉ Admin xem</span>
      </label>
      <div className="max-h-48 overflow-y-auto whitespace-pre-wrap break-all rounded-xl border border-amber-200 bg-amber-50/40 p-3 text-xs leading-relaxed text-slate-800">
        {loading ? (
          <span className="inline-flex items-center gap-1.5 text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Đang tải nội dung chat…</span>
        ) : text ? (
          <LinkifiedText text={text} />
        ) : (
          <span className="text-slate-500">Chưa có nội dung Fix trong khung chat — hãy nhập Ghi chú cho Designer.</span>
        )}
      </div>
    </div>
  )
}

interface AdminFixActionModalProps {
  isOpen: boolean
  mode: 'approve' | 'reject'
  orderId: string
  orderVersion?: number
  externalOrderId: string
  currentNote: string
  previousNote?: string | null
  currentDesignerNote?: string | null
  onClose: () => void
  onSuccess: (updatedNote: string) => void
}

export function AdminFixActionModal({
  isOpen,
  mode,
  orderId,
  orderVersion,
  externalOrderId,
  currentNote,
  previousNote,
  currentDesignerNote,
  onClose,
  onSuccess,
}: AdminFixActionModalProps) {
  const isApprove = mode === 'approve'
  const [adminNote, setAdminNote] = useState(currentDesignerNote || '')
  const [outsourceNote, setOutsourceNote] = useState(currentNote || previousNote || '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fixChat = useFixChat(isOpen && isApprove ? orderId : null)
  const template = useFixTemplate(isOpen && isApprove ? orderId : null)

  useEffect(() => {
    if (isOpen) {
      setAdminNote(currentDesignerNote || '')
      setOutsourceNote(currentNote || previousNote || '')
      setError(null)
    }
  }, [isOpen, mode, currentNote, previousNote, currentDesignerNote])

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  async function handleConfirm() {
    if (isApprove && !adminNote.trim() && !fixChat.text) {
      setError('Chưa có nội dung Fix từ khung chat, hãy nhập Ghi chú cho Designer.')
      return
    }
    if (isApprove && template.problem) {
      setError(template.problem)
      return
    }
    setLoading(true)
    setError(null)
    try {
      if (isApprove) {
        const res = await apiFetch<{ ok: boolean; note_outsource: string; message: string }>(
          `/orders/${orderId}/approve-fix`,
          {
            method: 'POST',
            body: JSON.stringify({
              designer_note: adminNote.trim(),
              ...template.payload(),
              ...(typeof orderVersion === 'number' ? { expected_version: orderVersion } : {}),
            }),
          }
        )
        onSuccess(res.note_outsource || '')
      } else {
        const res = await apiFetch<{ ok: boolean; note_outsource: string; message: string }>(
          `/orders/${orderId}/reject-fix-to-review`,
          {
            method: 'POST',
            body: JSON.stringify({
              note_outsource: outsourceNote.trim(),
              ...(typeof orderVersion === 'number' ? { expected_version: orderVersion } : {}),
            }),
          }
        )
        onSuccess(res.note_outsource || outsourceNote.trim())
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
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div
          className={`px-5 py-4 flex items-center justify-between border-b shrink-0 ${
            isApprove ? 'bg-emerald-50/75 border-emerald-100' : 'bg-orange-50/75 border-orange-100'
          }`}
        >
          <div className="flex items-center gap-2.5">
            <div
              className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
                isApprove ? 'bg-emerald-100 text-emerald-700' : 'bg-orange-100 text-orange-700'
              }`}
            >
              {isApprove ? <CheckCircle2 className="w-5 h-5" /> : <RotateCcw className="w-5 h-5" />}
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900">
                {isApprove
                  ? `Chấp Nhận Fix & Giao Designer (#${externalOrderId})`
                  : `Hủy Fix & Trả Về Review (#${externalOrderId})`}
              </h3>
              <p className="text-[11px] text-slate-500">
                {isApprove
                  ? 'Giao bài sửa cho Designer làm (Lưu ý: Không đẩy lên Print)'
                  : 'Chỉnh sửa Note outsource và cập nhật ngược lại lên Print cùng trạng thái Review'}
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
        <div className="p-5 space-y-4 text-xs overflow-y-auto">
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
                <span>Quy trình gửi bài sửa cho Designer:</span>
              </div>
              <p className="text-[11px] text-emerald-800 leading-relaxed">
                • Nếu có <strong>Ghi chú Admin</strong>, Designer chỉ nhận nội dung này.<br />
                • Nếu để trống Ghi chú Admin, Designer nhận nguyên văn nội dung Fix trong khung chat (không kèm link ảnh).
              </p>
            </div>
          ) : (
            <div className="p-3 bg-orange-50/80 border border-orange-200 text-orange-950 rounded-xl space-y-1">
              <div className="font-bold flex items-center gap-1.5 text-xs text-orange-900">
                <RotateCcw className="w-4 h-4 text-orange-600 shrink-0" />
                <span>Đồng bộ ngược lại Print:</span>
              </div>
              <p className="text-[11px] text-orange-800 leading-relaxed">
                Hệ thống sẽ <strong>ghi đè Note outsource này lên Print</strong> và tự động cập nhật trạng thái đơn hàng trên Print về <strong>Review (Chờ duyệt)</strong>.
              </p>
            </div>
          )}

          {isApprove && (
            <div className="space-y-1.5">
              <label className="font-semibold text-slate-800 block text-xs flex items-center justify-between">
                <span>Ghi chú của Admin cho Designer</span>
                <span className="text-[11px] font-normal text-slate-500">Ưu tiên gửi cho Des</span>
              </label>
              <textarea
                rows={3}
                value={adminNote}
                onChange={(e) => setAdminNote(e.target.value)}
                placeholder="Nhập hướng dẫn đã kiểm tra để gửi cho Des..."
                className="w-full p-3 text-xs border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#0052CC] font-mono leading-relaxed bg-white"
              />
            </div>
          )}

          {isApprove && <FixTemplateQuestion state={template} />}

          {isApprove ? <FixChatBox {...fixChat} /> : <div className="space-y-1.5">
            <label className="font-semibold text-slate-800 block text-xs flex items-center justify-between">
              <span>Nội dung Note outsource gửi lên Print:</span>
            </label>
            <textarea
              rows={6}
              value={outsourceNote}
              onChange={(e) => setOutsourceNote(e.target.value)}
              placeholder="Nhập nội dung note outsource, link drive, link ảnh mockup..."
              className="w-full p-3 text-xs border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#0052CC] font-mono leading-relaxed bg-white"
            />
          </div>}
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 bg-slate-50 border-t border-slate-100 flex items-center justify-end gap-2.5 shrink-0">
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
                ? 'Xác Nhận & Giao Des'
                : 'Gửi & Cập nhật Print'}
            </span>
          </button>
        </div>
      </div>
    </div>
  )
}
