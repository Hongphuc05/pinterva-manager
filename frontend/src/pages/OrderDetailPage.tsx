import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { apiFetch, ApiError, resolveAssetUrl } from '../api/client'
import { deduplicateGalleryUrls } from '../utils/galleryHelper'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { ImageModal } from '../components/ImageModal'
import { SourceFilesCard, type SourceFile } from '../components/SourceFilesCard'
import { ProductGalleryCard } from '../components/ProductGalleryCard'
import { ProductSkusCard, type ProductSku } from '../components/ProductSkusCard'
import { CustomConfigurationSection } from '../components/CustomConfigurationSection'
import { CopyableOrderCode } from '../components/CopyableOrderCode'
import { StatusDropdown } from '../components/StatusDropdown'
import { getStatusInfo, resolveExternalUrl } from '../utils/statusTranslation'
import { 
  ArrowLeft, 
  Package, 
  Clock, 
  FileText, 
  ExternalLink, 
  History, 
  AlertCircle,
  User,
  Send,
  CheckSquare,
  Lock,
  Loader2,
  Check,
  UserPlus,
  CheckCircle2,
  ArrowRight,
  Flame,
  RotateCcw,
  Image as ImageIcon,
  Flag,
  Layers,
} from 'lucide-react'
import { AdminFixActionModal } from '../components/AdminFixActionModal'
import { LinkifiedText, OpenExternalLinkButton } from '../components/LinkifiedText'
import { OrderWorkNotesCard } from '../components/OrderWorkNotesCard'

type ResultVersion = {
  id: string
  drive_url: string
  version_marker: number
  submitted_at: string | null
  qc_feedback: string | null
}

type OrderDetail = {
  id: string
  version: number
  external_order_id: string
  state: string
  work_domain?: string | null
  product_name: string | null
  thumbnail_url: string | null
  sku: string | null
  product_category: string | null
  product_variants: { name: string; value: string }[] | null
  multiple_design: boolean
  double_sided: boolean
  deadline_at_ext: string | null
  deadline_tacahu: string | null
  order_created_at_ext?: string | null
  created_at_ext?: string | null
  note_outsource: string
  previous_note_outsource?: string | null
  fix_approved_by_admin?: boolean
  fix_rejected_by_admin?: boolean
  fix_return_count?: number
  designer_note: string
  template_missing: boolean
  template_resolved_at?: string | null
  is_paid?: boolean
  paid_at?: string | null
  duplicate_check_status?: string
  custom_config: {
    original: { key: string; value: string }[]
    translated_vn?: { key: string; value: string }[]
  } | null
  product_skus: ProductSku[] | null
  assigned_designer_name: string | null
  assignment_id?: string | null
  sub_status?: string | null
  result_versions?: ResultVersion[]
  design_tool_url: string | null
  sku_image_url: string | null
  external_order_url: string | null
  source_files: SourceFile[] | null
  source_download_all_url: string | null
  product_image_urls?: string[] | null
  platform_designer?: string | null
  platform_status?: string | null
  created_at: string
  updated_at: string
}

type WorkflowEvent = {
  id?: string
  created_at: string
  from_state: string | null
  to_state: string
  actor_id?: string | null
  actor_name?: string | null
  actor_role?: string | null
  action?: string | null
  description?: string | null
  designer_name?: string | null
  evidence?: any
}
type LoadState = 'loading' | 'loaded' | 'not-found' | 'error'

