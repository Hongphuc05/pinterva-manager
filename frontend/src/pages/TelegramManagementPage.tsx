import { useEffect, useMemo, useState } from 'react'
import { DashboardLayout } from '../components/DashboardLayout'
import { apiFetch, ApiError } from '../api/client'
import { useToast } from '../context/ToastContext'
import {
  AlertCircle,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  Loader2,
  MessageCircle,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  Settings2,
  Trash2,
  Users,
  XCircle,
} from 'lucide-react'

type DeliveryMode = 'private' | 'group'

type TelegramDesigner = {
  id: string
  username: string
  full_name: string
  role: string
  active: boolean
  private_chat_id: string | null
  private_username: string | null
  private_connected: boolean
  group_chat_id: string | null
  group_title: string | null
  group_type: string | null
  group_configured: boolean
  group_verified: boolean
  group_verified_at: string | null
  group_last_error: string | null
  delivery_mode: DeliveryMode
  selected_chat_id: string | null
  notifications_enabled: boolean
}

type TelegramOverview = {
  is_configured: boolean
  bot_username: string | null
  platform_id: string
  designer_count: number
  private_connected_count: number
  group_configured_count: number
  group_verified_count: number
  designers: TelegramDesigner[]
}

type TelegramTemplate = {
  template_key: string
  audience: 'designer' | 'admin'
  body: string
  active: boolean
  version: number
  updated_by_id: string | null
  updated_at: string | null
  placeholders: string[]
}

const templateLabels: Record<string, string> = {
  designer_new_order: 'Des — Đơn mới',
  designer_urgent_fix: 'Des — Đơn cần Fix',
  designer_payment: 'Des — Thanh toán',
  admin_new_fix: 'Admin — Fix mới',
  admin_review_submitted: 'Admin — Des nộp Review',
  admin_missing_template: 'Admin — Báo thiếu temp',
  admin_excessive_fix: 'Admin — QC Alert nhiều Fix',
  admin_deadline_overdue: 'Admin — Des quá hạn',
  admin_system_alert: 'Admin — Cảnh báo hệ thống',
}

const roleLabels: Record<string, string> = {
  designer: 'Designer',
  'designer-trello': 'Designer Trello',
}

