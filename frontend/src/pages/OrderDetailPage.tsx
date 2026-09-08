import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch, ApiError } from '../api/client'
import { DashboardLayout } from '../components/DashboardLayout'
import { ImageModal } from '../components/ImageModal'
import { TemplateModal, type TemplateJob } from '../components/TemplateModal'
import { SourceFilesCard, type SourceFile } from '../components/SourceFilesCard'
import { getStatusInfo } from '../utils/statusTranslation'
import { 
  ArrowLeft, 
  Package, 
  Clock, 
  FileText, 
  ExternalLink, 
  History, 
  AlertCircle,
  Sliders,
  User
} from 'lucide-react'

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
  template_jobs: TemplateJob[] | null
  assigned_designer_name: string | null
  design_tool_url: string | null
  sku_image_url: string | null
  external_order_url: string | null
  source_files: SourceFile[] | null
  source_download_all_url: string | null
  created_at: string
}

type WorkflowEvent = { created_at: string; from_state: string | null; to_state: string }
type LoadState = 'loading' | 'loaded' | 'not-found' | 'error'

export function OrderDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [order, setOrder] = useState<OrderDetail | null>(null)
  const [history, setHistory] = useState<WorkflowEvent[]>([])
  const [status, setStatus] = useState<LoadState>('loading')

  // Modal states
  const [showImageModal, setShowImageModal] = useState(false)
  const [showTemplateModal, setShowTemplateModal] = useState(false)

  useEffect(() => {
    if (!id) return
    setStatus('loading')
    apiFetch<{ order: OrderDetail; history: WorkflowEvent[] }>(`/orders/${id}`)
      .then((data) => {
        setOrder(data.order)
        setHistory(data.history)
        setStatus('loaded')
      })
      .catch((e) => {
        setStatus(e instanceof ApiError && e.status === 404 ? 'not-found' : 'error')
      })
  }, [id])

  if (status === 'loading') {
    return (
      <DashboardLayout>
        <div className="p-8 text-center text-slate-400">Đang tải thông tin đơn hàng...</div>
      </DashboardLayout>
    )
  }

  if (status === 'not-found' || !order) {
    return (
      <DashboardLayout>
        <div className="p-8 text-center bg-white rounded-xl border border-slate-200 shadow-xs text-slate-500">
          <AlertCircle className="h-10 w-10 mx-auto text-amber-500 mb-2" />
          <h2 className="text-base font-bold text-slate-800">Không Tìm Thấy Đơn Hàng</h2>
          <Link to="/orders" className="text-xs font-semibold text-[#0052CC] hover:underline mt-2 inline-block">
            ← Quay lại danh sách đơn hàng
          </Link>
        </div>
      </DashboardLayout>
    )
  }

  const statusInfo = getStatusInfo(order.state)

  return (
    <DashboardLayout>
      {/* Zoom Image Modal */}
      <ImageModal
        isOpen={showImageModal}
        onClose={() => setShowImageModal(false)}
        imageUrl={order.thumbnail_url}
        altText={order.external_order_id}
      />

      {/* Template Modal */}
      <TemplateModal
        isOpen={showTemplateModal}
        onClose={() => setShowTemplateModal(false)}
        templateJobs={order.template_jobs}
        orderId={order.external_order_id}
      />

      {/* Back button */}
      <div>
        <Link
          to="/orders"
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-[#0052CC] transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Quay lại danh sách đơn hàng</span>
        </Link>
      </div>

      {/* Main Card Header */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-6">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-4 pb-6 border-b border-slate-100">
          <div className="flex items-start gap-4">
            {order.thumbnail_url ? (
              <img
                src={order.thumbnail_url}
                alt=""
                title="Click để xem ảnh to"
                onClick={() => setShowImageModal(true)}
                className="h-24 w-24 rounded-xl object-cover border border-slate-200 shadow-2xs shrink-0 cursor-pointer hover:scale-105 transition-transform hover:ring-2 hover:ring-[#0052CC]"
              />
            ) : (
              <div className="h-24 w-24 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                <Package className="h-10 w-10" />
              </div>
            )}
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-xl font-bold font-mono text-[#0052CC]">{order.external_order_id}</h1>
                <span
                  title={statusInfo.description}
                  className={`px-3 py-1 rounded-md text-xs font-bold border ${statusInfo.badgeClass}`}
                >
                  {statusInfo.label}
                </span>

                {order.assigned_designer_name && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-blue-50 text-[#0052CC] text-xs font-semibold border border-blue-100">
                    <User className="h-3.5 w-3.5" />
                    <span>DES: {order.assigned_designer_name}</span>
                  </span>
                )}
              </div>
              <p className="text-sm font-semibold text-slate-800 mt-1">{order.product_name ?? 'Đơn hàng 2D Custom'}</p>
              <div className="flex flex-wrap items-center gap-4 mt-2 text-xs text-slate-500 font-mono">
                <span>SKU: <strong className="text-slate-700">{order.sku ?? '-'}</strong></span>
                <span>•</span>
                <span>Category: <strong className="text-slate-700">{order.product_category ?? '-'}</strong></span>
                {order.sku_image_url && (
                  <>
                    <span>•</span>
                    <a
                      href={order.sku_image_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-bold text-[#0052CC] hover:underline flex items-center gap-1"
                    >
                      <span>Image</span>
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </>
                )}
                {order.external_order_url && (
                  <>
                    <span>•</span>
                    <a
                      href={order.external_order_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-bold text-[#0052CC] hover:underline flex items-center gap-1"
                    >
                      <span>Order</span>
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 shrink-0">
            {order.sku_image_url && (
              <a
                href={order.sku_image_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-[#0052CC] bg-blue-50 hover:bg-blue-100 rounded-xl transition-colors border border-blue-200"
              >
                <span>Image Link</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}

            {order.external_order_url && (
              <a
                href={order.external_order_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-[#0052CC] bg-blue-50 hover:bg-blue-100 rounded-xl transition-colors border border-blue-200"
              >
                <span>Order Link</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}

            {order.template_jobs && order.template_jobs.length > 0 && (
              <button
                onClick={() => setShowTemplateModal(true)}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl transition-colors shadow-2xs cursor-pointer"
              >
                <FileText className="h-3.5 w-3.5" />
                <span>Xem template của job</span>
              </button>
            )}

            {order.design_tool_url && (
              <a
                href={order.design_tool_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors shadow-2xs border border-slate-200"
              >
                <span>Gen Design Custom</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </div>
        </div>

        {/* Specifications Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
            <span className="text-slate-400 font-semibold block uppercase text-[10px]">Deadline Printerval</span>
            <p className="font-mono font-semibold text-slate-700 flex items-center gap-1">
              <Clock className="h-3.5 w-3.5 text-amber-600" />
              <span>{order.deadline_at_ext ? new Date(order.deadline_at_ext).toLocaleString('vi-VN') : '-'}</span>
            </p>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
            <span className="text-slate-400 font-semibold block uppercase text-[10px]">Mẫu Template</span>
            <div className="flex items-center justify-between">
              <p className="font-semibold text-slate-700">
                {order.has_template || (order.template_jobs && order.template_jobs.length > 0) ? 'Đã có sẵn mẫu' : 'Chưa có mẫu'}
              </p>
              {order.template_jobs && order.template_jobs.length > 0 && (
                <button
                  onClick={() => setShowTemplateModal(true)}
                  className="text-[11px] font-bold text-[#0052CC] hover:underline cursor-pointer"
                >
                  Xem chi tiết mẫu
                </button>
              )}
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
            <span className="text-slate-400 font-semibold block uppercase text-[10px]">Ngày Phát Hiện (Crawl)</span>
            <p className="font-mono font-semibold text-slate-700">
              {new Date(order.created_at).toLocaleString('vi-VN')}
            </p>
          </div>
        </div>

        {/* Customer Source Files */}
        <SourceFilesCard
          sourceFiles={order.source_files}
          downloadAllUrl={order.source_download_all_url}
        />

        {/* Notes */}
        {(order.order_note || order.note_outsource) && (
          <div className="p-4 rounded-xl bg-blue-50/50 border border-blue-100 text-xs space-y-2">
            <h3 className="font-bold text-slate-800 flex items-center gap-1.5">
              <FileText className="h-4 w-4 text-[#0052CC]" />
              <span>Ghi Chú & Hướng Dẫn</span>
            </h3>
            {order.order_note && (
              <p className="text-slate-700 font-mono text-[11px] whitespace-pre-wrap"><strong className="text-slate-900">Order Note:</strong> {order.order_note}</p>
            )}
            {order.note_outsource && (
              <p className="text-slate-700 font-mono text-[11px] whitespace-pre-wrap"><strong className="text-slate-900">Note Outsource:</strong> {order.note_outsource}</p>
            )}
          </div>
        )}

        {/* Custom Config Entries */}
        {order.custom_config && order.custom_config.original && order.custom_config.original.length > 0 && (
          <div className="space-y-3 pt-4 border-t border-slate-100">
            <h3 className="text-xs font-bold text-slate-800 flex items-center gap-1.5 uppercase tracking-wider">
              <Sliders className="h-4 w-4 text-[#0052CC]" />
              <span>Cấu Hình Custom (Custom Configurations)</span>
            </h3>
            <div className="rounded-xl border border-slate-200 overflow-hidden">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold text-slate-500 uppercase">
                    <th className="py-2.5 px-4 w-1/3">Thuộc Tính</th>
                    <th className="py-2.5 px-4">Giá Trị</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-mono text-slate-700">
                  {order.custom_config.original.map((entry, i) => (
                    <tr key={i} className="hover:bg-slate-50/50">
                      <td className="py-2 px-4 font-semibold text-slate-600">{entry.key}</td>
                      <td className="py-2 px-4 text-[#0052CC]">{entry.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Workflow History Audit Table */}
        <div className="space-y-3 pt-4 border-t border-slate-100">
          <h3 className="text-xs font-bold text-slate-800 flex items-center gap-1.5 uppercase tracking-wider">
            <History className="h-4 w-4 text-[#0052CC]" />
            <span>Lịch Sử Chuyển Trạng Thái (Audit History)</span>
          </h3>
          <div className="rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold text-slate-500 uppercase">
                  <th className="py-2.5 px-4">Thời Gian</th>
                  <th className="py-2.5 px-4">Từ Trạng Thái</th>
                  <th className="py-2.5 px-4">Đến Trạng Thái</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-mono text-xs">
                {history.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-6 text-center text-slate-400">Chưa có bản ghi lịch sử</td>
                  </tr>
                ) : (
                  history.map((e, i) => {
                    const fromInfo = e.from_state ? getStatusInfo(e.from_state) : null
                    const toInfo = getStatusInfo(e.to_state)
                    return (
                      <tr key={i} className="hover:bg-slate-50/50">
                        <td className="py-2.5 px-4 text-slate-500">{new Date(e.created_at).toLocaleString('vi-VN')}</td>
                        <td className="py-2.5 px-4 text-slate-600">{fromInfo ? fromInfo.label : <span className="text-slate-300">-</span>}</td>
                        <td className="py-2.5 px-4 font-bold text-[#0052CC]">{toInfo.label}</td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </DashboardLayout>
  )
}
