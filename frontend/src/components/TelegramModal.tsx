import { useState, useEffect } from 'react'
import { apiFetch } from '../api/client'
import { Send, CheckCircle2, AlertCircle, Copy, Check, ExternalLink, RefreshCw, Unlink } from 'lucide-react'
import { useToast } from '../context/ToastContext'

interface TelegramModalProps {
  isOpen: boolean
  onClose: () => void
}

interface TelegramStatus {
  is_configured: boolean
  bot_username: string | null
  is_linked: boolean
  telegram_chat_id: string | null
  telegram_username: string | null
  notifications_enabled: boolean
}

interface LinkCodeData {
  ok: boolean
  code: string
  link_url: string | null
  bot_username: string | null
  expires_in_seconds: number
  is_linked: boolean
}

export function TelegramModal({ isOpen, onClose }: TelegramModalProps) {
  const [status, setStatus] = useState<TelegramStatus | null>(null)
  const [linkData, setLinkData] = useState<LinkCodeData | null>(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const { showToast } = useToast()

  useEffect(() => {
    if (isOpen) {
      loadStatus()
    }
  }, [isOpen])

  async function loadStatus() {
    setLoading(true)
    try {
      const res = await apiFetch<TelegramStatus>('/telegram/status')
      setStatus(res)
    } catch (err: any) {
      showToast(err?.message || 'Không thể tải trạng thái Telegram', 'error')
    } finally {
      setLoading(false)
    }
  }

  async function generateLink() {
    setLoading(true)
    try {
      const res = await apiFetch<LinkCodeData>('/telegram/link-code', { method: 'POST' })
      setLinkData(res)
    } catch (err: any) {
      showToast(err?.message || 'Không thể tạo mã liên kết', 'error')
    } finally {
      setLoading(false)
    }
  }

  async function handleUnlink() {
    if (!confirm('Bạn có chắc chắn muốn hủy liên kết tài khoản Telegram này không?')) return
    setLoading(true)
    try {
      await apiFetch('/telegram/unlink', { method: 'POST' })
      showToast('Đã hủy liên kết Telegram thành công', 'success')
      setLinkData(null)
      loadStatus()
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi hủy liên kết', 'error')
    } finally {
      setLoading(false)
    }
  }

  function copyLink() {
    if (!linkData?.link_url) return
    navigator.clipboard.writeText(linkData.link_url)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
    showToast('Đã sao chép link liên kết!', 'success')
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b pb-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500 text-white shadow-md shadow-sky-500/20">
              <Send className="h-5 w-5 -translate-x-0.5 translate-y-0.5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-800">Kết Nối Telegram Bot</h3>
              <p className="text-xs text-slate-500">Nhận thông báo đơn mới, fix gấp & thanh toán</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="mt-5 space-y-4">
          {loading && !status ? (
            <div className="flex items-center justify-center py-8 text-slate-500">
              <RefreshCw className="h-5 w-5 animate-spin mr-2" /> Đang kiểm tra...
            </div>
          ) : status?.is_linked ? (
            /* Already Linked */
            <div className="space-y-4">
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-4">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="h-6 w-6 text-emerald-600" />
                  <div>
                    <h4 className="text-sm font-bold text-emerald-800">Đã kết nối Telegram thành công</h4>
                    <p className="text-xs text-emerald-700">
                      Chat ID: <code className="font-mono">{status.telegram_chat_id}</code>
                      {status.telegram_username ? ` (@${status.telegram_username})` : ''}
                    </p>
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-xs text-slate-600 space-y-1.5">
                <p className="font-semibold text-slate-700">Các thông báo tự động được kích hoạt:</p>
                <p className="flex items-center gap-1.5">✓ Nhận tin nhắn ngay khi có đơn mới vào tab Doing</p>
                <p className="flex items-center gap-1.5">✓ Nhận cảnh báo đơn cần sửa gấp (Fix) kèm hướng dẫn</p>
                <p className="flex items-center gap-1.5">✓ Nhận thông báo khi Admin thanh toán tiền công</p>
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={handleUnlink}
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-red-200 bg-red-50 py-2.5 text-xs font-semibold text-red-600 hover:bg-red-100 transition"
                >
                  <Unlink className="h-4 w-4" /> Hủy liên kết Telegram
                </button>
              </div>
            </div>
          ) : (
            /* Not Linked */
            <div className="space-y-4">
              <div className="rounded-xl border border-sky-100 bg-sky-50/60 p-4 text-xs text-sky-800 space-y-1">
                <p className="font-bold flex items-center gap-1.5">
                  <AlertCircle className="h-4 w-4 text-sky-600" /> Tiện ích thông báo tự động
                </p>
                <p>
                  Kết nối với Telegram Bot để điện thoại của bạn tự động rung chuông báo khi có đơn mới, không lo bị trôi đơn!
                </p>
              </div>

              {!linkData ? (
                <button
                  type="button"
                  onClick={generateLink}
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-sky-500 py-3 text-sm font-bold text-white shadow-lg shadow-sky-500/25 hover:bg-sky-600 transition"
                >
                  <Send className="h-4 w-4" /> Tạo mã liên kết Telegram
                </button>
              ) : (
                <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-semibold text-slate-700">
                    Bước tiếp theo: Bấm nút bên dưới để mở Telegram và bấm <span className="text-sky-600 font-bold">Start</span>
                  </p>

                  {linkData.link_url && (
                    <a
                      href={linkData.link_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-sky-500 py-2.5 text-xs font-bold text-white shadow-md hover:bg-sky-600 transition"
                    >
                      <ExternalLink className="h-4 w-4" /> Mở Bot Telegram ngay
                    </a>
                  )}

                  <div className="flex items-center gap-2 pt-1">
                    <input
                      type="text"
                      readOnly
                      value={linkData.link_url || `Code: ${linkData.code}`}
                      className="w-full rounded-lg border bg-white px-2.5 py-1.5 text-xs text-slate-600 font-mono"
                    />
                    <button
                      type="button"
                      onClick={copyLink}
                      className="rounded-lg border bg-white p-2 text-slate-600 hover:bg-slate-100"
                      title="Sao chép link"
                    >
                      {copied ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
                    </button>
                  </div>

                  <p className="text-[11px] text-slate-400 text-center">
                    Mã liên kết có hiệu lực trong 15 phút. Sau khi bấm Start trên Telegram, quay lại đây bấm Tải lại.
                  </p>

                  <button
                    type="button"
                    onClick={loadStatus}
                    className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> Kiểm tra trạng thái kết nối
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mt-6 flex justify-end border-t pt-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  )
}