export function TelegramManagementPage() {
  const [overview, setOverview] = useState<TelegramOverview | null>(null)
  const [templates, setTemplates] = useState<TelegramTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [groupDrafts, setGroupDrafts] = useState<Record<string, string>>({})
  const [busyDesigner, setBusyDesigner] = useState<Record<string, string>>({})
  const [selectedTemplateKey, setSelectedTemplateKey] = useState('')
  const [templateDraft, setTemplateDraft] = useState('')
  const [templatePreview, setTemplatePreview] = useState('')
  const [savingTemplate, setSavingTemplate] = useState(false)
  const [previewingTemplate, setPreviewingTemplate] = useState(false)
  const { showToast } = useToast()

  const selectedTemplate = templates.find((template) => template.template_key === selectedTemplateKey) || null

  useEffect(() => {
    void loadData()
  }, [])

  useEffect(() => {
    if (!selectedTemplate) return
    setTemplateDraft(selectedTemplate.body)
    setTemplatePreview('')
  }, [selectedTemplate])

  async function loadData() {
    setLoading(true)
    setError('')
    try {
      const [overviewData, templateData] = await Promise.all([
        apiFetch<TelegramOverview>('/telegram/admin/overview'),
        apiFetch<TelegramTemplate[]>('/telegram/admin/templates'),
      ])
      setOverview(overviewData)
      setTemplates(templateData)
      setGroupDrafts(Object.fromEntries(overviewData.designers.map((designer) => [designer.id, designer.group_chat_id || ''])))
      setSelectedTemplateKey((current) => current || templateData[0]?.template_key || '')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể tải quản lý bot Telegram.')
    } finally {
      setLoading(false)
    }
  }

  function replaceDesigner(updated: TelegramDesigner) {
    setOverview((current) => {
      if (!current) return current
      const designers = current.designers.map((designer) => designer.id === updated.id ? updated : designer)
      return {
        ...current,
        designers,
        private_connected_count: designers.filter((designer) => designer.private_connected).length,
        group_configured_count: designers.filter((designer) => designer.group_configured).length,
        group_verified_count: designers.filter((designer) => designer.group_verified).length,
      }
    })
    setGroupDrafts((current) => ({ ...current, [updated.id]: updated.group_chat_id || '' }))
  }

  function setBusy(id: string, action: string | null) {
    setBusyDesigner((current) => {
      const next = { ...current }
      if (action) next[id] = action
      else delete next[id]
      return next
    })
  }

  async function saveGroup(designer: TelegramDesigner) {
    const groupChatId = (groupDrafts[designer.id] || '').trim()
    if (!groupChatId) {
      showToast('Hãy nhập group chat ID trước.', 'warning')
      return
    }
    setBusy(designer.id, 'save')
    try {
      const updated = await apiFetch<TelegramDesigner>(`/telegram/admin/designers/${designer.id}/group`, {
        method: 'PUT',
        body: JSON.stringify({ group_chat_id: groupChatId }),
      })
      replaceDesigner(updated)
      showToast(`Đã lưu group cho ${designer.full_name}. Hãy bấm kiểm tra group.`, 'success')
    } catch (caught) {
      showToast(caught instanceof ApiError ? caught.message : 'Không thể lưu group chat.', 'error')
    } finally {
      setBusy(designer.id, null)
    }
  }

  async function verifyGroup(designer: TelegramDesigner) {
    setBusy(designer.id, 'verify')
    try {
      const updated = await apiFetch<TelegramDesigner>(`/telegram/admin/designers/${designer.id}/group/verify`, { method: 'POST' })
      replaceDesigner(updated)
      showToast(`Đã xác thực group ${updated.group_title || updated.group_chat_id}.`, 'success')
    } catch (caught) {
      showToast(caught instanceof ApiError ? caught.message : 'Không thể xác thực group.', 'error')
      await loadData()
    } finally {
      setBusy(designer.id, null)
    }
  }

  async function clearGroup(designer: TelegramDesigner) {
    if (!window.confirm(`Xóa group chat của ${designer.full_name}? Nếu đang dùng mode Group, hệ thống sẽ chuyển về Chat riêng.`)) return
    setBusy(designer.id, 'clear')
    try {
      const updated = await apiFetch<TelegramDesigner>(`/telegram/admin/designers/${designer.id}/group`, { method: 'DELETE' })
      replaceDesigner(updated)
      showToast('Đã xóa mapping group.', 'success')
    } catch (caught) {
      showToast(caught instanceof ApiError ? caught.message : 'Không thể xóa mapping group.', 'error')
    } finally {
      setBusy(designer.id, null)
    }
  }

  async function changeMode(designer: TelegramDesigner, mode: DeliveryMode) {
    if (mode === designer.delivery_mode) return
    setBusy(designer.id, 'mode')
    try {
      const updated = await apiFetch<TelegramDesigner>(`/telegram/admin/designers/${designer.id}/delivery-mode`, {
        method: 'PATCH',
        body: JSON.stringify({ mode }),
      })
      replaceDesigner(updated)
      showToast(`Bot sẽ gửi cho ${designer.full_name} qua ${mode === 'group' ? 'group' : 'chat riêng'}.`, 'success')
    } catch (caught) {
      showToast(caught instanceof ApiError ? caught.message : 'Không thể đổi kiểu gửi.', 'error')
    } finally {
      setBusy(designer.id, null)
    }
  }

  async function sendTest(designer: TelegramDesigner) {
    setBusy(designer.id, 'test')
    try {
      await apiFetch(`/telegram/admin/designers/${designer.id}/test`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      showToast('Đã gửi tin nhắn test.', 'success')
    } catch (caught) {
      showToast(caught instanceof ApiError ? caught.message : 'Không thể gửi tin nhắn test.', 'error')
    } finally {
      setBusy(designer.id, null)
    }
  }

  async function previewTemplate() {
    if (!selectedTemplate) return
    setPreviewingTemplate(true)
    try {
      const result = await apiFetch<{ rendered: string }>(`/telegram/admin/templates/${selectedTemplate.template_key}/preview`, {
        method: 'POST',
        body: JSON.stringify({ body: templateDraft }),
      })
      setTemplatePreview(result.rendered)
    } catch (caught) {
      showToast(caught instanceof ApiError ? caught.message : 'Không thể xem preview template.', 'error')
    } finally {
      setPreviewingTemplate(false)
    }
  }

  async function saveTemplate() {
    if (!selectedTemplate) return
    setSavingTemplate(true)
    try {
      const updated = await apiFetch<TelegramTemplate>(`/telegram/admin/templates/${selectedTemplate.template_key}`, {
        method: 'PUT',
        body: JSON.stringify({ body: templateDraft }),
      })
      setTemplates((current) => current.map((template) => template.template_key === updated.template_key ? updated : template))
      showToast('Đã lưu mẫu tin nhắn Telegram.', 'success')
      await previewTemplate()
    } catch (caught) {
      showToast(caught instanceof ApiError ? caught.message : 'Không thể lưu mẫu tin nhắn.', 'error')
    } finally {
      setSavingTemplate(false)
    }
  }

  async function resetTemplate() {
    if (!selectedTemplate) return
    if (!window.confirm(`Khôi phục mẫu "${templateLabels[selectedTemplate.template_key] || selectedTemplate.template_key}" về mặc định?`)) return
    setSavingTemplate(true)
    try {
      const updated = await apiFetch<TelegramTemplate>(`/telegram/admin/templates/${selectedTemplate.template_key}/reset`, {
        method: 'POST',
      })
      setTemplates((current) => current.map((template) => template.template_key === updated.template_key ? updated : template))
      setTemplateDraft(updated.body)
      setTemplatePreview('')
      showToast('Đã khôi phục mẫu mặc định.', 'success')
    } catch (caught) {
      showToast(caught instanceof ApiError ? caught.message : 'Không thể khôi phục mẫu mặc định.', 'error')
    } finally {
      setSavingTemplate(false)
    }
  }

  const visibleDesigners = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!overview) return []
    if (!term) return overview.designers
    return overview.designers.filter((designer) =>
      `${designer.full_name} ${designer.username} ${designer.group_chat_id || ''} ${designer.group_title || ''}`.toLowerCase().includes(term),
    )
  }, [overview, search])

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex flex-col justify-between gap-4 border-b border-slate-200 pb-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-bold text-slate-900">
              <Bot className="h-6 w-6 text-[#0052CC]" />
              Quản Lý Bot Telegram
            </h1>
            <p className="mt-1 text-xs text-slate-500">Quản lý kết nối des-mana, đích gửi và nội dung thông báo cho từng Acc Mẹ.</p>
          </div>
          <button type="button" onClick={() => void loadData()} disabled={loading} className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 shadow-2xs hover:bg-slate-50 disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Tải lại
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-xs font-semibold text-red-800">
            <AlertCircle className="h-4 w-4 shrink-0" /> {error}
          </div>
        )}

        {loading && !overview ? (
          <div className="rounded-2xl border border-slate-200 bg-white py-20 text-center text-slate-400">
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-[#0052CC]" />
            <p className="mt-3 text-xs font-medium">Đang tải cấu hình bot...</p>
          </div>
        ) : overview ? (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
              <StatusCard icon={Bot} label="Bot" value={overview.is_configured ? `@${overview.bot_username || 'đã cấu hình'}` : 'Chưa cấu hình'} tone={overview.is_configured ? 'green' : 'amber'} />
              <StatusCard icon={Users} label="Tổng designer" value={String(overview.designer_count)} />
              <StatusCard icon={MessageCircle} label="Đã nối chat riêng" value={String(overview.private_connected_count)} />
              <StatusCard icon={Users} label="Đã gắn group" value={String(overview.group_configured_count)} />
              <StatusCard icon={CheckCircle2} label="Group đã xác thực" value={String(overview.group_verified_count)} tone="green" />
            </div>

            <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xs">
              <div className="flex flex-col gap-3 border-b border-slate-100 p-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="flex items-center gap-2 text-sm font-bold text-slate-800"><Settings2 className="h-4 w-4 text-[#0052CC]" /> Đích gửi theo Designer</h2>
                  <p className="mt-1 text-xs text-slate-500">Group chỉ được chọn sau khi bot đã được thêm vào group và xác thực thành công.</p>
                </div>
                <div className="relative w-full sm:w-72">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm tên, username, group..." className="w-full rounded-xl border border-slate-200 py-2.5 pl-9 pr-3 text-xs outline-none focus:border-[#0052CC]" />
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1120px] text-left text-xs">
                  <thead className="border-b border-slate-200 bg-slate-50 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Designer</th>
                      <th className="px-4 py-3">Chat riêng</th>
                      <th className="px-4 py-3">Group chat ID</th>
                      <th className="px-4 py-3">Đích đang chọn</th>
                      <th className="px-4 py-3">Test</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visibleDesigners.map((designer) => {
                      const busy = busyDesigner[designer.id]
                      const groupDraft = groupDrafts[designer.id] ?? ''
                      return (
                        <tr key={designer.id} className="align-top hover:bg-slate-50/60">
                          <td className="px-4 py-4">
                            <p className="font-bold text-slate-800">{designer.full_name}</p>
                            <p className="mt-1 font-mono text-[10px] text-slate-400">@{designer.username} · {roleLabels[designer.role] || designer.role}</p>
                            {!designer.active && <span className="mt-1 inline-flex rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">Đã khóa</span>}
                          </td>
                          <td className="px-4 py-4">
                            {designer.private_connected ? (
                              <div className="space-y-1">
                                <span className="inline-flex items-center gap-1 rounded-lg bg-emerald-50 px-2 py-1 font-semibold text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> Đã kết nối</span>
                                <p className="font-mono text-[10px] text-slate-500">{designer.private_chat_id}{designer.private_username ? ` · @${designer.private_username}` : ''}</p>
                              </div>
                            ) : <span className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2 py-1 font-semibold text-slate-500"><XCircle className="h-3.5 w-3.5" /> Chưa kết nối</span>}
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex max-w-[320px] items-center gap-2">
                              <input value={groupDraft} onChange={(event) => setGroupDrafts((current) => ({ ...current, [designer.id]: event.target.value }))} placeholder="Ví dụ: -1001234567890" className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2.5 py-2 font-mono text-[11px] outline-none focus:border-[#0052CC]" />
                              <button type="button" onClick={() => void saveGroup(designer)} disabled={Boolean(busy)} className="rounded-lg bg-[#0052CC] p-2 text-white hover:bg-[#0041A3] disabled:opacity-50" title="Lưu group ID"><Save className="h-3.5 w-3.5" /></button>
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                              {designer.group_verified ? <span className="inline-flex items-center gap-1 rounded-lg bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-700"><Check className="h-3 w-3" /> {designer.group_title || 'Đã xác thực'}</span> : designer.group_configured ? <span className="inline-flex items-center gap-1 rounded-lg bg-amber-50 px-2 py-1 text-[10px] font-bold text-amber-700"><AlertCircle className="h-3 w-3" /> Chưa xác thực</span> : <span className="text-[10px] text-slate-400">Chưa gắn group</span>}
                              {designer.group_configured && <button type="button" onClick={() => void verifyGroup(designer)} disabled={Boolean(busy)} className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[10px] font-bold text-slate-600 hover:bg-slate-50 disabled:opacity-50">{busy === 'verify' ? 'Đang kiểm tra...' : 'Kiểm tra'}</button>}
                              {designer.group_configured && <button type="button" onClick={() => void clearGroup(designer)} disabled={Boolean(busy)} className="rounded-lg border border-red-200 bg-red-50 p-1.5 text-red-600 hover:bg-red-100 disabled:opacity-50" title="Xóa mapping group"><Trash2 className="h-3 w-3" /></button>}
                            </div>
                            {designer.group_last_error && <p className="mt-1 max-w-[320px] text-[10px] font-medium text-red-600">{designer.group_last_error}</p>}
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex items-center gap-2">
                              <select value={designer.delivery_mode} onChange={(event) => void changeMode(designer, event.target.value as DeliveryMode)} disabled={Boolean(busy)} className="rounded-lg border border-slate-200 bg-white px-2 py-2 text-[11px] font-bold text-slate-700 outline-none focus:border-[#0052CC] disabled:opacity-50">
                                <option value="private">Chat riêng</option>
                                <option value="group" disabled={!designer.group_verified}>Group chat</option>
                              </select>
                            </div>
                            <p className="mt-1 max-w-[220px] break-all font-mono text-[10px] text-slate-500">{designer.selected_chat_id || 'Chưa có đích gửi'}</p>
                          </td>
                          <td className="px-4 py-4">
                            <button type="button" onClick={() => void sendTest(designer)} disabled={Boolean(busy) || !designer.selected_chat_id} className="inline-flex items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-2.5 py-2 text-[11px] font-bold text-sky-700 hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-50">
                              {busy === 'test' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />} Gửi test
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {visibleDesigners.length === 0 && <div className="py-12 text-center text-xs text-slate-400">Không tìm thấy designer phù hợp.</div>}
              </div>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-2xs">
              <div className="flex flex-col gap-3 border-b border-slate-100 pb-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="flex items-center gap-2 text-sm font-bold text-slate-800"><MessageCircle className="h-4 w-4 text-[#0052CC]" /> Mẫu nội dung chatbot</h2>
                  <p className="mt-1 text-xs text-slate-500">Chỉnh text và giữ nguyên các placeholder được phép. Token/callback/quyền gửi không nằm trong form này.</p>
                </div>
                <div className="relative w-full sm:w-80">
                  <select value={selectedTemplateKey} onChange={(event) => setSelectedTemplateKey(event.target.value)} className="w-full appearance-none rounded-xl border border-slate-200 bg-white px-3 py-2.5 pr-9 text-xs font-semibold text-slate-700 outline-none focus:border-[#0052CC]">
                    {templates.map((template) => <option key={template.template_key} value={template.template_key}>{templateLabels[template.template_key] || template.template_key}</option>)}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                </div>
              </div>
              {selectedTemplate && (
                <div className="grid gap-5 pt-5 lg:grid-cols-2">
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold text-slate-500">
                      <span className={`rounded-lg px-2 py-1 font-bold ${selectedTemplate.audience === 'designer' ? 'bg-blue-50 text-blue-700' : 'bg-rose-50 text-rose-700'}`}>{selectedTemplate.audience === 'designer' ? 'Gửi Designer' : 'Gửi Admin'}</span>
                      <span>Version {selectedTemplate.version}</span>
                      <span>•</span>
                      <span>Placeholder: {selectedTemplate.placeholders.map((placeholder) => <code key={placeholder} className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px]">{'{{'}{placeholder}{'}}'}</code>)}</span>
                    </div>
                    <textarea value={templateDraft} onChange={(event) => setTemplateDraft(event.target.value)} rows={14} className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs leading-relaxed text-slate-800 outline-none focus:border-[#0052CC] focus:bg-white" />
                    <div className="flex flex-wrap gap-2">
                      <button type="button" onClick={() => void saveTemplate()} disabled={savingTemplate || previewingTemplate} className="inline-flex items-center gap-1.5 rounded-xl bg-[#0052CC] px-4 py-2.5 text-xs font-bold text-white hover:bg-[#0041A3] disabled:opacity-50"><Save className="h-3.5 w-3.5" /> {savingTemplate ? 'Đang lưu...' : 'Lưu mẫu tin'}</button>
                      <button type="button" onClick={() => void previewTemplate()} disabled={savingTemplate || previewingTemplate} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50"><MessageCircle className="h-3.5 w-3.5" /> {previewingTemplate ? 'Đang xem...' : 'Xem preview'}</button>
                      <button type="button" onClick={() => void resetTemplate()} disabled={savingTemplate || previewingTemplate} className="inline-flex items-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs font-bold text-amber-800 hover:bg-amber-100 disabled:opacity-50"><RotateCcw className="h-3.5 w-3.5" /> Mặc định</button>
                    </div>
                  </div>
                  <div className="rounded-2xl border border-sky-200 bg-sky-50/60 p-4">
                    <h3 className="flex items-center gap-2 text-xs font-bold text-sky-900"><MessageCircle className="h-4 w-4" /> Preview với dữ liệu mẫu</h3>
                    <div className="mt-3 min-h-64 whitespace-pre-wrap rounded-xl border border-sky-100 bg-white p-4 text-xs leading-relaxed text-slate-800 shadow-2xs">{templatePreview || 'Bấm “Xem preview” để render nội dung mẫu.'}</div>
                    <p className="mt-3 text-[11px] leading-relaxed text-sky-800">Giá trị trong placeholder sẽ được hệ thống tự escape trước khi gửi Telegram.</p>
                  </div>
                </div>
              )}
            </section>
          </>
        ) : null}
      </div>
    </DashboardLayout>
  )
}

function StatusCard({ icon: Icon, label, value, tone = 'blue' }: { icon: typeof Bot; label: string; value: string; tone?: 'blue' | 'green' | 'amber' }) {
  const colors = tone === 'green' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : tone === 'amber' ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-blue-200 bg-blue-50 text-blue-700'
  return (
    <div className={`rounded-xl border p-3 ${colors}`}>
      <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wide"><Icon className="h-4 w-4" /> {label}</div>
      <p className="mt-2 truncate text-sm font-bold">{value}</p>
    </div>
  )
}