export function OrderDetailPage() {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const usesOrderConcurrency = isAdmin || user?.role === 'designer-trello'
  const [order, setOrder] = useState<OrderDetail | null>(null)
  const [history, setHistory] = useState<WorkflowEvent[]>([])
  const [status, setStatus] = useState<LoadState>('loading')

  // Modal states
  const [showImageModal, setShowImageModal] = useState(false)
  const [selectedImageIndex, setSelectedImageIndex] = useState(0)
  const [showSubmitModal, setShowSubmitModal] = useState(false)

  // Task execution states
  const [driveUrl, setDriveUrl] = useState('')
  const [busyAssignment, setBusyAssignment] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)
  const [flaggingMissingTemplate, setFlaggingMissingTemplate] = useState(false)
  const [resolvingMissingTemplate, setResolvingMissingTemplate] = useState(false)
  const [fixActionModal, setFixActionModal] = useState<{
    isOpen: boolean
    mode: 'approve' | 'reject'
  } | null>(null)

  useEffect(() => {
    if (!showSubmitModal) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busyAssignment) setShowSubmitModal(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [showSubmitModal, busyAssignment])
  const returnTo = typeof (location.state as { returnTo?: unknown } | null)?.returnTo === 'string'
    && (location.state as { returnTo: string }).returnTo.startsWith('/orders')
    ? (location.state as { returnTo: string }).returnTo
    : '/orders'

  async function loadOrderDetail(preserveDrafts = false) {
    if (!id) return
    apiFetch<{ order: any; history: WorkflowEvent[] }>(`/orders/${id}`)
      .then((data) => {
        const orderData: OrderDetail = {
          ...data.order,
          platform_designer: data.order.platform_designer || null,
          platform_status: data.order.platform_status || null,
        }
        setOrder(orderData)
        setHistory(data.history)
        if (orderData.result_versions && orderData.result_versions.length > 0) {
          const latest = orderData.result_versions[orderData.result_versions.length - 1]
          if (!preserveDrafts && latest?.drive_url) {
            setDriveUrl(latest.drive_url)
          }
        }
        setStatus('loaded')
      })
      .catch((e) => {
        setStatus(e instanceof ApiError && e.status === 404 ? 'not-found' : 'error')
      })
  }

  async function flagMissingTemplate() {
    if (!order?.assignment_id) return
    setFlaggingMissingTemplate(true)
    setActionError(null)
    try {
      await apiFetch(`/assignments/${order.assignment_id}/flag-missing-template`, {
        method: 'POST',
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          ...(usesOrderConcurrency ? { expected_version: order.version } : {}),
        }),
      })
      setActionSuccess('Đã báo thiếu temp. Đơn được chuyển sang mục Chờ cập nhật.')
      await loadOrderDetail()
      window.dispatchEvent(new CustomEvent('orders-updated'))
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : 'Không thể báo thiếu temp.')
    } finally {
      setFlaggingMissingTemplate(false)
    }
  }

  async function resolveMissingTemplate() {
    if (!order?.template_missing) return
    setResolvingMissingTemplate(true)
    setActionError(null)
    setActionSuccess(null)
    try {
      await apiFetch(`/orders/${order.id}/resolve-missing-template`, {
        method: 'POST',
        body: JSON.stringify({ expected_version: order.version }),
      })
      setActionSuccess('Đã cập nhật temp. Tag thiếu temp được gỡ và đơn đã trả về Doing.')
      window.dispatchEvent(new CustomEvent('orders-updated'))
      await loadOrderDetail()
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : 'Không thể cập nhật temp cho đơn này.')
    } finally {
      setResolvingMissingTemplate(false)
    }
  }

  useEffect(() => {
    setStatus('loading')
    loadOrderDetail()
  }, [id])

  function handleInitiateReviewSubmit(e?: React.FormEvent) {
    if (e) e.preventDefault()
    if (!order) return
    const norm = (order.state || '').toUpperCase()
    if (norm === 'QC_PENDING' || norm === 'REVIEW') return
    const hasFix = (order.fix_return_count || 0) > 0 || norm === 'REVISION' || norm === 'FIX' || Boolean(order.fix_approved_by_admin)
    if (hasFix) {
      void handleConfirmSubmit()
      return
    }
    setActionError(null)
    setShowSubmitModal(true)
  }

  async function handleConfirmSubmit() {
    if (!order) return
    setBusyAssignment(true)
    setActionError(null)
    setActionSuccess(null)
    setShowSubmitModal(false)
    try {
      const submittedText = driveUrl.trim()
      let submittedByAssignment = false
      if (order.assignment_id) {
        try {
          await apiFetch(`/assignments/${order.assignment_id}/results`, {
            method: 'POST',
            body: JSON.stringify({
              drive_url: submittedText || 'Đã hoàn thành',
              request_id: crypto.randomUUID(),
              ...(usesOrderConcurrency ? { expected_version: order.version } : {}),
            }),
          })
          submittedByAssignment = true
        } catch (assignErr: any) {
          console.warn('Ghi nhận assignment result:', assignErr)
        }
      }
      if (!submittedByAssignment) {
        await apiFetch(`/orders/${order.id}/state`, {
          method: 'PATCH',
          body: JSON.stringify({
            state: 'QC_PENDING',
            drive_url: hasFixTag ? undefined : (submittedText || undefined),
            note_outsource: hasFixTag ? undefined : (submittedText || undefined),
            ...(usesOrderConcurrency ? { expected_version: order.version } : {}),
          }),
        })
      }
      setActionSuccess('Nộp bài QC và chuyển sang Review (Chờ duyệt) thành công!')
      window.dispatchEvent(new CustomEvent('orders-updated'))
      await loadOrderDetail()
    } catch (caught: any) {
      setActionError(caught?.message || 'Không nộp được kết quả.')
    } finally {
      setBusyAssignment(false)
    }
  }

  async function handleUpdateState(newState: string) {
    if (!order) return
    const currentNorm = (order.state || '').toUpperCase()

    // If clicking Review button and not currently in Review, trigger submission or confirm
    if (newState === 'QC_PENDING' && currentNorm !== 'QC_PENDING' && currentNorm !== 'REVIEW') {
      const hasFix = (order.fix_return_count || 0) > 0 || currentNorm === 'REVISION' || currentNorm === 'FIX' || Boolean(order.fix_approved_by_admin)
      if (hasFix) {
        void handleConfirmSubmit()
      } else {
        handleInitiateReviewSubmit()
      }
      return
    }

    setBusyAssignment(true)
    setActionError(null)
    setActionSuccess(null)
    try {
      await apiFetch(`/orders/${order.id}/state`, {
        method: 'PATCH',
        body: JSON.stringify({
          state: newState,
          ...(usesOrderConcurrency ? { expected_version: order.version } : {}),
        }),
      })
      const stateLabel =
        newState === 'IN_PROGRESS'
          ? 'Doing (Đang làm)'
          : newState === 'QC_PENDING'
          ? 'Review (Chờ duyệt)'
          : newState === 'REVISION'
          ? 'Fix (Cần sửa)'
          : newState === 'DONE'
          ? 'Done (Hoàn thành)'
          : 'Waiting (Chờ làm)'
      setActionSuccess(`Đã cập nhật tiến độ: ${stateLabel}`)
      window.dispatchEvent(new CustomEvent('orders-updated'))
      await loadOrderDetail()
    } catch (caught: any) {
      setActionError(caught?.message || 'Không thể cập nhật tiến độ.')
    } finally {
      setBusyAssignment(false)
    }
  }

  if (status === 'loading') {
    return (
      <DashboardLayout>
        <div className="p-8 text-center text-slate-400">Đang tải thông tin đơn hàng...</div>
      </DashboardLayout>
    )
  }

  if (status === 'not-found') {
    return (
      <DashboardLayout>
        <div className="p-8 text-center bg-white rounded-xl border border-slate-200 shadow-xs text-slate-500">
          <AlertCircle className="h-10 w-10 mx-auto text-amber-500 mb-2" />
          <h2 className="text-base font-bold text-slate-800">Không Tìm Thấy Đơn Hàng</h2>
          <p className="text-xs text-slate-500 mt-1">Mã đơn hàng không tồn tại hoặc đã bị xóa khỏi hệ thống.</p>
          <Link to={returnTo} className="text-xs font-semibold text-[#0052CC] hover:underline mt-3 inline-block">
            ← Quay lại danh sách đơn hàng
          </Link>
        </div>
      </DashboardLayout>
    )
  }

  if (status === 'error' || !order) {
    return (
      <DashboardLayout>
        <div className="p-8 text-center bg-white rounded-xl border border-slate-200 shadow-xs text-slate-500">
          <AlertCircle className="h-10 w-10 mx-auto text-rose-500 mb-2" />
          <h2 className="text-base font-bold text-slate-800">Không Thể Tải Chi Tiết Đơn Hàng</h2>
          <p className="text-xs text-slate-500 mt-1">Đã có lỗi kết nối mạng hoặc phản hồi từ máy chủ bị gián đoạn.</p>
          <div className="mt-4 flex items-center justify-center gap-3">
            <button
              onClick={() => {
                setStatus('loading')
                loadOrderDetail()
              }}
              className="px-3.5 py-1.5 text-xs font-semibold bg-[#0052CC] text-white rounded-lg hover:bg-blue-700 cursor-pointer shadow-2xs"
            >
              Thử tải lại ngay
            </button>
            <Link to={returnTo} className="text-xs font-semibold text-slate-600 hover:underline">
              ← Quay lại danh sách
            </Link>
          </div>
        </div>
      </DashboardLayout>
    )
  }

  const normState = (order.state || '').toUpperCase()
  const isDoing = normState === 'IN_PROGRESS' || normState === 'DOING'
  const isReview = normState === 'QC_PENDING' || normState === 'REVIEW' || normState === 'RESULT_SUBMITTED'
  const isFix = normState === 'REVISION' || normState === 'FIX' || normState === 'REVISION_REQUESTED'
  const isDone = normState === 'DONE' || normState === 'SKIPPED'
  const hasFixTag = (order.fix_return_count || 0) > 0 || isFix || Boolean(order.fix_approved_by_admin) || order.sub_status === 'fixing'
  const isDuplicateOrder =
    (order.work_domain || '').trim().toLowerCase() === 'duplicate' ||
    (order.duplicate_check_status || '').trim().toLowerCase() === 'duplicate'

  // Extract all variants to display at header (Type, Size, etc.)
  const variantsToDisplay = (() => {
    const list: { name: string; value: string }[] = []
    const seen = new Set<string>()

    const addVariant = (name?: string | null, value?: string | null) => {
      if (!name || !value) return
      // Sometimes labels such as "| Size" are returned from the source
      // markup. Strip presentation separators before deduplicating/grouping.
      const normalizedName = name.trim().replace(/^[|•·\s]+|[|•·\s]+$/g, '').trim()
      if (!normalizedName) return
      const k = `${normalizedName.toLowerCase()}:${value.trim().toLowerCase()}`
      if (!seen.has(k)) {
        seen.add(k)
        list.push({ name: normalizedName, value: value.trim() })
      }
    }

    if (order.product_variants && Array.isArray(order.product_variants)) {
      order.product_variants.forEach((v) => addVariant(v.name, v.value))
    }

    if (order.product_skus && Array.isArray(order.product_skus)) {
      order.product_skus.forEach((sku) => {
        if (sku.variants && Array.isArray(sku.variants)) {
          sku.variants.forEach((v) => addVariant(v.name, v.value))
        }
      })
    }

    return list
  })()
  const sizeValues = variantsToDisplay
    .filter((variant) => variant.name.trim().toLowerCase() === 'size')
    .map((variant) => variant.value)
  const nonSizeVariants = variantsToDisplay.filter(
    (variant) => variant.name.trim().toLowerCase() !== 'size',
  )

  // Find sample image (from sku_image_url or product_skus)
  const sampleMockupUrl =
    order.sku_image_url ||
    order.product_skus?.find((s) => s.image_url)?.image_url ||
    null

  return (
    <DashboardLayout>
      {/* Zoom Image Modal */}
      <ImageModal
        isOpen={showImageModal}
        onClose={() => setShowImageModal(false)}
        images={deduplicateGalleryUrls([
          ...(order.product_image_urls && order.product_image_urls.length > 0
            ? order.product_image_urls
            : order.thumbnail_url
            ? [order.thumbnail_url]
            : []),
          ...(sampleMockupUrl ? [sampleMockupUrl] : []),
        ])}
        initialIndex={selectedImageIndex}
        altText={isAdmin ? order.external_order_id : (order.product_name || 'Ảnh sản phẩm')}
        hideExternalLink={!isAdmin}
      />

      {/* Submit & Review Confirmation Modal */}
      {showSubmitModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-150"
          onClick={() => setShowSubmitModal(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl border border-slate-200 space-y-4 animate-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-purple-100 text-purple-700 flex items-center justify-center shrink-0">
                <Send className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900">Xác Nhận Nộp Bài Thiết Kế</h3>
                <p className="text-xs text-slate-500">Chuyển trạng thái đơn hàng sang Review (Chờ duyệt)</p>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-purple-50/60 border border-purple-200 space-y-2 text-xs">
              <p className="text-slate-700 font-medium leading-relaxed">
                Bạn có xác nhận nộp bài và đổi trạng thái đơn sang <strong className="text-purple-700 font-bold">Review (Chờ duyệt)</strong> để Admin kiểm tra và duyệt đơn không?
              </p>
              <div className="pt-2 border-t border-purple-200/60">
                <span className="text-[10px] font-bold text-purple-800 uppercase tracking-wider block mb-1">
                  Kết quả / Ghi chú nộp bài (Tùy chọn):
                </span>
                {driveUrl.trim() ? (
                  resolveExternalUrl(driveUrl.trim()) ? (
                    <a
                      href={resolveExternalUrl(driveUrl.trim())!}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-[11px] text-[#0052CC] hover:underline break-all flex items-center gap-1 font-semibold"
                    >
                      <span className="truncate">{driveUrl.trim()}</span>
                      <ExternalLink className="h-3 w-3 shrink-0" />
                    </a>
                  ) : (
                    <div className="font-mono text-[11px] text-slate-800 font-semibold break-words whitespace-pre-wrap">
                      {driveUrl.trim()}
                    </div>
                  )
                ) : (
                  <span className="text-[11px] text-slate-500 italic">(Không nhập ghi chú / link)</span>
                )}
              </div>
            </div>

            <div className="text-[11px] text-slate-500 bg-slate-50 p-2.5 rounded-lg border border-slate-100">
              Sau khi nộp, ô nhập bài sẽ được khóa. Nếu cần sửa lại, bạn có thể bấm nút <strong>"Doing"</strong> để mở lại.
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-slate-100">
              <button
                type="button"
                disabled={busyAssignment}
                onClick={() => setShowSubmitModal(false)}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors cursor-pointer"
              >
                Hủy
              </button>
              <button
                type="button"
                disabled={busyAssignment}
                onClick={handleConfirmSubmit}
                className="px-4 py-2 text-xs font-bold text-white bg-purple-600 hover:bg-purple-700 rounded-xl transition-colors shadow-2xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
              >
                {busyAssignment ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Đang nộp...</span>
                  </>
                ) : (
                  <>
                    <Check className="h-3.5 w-3.5" />
                    <span>Xác Nhận Nộp Bài</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Back button */}
      <div>
        <Link
          to={returnTo}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-[#0052CC] transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Quay lại danh sách đơn hàng</span>
        </Link>
      </div>

      {/* Alerts */}
      {actionSuccess && (
        <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold flex items-center justify-between shadow-xs">
          <span>{actionSuccess}</span>
          <button onClick={() => setActionSuccess(null)} className="text-emerald-600 hover:text-emerald-900 font-bold cursor-pointer">X</button>
        </div>
      )}
      {actionError && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-xs font-semibold flex items-center justify-between shadow-xs">
          <span>{actionError}</span>
          <button onClick={() => setActionError(null)} className="text-red-600 hover:text-red-900 font-bold cursor-pointer">X</button>
        </div>
      )}

      {/* Main Card Header */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-6">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-4 pb-6 border-b border-slate-100">
          <div className="flex items-start gap-4">
            {(() => {
              const gallery = deduplicateGalleryUrls(
                order.product_image_urls && order.product_image_urls.length > 0
                  ? order.product_image_urls
                  : order.thumbnail_url
                  ? [order.thumbnail_url]
                  : []
              )
              const currentImg =
                gallery[selectedImageIndex] || gallery[0] || order.thumbnail_url

              if (!currentImg) {
                return (
                  <div className="h-24 w-24 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                    <Package className="h-10 w-10" />
                  </div>
                )
              }

              return (
                <div className="flex flex-col items-center gap-1.5 shrink-0">
                  <div className="relative group">
                    <img
                      src={resolveAssetUrl(currentImg)}
                      alt=""
                      title="Click để xem ảnh to"
                      onClick={() => setShowImageModal(true)}
                      className="h-24 w-24 rounded-xl object-cover border border-slate-200 shadow-2xs shrink-0 cursor-pointer hover:scale-105 transition-transform hover:ring-2 hover:ring-[#0052CC]"
                    />
                    {gallery.length > 1 && (
                      <span className="absolute bottom-1 right-1 bg-slate-900/80 text-white font-mono text-[9px] px-1 rounded">
                        {selectedImageIndex + 1}/{gallery.length}
                      </span>
                    )}
                  </div>
                  {gallery.length > 1 && (
                    <div className="flex items-center gap-1 max-w-[120px] overflow-x-auto py-0.5">
                      {gallery.slice(0, 5).map((thumb, idx) => (
                        <button
                          key={idx}
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedImageIndex(idx)
                          }}
                          className={`w-4 h-4 rounded border transition-all cursor-pointer overflow-hidden shrink-0 ${
                            idx === selectedImageIndex
                              ? 'border-[#0052CC] ring-1 ring-[#0052CC]'
                              : 'border-slate-300 opacity-60 hover:opacity-100'
                          }`}
                          title={`Xem ảnh ${idx + 1}`}
                        >
                          <img
                            src={resolveAssetUrl(thumb)}
                            alt=""
                            className="w-full h-full object-cover"
                          />
                        </button>
                      ))}
                      {gallery.length > 5 && (
                        <span className="text-[9px] text-slate-400 font-mono">
                          +{gallery.length - 5}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )
            })()}
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-3">
                {isAdmin ? (
                  <CopyableOrderCode code={order.external_order_id} textSize="text-xl" />
                ) : (
                  <h1 className="text-xl font-bold text-slate-900">{order.product_name || 'Đơn hàng thiết kế'}</h1>
                )}
                {isAdmin ? (
                  <StatusDropdown
                    orderId={order.id}
                    orderVersion={order.version}
                    currentState={order.state}
                    onStatusChanged={(newState) => {
                      setOrder((prev) => prev ? { ...prev, state: newState } : null)
                      loadOrderDetail()
                    }}
                  />
                ) : !isDone && (
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-bold rounded-lg border select-none ${
                    order.template_missing
                      ? 'bg-rose-100 text-rose-800 border-rose-300'
                      : isReview
                      ? 'bg-purple-100 text-purple-800 border-purple-300'
                      : 'bg-blue-100 text-blue-800 border-blue-300'
                  }`}>
                    <span className={`h-2 w-2 rounded-full ${
                      order.template_missing
                        ? 'bg-rose-500'
                        : isReview
                        ? 'bg-purple-500'
                        : 'bg-blue-500'
                    }`} />
                    <span>{order.template_missing ? 'Chờ cập nhật' : isReview ? 'Chờ duyệt' : 'Đang làm'}</span>
                  </span>
                )}

                {isDuplicateOrder && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-50 text-violet-700 text-xs font-semibold border border-violet-200">
                    <Layers className="h-3.5 w-3.5" />
                    <span>Đơn trùng lặp</span>
                  </span>
                )}

                {order.assigned_designer_name && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-blue-50 text-[#0052CC] text-xs font-semibold border border-blue-100">
                    <User className="h-3.5 w-3.5" />
                    <span>DES: {order.assigned_designer_name}</span>
                  </span>
                )}
                {order.template_missing && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-rose-50 text-rose-700 text-xs font-bold border border-rose-200">
                    <Flag className="h-3.5 w-3.5" />
                    <span>Thiếu temp</span>
                  </span>
                )}
                {order.is_paid && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 text-xs font-bold border border-emerald-200">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    <span>Đã thanh toán</span>
                  </span>
                )}
                {hasFixTag && (
                  <span className="inline-flex items-center px-2.5 py-1 rounded-md bg-orange-50 text-orange-800 text-xs font-bold border border-orange-200" title="Số lần Printerval trả đơn về Fix">
                    Fix × {order.fix_return_count || 1}
                  </span>
                )}
                {isAdmin && order.platform_designer && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-50 text-violet-700 text-xs font-semibold border border-violet-100">
                    <User className="h-3.5 w-3.5" />
                    <span>
                      Acc Mẹ: {order.platform_designer}
                      {order.platform_status ? ` · ${order.platform_status}` : ''}
                    </span>
                  </span>
                )}
              </div>
              {isAdmin && (
                <p className="text-sm font-semibold text-slate-800 mt-1">{order.product_name ?? 'Đơn hàng 2D Custom'}</p>
              )}
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mt-2 text-xs text-slate-500 font-mono">
                {isAdmin && (
                  <>
                    <span>SKU: <strong className="text-slate-700">{order.sku ?? '-'}</strong></span>
                    <span>•</span>
                  </>
                )}
                <span>Category: <strong className="text-slate-700">{order.product_category ?? '-'}</strong></span>
                {nonSizeVariants.map((v, idx) => (
                  <span key={idx} className="flex items-center gap-3">
                    <span>•</span>
                    <span>{v.name}: <strong className="text-slate-700">{v.value}</strong></span>
                  </span>
                ))}
                {sizeValues.length > 0 && (
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span>•</span>
                    <span>Size:</span>
                    {sizeValues.map((size) => (
                      <strong
                        key={size}
                        className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-slate-700"
                      >
                        {size}
                      </strong>
                    ))}
                  </span>
                )}
                {sampleMockupUrl && (
                  <>
                    <span>•</span>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedImageIndex(0)
                        setShowImageModal(true)
                      }}
                      className="font-bold text-[#0052CC] hover:underline flex items-center gap-1 cursor-pointer"
                    >
                      <ImageIcon className="h-3 w-3" />
                      <span>Xem ảnh mẫu</span>
                    </button>
                  </>
                )}
                {isAdmin && order.external_order_url && (
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
            {isAdmin && order.template_missing && (
              <button
                type="button"
                onClick={resolveMissingTemplate}
                disabled={resolvingMissingTemplate || busyAssignment}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 rounded-xl transition-colors border border-emerald-200 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {resolvingMissingTemplate ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                <span>{resolvingMissingTemplate ? 'Đang cập nhật…' : 'Cập nhật temp'}</span>
              </button>
            )}
            {sampleMockupUrl && (
              <button
                type="button"
                onClick={() => {
                  setSelectedImageIndex(0)
                  setShowImageModal(true)
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-[#0052CC] bg-blue-50 hover:bg-blue-100 rounded-xl transition-colors border border-blue-200 cursor-pointer"
              >
                <ImageIcon className="h-3.5 w-3.5" />
                <span>Xem ảnh mẫu</span>
              </button>
            )}

            {isAdmin && order.external_order_url && (
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

            {isAdmin && order.design_tool_url && (
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

        {/* Designer Task Actions Block */}
        {(order.assignment_id || order.platform_designer || isAdmin) && (
          <div className="p-5 rounded-xl bg-blue-50/40 border border-blue-200 space-y-4">
            <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2">
              <CheckSquare className="h-4 w-4 text-[#0052CC]" />
              <span>Nhiệm Vụ & Tiến Độ Thiết Kế</span>
            </h3>

            {/* Fix Notice Banner if order is in REVISION */}
            {isFix && (
              <div className="p-4 rounded-xl bg-orange-50 border border-orange-200 text-xs text-orange-950 space-y-2.5">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="font-bold flex items-center gap-1.5 text-orange-900">
                    <Flame className="h-4 w-4 text-orange-600" />
                    <span>Yêu Cầu Sửa Bài (QC):</span>
                    {order.fix_approved_by_admin ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
                        Đã gửi fix cho des
                      </span>
                    ) : order.fix_rejected_by_admin ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-100 text-purple-800 border border-purple-200">
                        Đã từ chối fix
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800">
                        Chưa lựa chọn (Chờ Admin check)
                      </span>
                    )}
                  </div>
                  {isAdmin && (
                    <div className="flex items-center gap-2">
                      {!order.fix_approved_by_admin ? (
                        <>
                          <button
                            type="button"
                            onClick={() => setFixActionModal({ isOpen: true, mode: 'approve' })}
                            className="px-3 py-1 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg shadow-2xs cursor-pointer flex items-center gap-1"
                          >
                            <Check className="h-3 w-3" />
                            <span>Check & Duyệt</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setFixActionModal({ isOpen: true, mode: 'reject' })}
                            className="px-3 py-1 text-xs font-bold text-slate-700 bg-white hover:bg-slate-100 border border-slate-300 rounded-lg shadow-2xs cursor-pointer flex items-center gap-1"
                          >
                            <RotateCcw className="h-3 w-3" />
                            <span>Hủy trả Review</span>
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setFixActionModal({ isOpen: true, mode: 'reject' })}
                          className="px-2.5 py-1 text-xs font-semibold text-slate-600 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg cursor-pointer"
                        >
                          Đổi ý: Hủy trả Review
                        </button>
                      )}
                    </div>
                  )}
                </div>

                <div className="whitespace-pre-wrap break-all leading-relaxed font-sans text-slate-800 bg-white/90 p-3 rounded-lg border border-orange-200/80">
                  {isAdmin
                    ? (order.note_outsource ? <LinkifiedText text={order.note_outsource} /> : 'Chưa có ghi chú cụ thể từ QC.')
                    : (order.designer_note || 'Admin chưa gửi hướng dẫn Fix.')}
                </div>
              </div>
            )}

            {/* Progress Control Buttons: Des only has Doing and Review! */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="text-xs font-semibold text-slate-600">Cập nhật tiến độ:</span>

                {/* 1. DOING Button */}
                <button
                  type="button"
                  disabled={busyAssignment || isDoing}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all border cursor-pointer flex items-center gap-1.5 ${
                    isDoing
                      ? 'bg-blue-600 text-white border-blue-600 shadow-2xs ring-2 ring-blue-400/20'
                      : 'bg-white text-blue-700 border-blue-200 hover:bg-blue-50'
                  } disabled:opacity-50`}
                  onClick={() => handleUpdateState('IN_PROGRESS')}
                >
                  <span className={`h-2 w-2 rounded-full ${isDoing ? 'bg-white' : 'bg-blue-500'}`} />
                  <span>Đang làm</span>
                </button>

                {/* 2. REVIEW Button */}
                <button
                  type="button"
                  disabled={busyAssignment || isReview}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all border cursor-pointer flex items-center gap-1.5 ${
                    isReview
                      ? 'bg-purple-600 text-white border-purple-600 shadow-2xs ring-2 ring-purple-400/20'
                      : 'bg-white text-purple-700 border-purple-200 hover:bg-purple-50'
                  } disabled:opacity-50`}
                  onClick={() => handleUpdateState('QC_PENDING')}
                >
                  <span className={`h-2 w-2 rounded-full ${isReview ? 'bg-white' : 'bg-purple-500'}`} />
                  <span>Chờ duyệt</span>
                </button>

                {/* If Admin, show Fix and Done buttons as well */}
                {isAdmin && (
                  <>
                    <button
                      type="button"
                      disabled={busyAssignment || isFix}
                      className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all border cursor-pointer flex items-center gap-1.5 ${
                        isFix
                          ? 'bg-orange-600 text-white border-orange-600 shadow-2xs'
                          : 'bg-white text-orange-700 border-orange-200 hover:bg-orange-50'
                      } disabled:opacity-50`}
                      onClick={() => handleUpdateState('REVISION')}
                    >
                      <span className={`h-2 w-2 rounded-full ${isFix ? 'bg-white' : 'bg-orange-500'}`} />
                      <span>Fix (Cần sửa)</span>
                    </button>

                    <button
                      type="button"
                      disabled={busyAssignment || isDone}
                      className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all border cursor-pointer flex items-center gap-1.5 ${
                        isDone
                          ? 'bg-emerald-600 text-white border-emerald-600 shadow-2xs'
                          : 'bg-white text-emerald-700 border-emerald-200 hover:bg-emerald-50'
                      } disabled:opacity-50`}
                      onClick={() => handleUpdateState('DONE')}
                    >
                      <span className={`h-2 w-2 rounded-full ${isDone ? 'bg-white' : 'bg-emerald-500'}`} />
                      <span>Done (Hoàn thành)</span>
                    </button>
                  </>
                )}
              </div>
              {!isAdmin && order.assignment_id && (
                order.template_missing ? (
                  <span className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700">
                    <Flag className="h-3.5 w-3.5" /> Đang chờ cập nhật temp
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={flagMissingTemplate}
                    disabled={busyAssignment || flaggingMissingTemplate || isDone}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
                    title="Báo Admin rằng đơn này thiếu temp"
                  >
                    {flaggingMissingTemplate ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Flag className="h-3.5 w-3.5" />}
                    {flaggingMissingTemplate ? 'Đang báo…' : 'Báo thiếu temp'}
                  </button>
                )
              )}
            </div>

            {/* A Fix reuses its first result link; Designer can only update it back to Review. */}
            {!isDone && (
              <form
                className="space-y-2 pt-3 border-t border-blue-100"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (hasFixTag) void handleConfirmSubmit()
                  else handleInitiateReviewSubmit()
                }}
              >
                <div className="flex flex-col sm:flex-row gap-3">
                  {!hasFixTag && (
                    <div className="relative flex-1">
                      <input
                        type="text"
                        disabled={isReview || busyAssignment}
                        className={`w-full px-3.5 py-2 text-xs rounded-xl border font-mono transition-all focus:outline-none ${
                          isReview
                            ? 'bg-slate-100 text-slate-500 border-slate-200 cursor-not-allowed pr-40'
                            : 'bg-white text-slate-900 border-slate-300 focus:border-[#0052CC] focus:ring-1 focus:ring-[#0052CC] pr-24'
                        }`}
                        placeholder={
                          isReview
                            ? 'Đã nộp bài - Đang ở Review (Bấm "Doing" ở trên nếu muốn sửa nộp lại)'
                            : 'Nhập link Drive, link ảnh hoặc ghi chú hoàn thành (tùy chọn)...'
                        }
                        value={driveUrl}
                        onChange={(e) => setDriveUrl(e.target.value)}
                      />
                      {!isReview && (
                        <span className="absolute right-1.5 top-1/2 -translate-y-1/2">
                          <OpenExternalLinkButton url={driveUrl} label="Mở" />
                        </span>
                      )}
                      {isReview && (
                        <span className="absolute right-2.5 top-1.5 text-[10px] font-bold text-purple-800 bg-purple-100 px-2 py-1 rounded-md border border-purple-200 flex items-center gap-1 shadow-2xs select-none">
                          <Lock className="h-3 w-3" />
                          <span>Đã khóa ở Review</span>
                        </span>
                      )}
                    </div>
                  )}

                  {hasFixTag && !isReview && (
                    <div className="flex-1 flex items-center gap-2 text-xs font-semibold text-orange-900 bg-orange-50 border border-orange-200/80 px-3.5 py-2 rounded-xl">
                      <AlertCircle className="h-4 w-4 text-orange-600 shrink-0" />
                      <span>Đơn có tag Fix (Fix × {order.fix_return_count || 1}). Bài nộp giữ nguyên link gốc từ kho lưu trữ. Bạn thực hiện sửa bài và bấm Cập nhật đơn để gửi Review.</span>
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={isReview || busyAssignment}
                    className={`px-5 py-2 text-xs font-bold rounded-xl transition-all shadow-2xs flex items-center justify-center gap-1.5 shrink-0 select-none ${
                      isReview
                        ? 'bg-slate-200 text-slate-400 border border-slate-300 cursor-not-allowed'
                        : 'text-white bg-emerald-600 hover:bg-emerald-700 cursor-pointer hover:shadow-xs'
                    }`}
                  >
                    <Send className="h-3.5 w-3.5" />
                    <span>{isReview ? 'Đã Nộp (Chờ Review)' : hasFixTag ? 'Cập nhật đơn' : 'Nộp Bài QC (Màu Xanh)'}</span>
                  </button>
                </div>

                {isReview && (
                  <p className="text-[11px] text-slate-500 italic flex items-center gap-1 pt-1">
                    <span>Đơn đang chờ Admin review. Nếu cần nộp lại, bạn chỉ cần bấm nút</span>
                    <strong className="text-blue-600 font-bold not-italic">"Doing (Đang làm)"</strong>
                    <span>ở trên để mở khóa ô nhập bài.</span>
                  </p>
                )}
              </form>
            )}

            {/* History of Submitted Versions */}
            {isAdmin && order.result_versions && order.result_versions.length > 0 && (
              <div className="pt-3 border-t border-blue-100 space-y-2">
                <h4 className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                  <History className="h-3.5 w-3.5 text-slate-500" />
                  <span>Lịch sử các bản đã nộp ({order.result_versions.length})</span>
                </h4>
                <div className="space-y-2">
                  {order.result_versions.map((version) => {
                    const validUrl = resolveExternalUrl(version.drive_url)
                    return (
                      <div key={version.id} className="p-3 rounded-lg bg-white border border-slate-200 flex items-center justify-between text-xs">
                        {validUrl ? (
                          <a
                            href={validUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-mono font-bold text-[#0052CC] hover:underline flex items-center gap-1"
                          >
                            <span>Bản v{version.version_marker}</span>
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold text-slate-800">Bản v{version.version_marker}</span>
                            {version.drive_url && (
                              <span className="text-slate-600 bg-slate-50 px-2 py-0.5 rounded border border-slate-200 text-[11px] font-mono">
                                {version.drive_url}
                              </span>
                            )}
                          </div>
                        )}
                        {version.qc_feedback && (
                          <p className="text-amber-800 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 text-[11px] font-medium">
                            QC Feedback: {version.qc_feedback}
                          </p>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Specifications Grid */}
        {!isAdmin ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
              <span className="text-slate-400 font-semibold block uppercase text-[10px]">
                Thời Gian Khách Đặt (Order At)
              </span>
              <p className="font-mono font-semibold text-slate-800 flex items-center gap-1.5 text-sm">
                <Clock className="h-4 w-4 text-blue-600" />
                <span>
                  {order.order_created_at_ext
                    ? new Date(order.order_created_at_ext).toLocaleString('vi-VN')
                    : order.created_at_ext
                    ? new Date(order.created_at_ext).toLocaleString('vi-VN')
                    : new Date(order.created_at).toLocaleString('vi-VN')}
                </span>
              </p>
            </div>

            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
              <span className="text-slate-400 font-semibold block uppercase text-[10px]">
                Deadline
              </span>
              <p className="font-mono font-semibold text-slate-800 flex items-center gap-1.5 text-sm">
                <Clock className="h-4 w-4 text-amber-600" />
                <span>
                  {order.deadline_tacahu
                    ? new Date(order.deadline_tacahu).toLocaleString('vi-VN')
                    : '-'}
                </span>
              </p>
            </div>
          </div>
        ) : (
          <div className={`grid grid-cols-1 gap-4 text-xs ${isAdmin ? 'md:grid-cols-5' : 'md:grid-cols-4'}`}>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
              <span className="text-slate-400 font-semibold block uppercase text-[10px]">Thời Gian Khách Đặt (Order At)</span>
              <p className="font-mono font-semibold text-slate-700 flex items-center gap-1">
                <Clock className="h-3.5 w-3.5 text-blue-600" />
                <span>
                  {order.order_created_at_ext
                    ? new Date(order.order_created_at_ext).toLocaleString('vi-VN')
                    : '-'}
                </span>
              </p>
            </div>

            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
              <span className="text-slate-400 font-semibold block uppercase text-[10px]">Hạn chót Tacahu</span>
              <p className="font-mono font-semibold text-slate-700 flex items-center gap-1">
                <Clock className="h-3.5 w-3.5 text-amber-600" />
                <span>{order.deadline_tacahu ? new Date(order.deadline_tacahu).toLocaleString('vi-VN') : '-'}</span>
              </p>
            </div>

            {isAdmin && (
              <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
                <span className="text-slate-400 font-semibold block uppercase text-[10px]">Deadline Printerval</span>
                <p className="font-mono font-semibold text-slate-700 flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5 text-slate-500" />
                  <span>{order.deadline_at_ext ? new Date(order.deadline_at_ext).toLocaleString('vi-VN') : '-'}</span>
                </p>
              </div>
            )}

            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
              <span className="text-slate-400 font-semibold block uppercase text-[10px]">Mẫu hàng</span>
              <p className="font-semibold text-slate-700">{order.product_skus?.length || (order.sku ? 1 : 0)} mẫu hàng</p>
            </div>

            {isAdmin && (
              <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
                <span className="text-slate-400 font-semibold block uppercase text-[10px]">Ngày Phát Hiện (Crawl)</span>
                <p className="font-mono font-semibold text-slate-700">
                  {new Date(order.created_at).toLocaleString('vi-VN')}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Printerval's source note is read-only; team discussion lives in Note làm việc. */}
        {isAdmin && (
          <div className="p-4 rounded-xl bg-blue-50/50 border border-blue-100 text-xs space-y-2">
            <h3 className="font-bold text-slate-800 flex items-center gap-1.5">
              <FileText className="h-4 w-4 text-[#0052CC]" />
              <span>Note Outsource từ Printerval</span>
            </h3>
            <p className="text-slate-700 font-mono text-[11px] whitespace-pre-wrap">
              {order.note_outsource ? <LinkifiedText text={order.note_outsource} /> : 'Chưa có note từ Printerval.'}
            </p>
          </div>
        )}

        <OrderWorkNotesCard orderId={order.id} />

        {/* Custom configuration */}
        {order.custom_config && order.custom_config.original && order.custom_config.original.length > 0 && (
          <div className="space-y-3 pt-4 border-t border-slate-100">
            <CustomConfigurationSection entries={order.custom_config.original} />
            {order.custom_config.translated_vn && order.custom_config.translated_vn.length > 0 && (
              <CustomConfigurationSection entries={order.custom_config.translated_vn} translated />
            )}
          </div>
        )}

        {/* Product SKU Card (Admin only) */}
        {isAdmin && (
          <ProductSkusCard
            productSkus={order.product_skus}
            fallbackSku={order.sku}
            fallbackCategory={order.product_category}
            fallbackVariants={order.product_variants}
            isAdmin={isAdmin}
          />
        )}

        {(isAdmin || (order.product_image_urls && order.product_image_urls.length > 0)) && (
          <ProductGalleryCard
            orderId={order.id}
            orderVersion={order.version}
            images={order.product_image_urls}
            orderTitle={order.product_name}
            isAdmin={isAdmin}
            onSelectImage={(index) => {
              setSelectedImageIndex(index)
              setShowImageModal(true)
            }}
            onGalleryUpdated={(newImages) => {
              setOrder((prev) => (prev ? { ...prev, product_image_urls: newImages } : null))
            }}
          />
        )}

        {/* Source Files Card */}
        <SourceFilesCard
          sourceFiles={order.source_files}
          downloadAllUrl={order.source_download_all_url}
          isAdmin={isAdmin}
        />

        {/* Workflow History Audit Table — Admin only */}
        {isAdmin && <div className="space-y-4 pt-4 border-t border-slate-100">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold text-slate-800 flex items-center gap-1.5 uppercase tracking-wider">
              <History className="h-4 w-4 text-[#0052CC]" />
              <span>Lịch Sử Tiến Độ & Hoạt Động (Audit Trail)</span>
            </h3>
            <span className="text-xs font-medium text-slate-400">
              {history.length} sự kiện
            </span>
          </div>

          <div className="rounded-xl border border-slate-200 overflow-hidden bg-white shadow-2xs">
            {history.length === 0 ? (
              <div className="py-8 text-center text-slate-400 text-xs">
                Chưa có bản ghi lịch sử nào cho đơn này
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {history.map((e, i) => {
                  const fromInfo = e.from_state ? getStatusInfo(e.from_state) : null
                  const toInfo = getStatusInfo(e.to_state)
                  const act = (e.action || '').toUpperCase()
                  const isDone = act === 'APPROVE_DONE'
                  const isFix = act === 'REQUEST_FIX'
                  const isReview = act === 'SUBMIT_REVIEW'
                  const isAssign = act === 'ASSIGN' || act === 'REASSIGN'
                  const isDoing = act === 'START_DOING' || act === 'REVERT_TO_DOING'
                  const driveLink = e.evidence?.drive_link || (e.evidence?.note?.includes('http') ? e.evidence.note : null)

                  return (
                    <div key={i} className="p-4 hover:bg-slate-50/60 transition-colors flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs">
                      <div className="flex items-start gap-3">
                        <div className={`mt-0.5 w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
                          isDone ? 'bg-emerald-100 text-emerald-700' :
                          isFix ? 'bg-amber-100 text-amber-700' :
                          isReview ? 'bg-purple-100 text-purple-700' :
                          isAssign ? 'bg-blue-100 text-blue-700' :
                          isDoing ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600'
                        }`}>
                          {isDone ? <CheckCircle2 className="w-4 h-4" /> :
                           isFix ? <AlertCircle className="w-4 h-4" /> :
                           isReview ? <Send className="w-4 h-4" /> :
                           isAssign ? <UserPlus className="w-4 h-4" /> :
                           <Clock className="w-4 h-4" />}
                        </div>
                        <div className="space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-slate-900">
                              {e.description || `Chuyển trạng thái sang ${toInfo.label}`}
                            </span>
                            {e.actor_name && (
                              <span className="text-[11px] text-slate-500 flex items-center gap-1">
                                <span>bởi</span>
                                <span className="font-medium text-slate-700">{e.actor_name}</span>
                                {e.actor_role && (
                                  <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${
                                    e.actor_role === 'admin' ? 'bg-rose-50 text-rose-600' : 'bg-blue-50 text-blue-600'
                                  }`}>
                                    {e.actor_role}
                                  </span>
                                )}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-[11px] text-slate-500 flex-wrap">
                            <span>{new Date(e.created_at).toLocaleString('vi-VN')}</span>
                            <span>•</span>
                            <div className="flex items-center gap-1">
                              {fromInfo ? (
                                <span className={`px-1.5 py-0.5 rounded text-[10px] border ${fromInfo.badgeClass}`}>
                                  {fromInfo.label}
                                </span>
                              ) : (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-500 border border-slate-200">Mới</span>
                              )}
                              <ArrowRight className="w-3 h-3 text-slate-400" />
                              <span className={`px-1.5 py-0.5 rounded text-[10px] border ${toInfo.badgeClass}`}>
                                {toInfo.label}
                              </span>
                            </div>
                            {driveLink && (() => {
                              const validDriveUrl = resolveExternalUrl(driveLink)
                              return validDriveUrl ? (
                                <>
                                  <span>•</span>
                                  <a
                                    href={validDriveUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-0.5 text-blue-600 hover:underline font-medium"
                                  >
                                    <ExternalLink className="w-3 h-3" />
                                    <span>Link nộp bài</span>
                                  </a>
                                </>
                              ) : (
                                <>
                                  <span>•</span>
                                  <span className="inline-flex items-center gap-0.5 text-slate-600 font-mono text-[10px] bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200">
                                    Bài nộp: {driveLink}
                                  </span>
                                </>
                              )
                            })()}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>}
      </div>
      {fixActionModal && order && (
        <AdminFixActionModal
          isOpen={fixActionModal.isOpen}
          onClose={() => setFixActionModal(null)}
          orderId={order.id}
          orderVersion={order.version}
          externalOrderId={order.external_order_id}
          mode={fixActionModal.mode}
          currentNote={order.note_outsource}
          previousNote={order.previous_note_outsource}
          onSuccess={() => {
            loadOrderDetail()
            window.dispatchEvent(new CustomEvent('orders-updated'))
          }}
        />
      )}
    </DashboardLayout>
  )
}
