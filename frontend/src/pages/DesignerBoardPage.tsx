import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch, resolveAssetUrl } from '../api/client'
import { DashboardLayout } from '../components/DashboardLayout'
import { ImageModal } from '../components/ImageModal'
import { StatusDropdown } from '../components/StatusDropdown'
import { 
  Users, 
  Search, 
  RotateCcw, 
  Package, 
  Clock, 
  AlertCircle, 
  Check, 
  Flame, 
  ChevronRight,
  CheckCheck
} from 'lucide-react'

type DesignerOrder = {
  id: string
  external_order_id: string
  state: string
  thumbnail_url: string | null
  deadline_at_ext: string | null
  product_name: string | null
  printerval_designer: string | null
}

type DesignerWorkload = {
  id: string
  username: string
  full_name: string
  printerval_designer_option: string | null
  total_orders: number
  doing_count: number
  review_count: number
  fix_count: number
  done_count: number
  orders: DesignerOrder[]
}

export function DesignerBoardPage() {
  const [designers, setDesigners] = useState<DesignerWorkload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterMode, setFilterMode] = useState<'all' | 'needs_review' | 'has_fix' | 'active'>('all')
  const [selectedImage, setSelectedImage] = useState<string | null>(null)
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null)
  const [showDoneColumn, setShowDoneColumn] = useState(true)

  useEffect(() => {
    loadWorkload()

    function handleUpdate() {
      loadWorkload()
    }
    window.addEventListener('orders-updated', handleUpdate)
    return () => window.removeEventListener('orders-updated', handleUpdate)
  }, [])

  async function loadWorkload() {
    setLoading(true)
    try {
      const data = await apiFetch<DesignerWorkload[]>('/designers/workload')
      setDesigners(data)
      setError(null)
    } catch (err: any) {
      setError(err.message || 'Không thể tải bảng tiến độ Designer.')
    } finally {
      setLoading(false)
    }
  }

  async function handleQuickState(orderId: string, newState: 'DONE' | 'REVISION') {
    setActionLoadingId(orderId)
    try {
      await apiFetch(`/orders/${orderId}/state`, {
        method: 'PATCH',
        body: JSON.stringify({ state: newState }),
      })
      await loadWorkload()
      window.dispatchEvent(new CustomEvent('orders-updated'))
    } catch (err: any) {
      alert(err.message || 'Lỗi khi cập nhật trạng thái đơn.')
    } finally {
      setActionLoadingId(null)
    }
  }

  // Aggregate stats across all designers
  const totalDesigners = designers.length
  const totalAllOrders = designers.reduce((sum, d) => sum + d.total_orders, 0)
  const totalDoing = designers.reduce((sum, d) => sum + d.doing_count, 0)
  const totalReview = designers.reduce((sum, d) => sum + d.review_count, 0)
  const totalFix = designers.reduce((sum, d) => sum + d.fix_count, 0)
  const totalDone = designers.reduce((sum, d) => sum + d.done_count, 0)

  // Filtering
  const filteredDesigners = designers.filter((des) => {
    const matchSearch =
      des.full_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      des.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (des.printerval_designer_option &&
        des.printerval_designer_option.toLowerCase().includes(searchQuery.toLowerCase()))

    if (!matchSearch) return false

    if (filterMode === 'needs_review') return des.review_count > 0
    if (filterMode === 'has_fix') return des.fix_count > 0
    if (filterMode === 'active') return des.doing_count > 0 || des.review_count > 0 || des.fix_count > 0
    return true
  })

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Top Summary Banner */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-900 flex items-center gap-2.5">
              <Users className="h-6 w-6 text-[#0052CC]" />
              <span>Tiến Độ & Năng Suất Designer</span>
            </h1>
            <p className="text-xs text-slate-500 mt-1">
              Trực quan hóa khối lượng công việc, theo dõi tiến độ Doing / Review / Fix / Done của toàn bộ đội ngũ Designer.
            </p>
          </div>

          <button
            onClick={loadWorkload}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-semibold bg-white hover:bg-slate-50 text-slate-700 rounded-xl border border-slate-200 shadow-2xs transition-all cursor-pointer"
          >
            <RotateCcw className="h-3.5 w-3.5 text-slate-500" />
            <span>Làm Mới Dữ Liệu</span>
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2.5 p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-semibold">
            <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
            <span>{error}</span>
          </div>
        )}

        {/* Global KPI Summary Grid */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3.5">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Tổng Đơn Đang Quản Lý</div>
            <div className="text-2xl font-black font-mono text-slate-800 mt-1">{totalAllOrders}</div>
            <div className="text-[10px] text-slate-400 mt-1 font-medium">{totalDesigners} Designer trong team</div>
          </div>

          <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4 shadow-2xs">
            <div className="text-[11px] font-bold text-blue-700 uppercase tracking-wider flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-blue-500"></span>
              <span>Đang Làm (Doing)</span>
            </div>
            <div className="text-2xl font-black font-mono text-blue-800 mt-1">{totalDoing}</div>
            <div className="text-[10px] text-blue-600/80 mt-1 font-medium">Đang trong quá trình thiết kế</div>
          </div>

          <div className={`rounded-xl border p-4 shadow-2xs transition-all ${
            totalReview > 0
              ? 'border-purple-300 bg-purple-50 ring-2 ring-purple-400/20'
              : 'border-slate-200 bg-white'
          }`}>
            <div className="text-[11px] font-bold text-purple-700 uppercase tracking-wider flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full bg-purple-500 ${totalReview > 0 ? 'animate-ping' : ''}`}></span>
              <span>Chờ Duyệt (Review)</span>
            </div>
            <div className="text-2xl font-black font-mono text-purple-800 mt-1">{totalReview}</div>
            <div className="text-[10px] text-purple-600/80 mt-1 font-medium">
              {totalReview > 0 ? '⚡ Cần Admin kiểm tra duyệt' : 'Không có đơn chờ duyệt'}
            </div>
          </div>

          <div className={`rounded-xl border p-4 shadow-2xs transition-all ${
            totalFix > 0
              ? 'border-orange-300 bg-orange-50/80'
              : 'border-slate-200 bg-white'
          }`}>
            <div className="text-[11px] font-bold text-orange-700 uppercase tracking-wider flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-orange-500"></span>
              <span>Cần Sửa (Fix)</span>
            </div>
            <div className="text-2xl font-black font-mono text-orange-800 mt-1">{totalFix}</div>
            <div className="text-[10px] text-orange-600/80 mt-1 font-medium">Đang chờ Designer sửa lại</div>
          </div>

          <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 shadow-2xs">
            <div className="text-[11px] font-bold text-emerald-700 uppercase tracking-wider flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500"></span>
              <span>Hoàn Thành (Done)</span>
            </div>
            <div className="text-2xl font-black font-mono text-emerald-800 mt-1">{totalDone}</div>
            <div className="text-[10px] text-emerald-600/80 mt-1 font-medium">Đã kiểm tra & hoàn tất</div>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3.5 rounded-xl border border-slate-200 shadow-2xs">
          <div className="relative w-full sm:w-80">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Tìm kiếm Designer theo tên..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-1.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:border-[#0052CC]"
            />
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto overflow-x-auto pb-1 sm:pb-0">
            <button
              onClick={() => setFilterMode('all')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all cursor-pointer ${
                filterMode === 'all'
                  ? 'bg-slate-900 text-white border-slate-900 shadow-2xs'
                  : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
              }`}
            >
              Tất Cả ({totalDesigners})
            </button>
            <button
              onClick={() => setFilterMode('needs_review')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all cursor-pointer flex items-center gap-1.5 ${
                filterMode === 'needs_review'
                  ? 'bg-purple-600 text-white border-purple-600 shadow-2xs'
                  : 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100'
              }`}
            >
              <span>Có đơn Review</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-purple-200 text-purple-900 font-mono font-bold">
                {designers.filter((d) => d.review_count > 0).length}
              </span>
            </button>
            <button
              onClick={() => setFilterMode('has_fix')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all cursor-pointer flex items-center gap-1.5 ${
                filterMode === 'has_fix'
                  ? 'bg-orange-600 text-white border-orange-600 shadow-2xs'
                  : 'bg-orange-50 text-orange-700 border-orange-200 hover:bg-orange-100'
              }`}
            >
              <span>Có đơn Fix</span>
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-orange-200 text-orange-900 font-mono font-bold">
                {designers.filter((d) => d.fix_count > 0).length}
              </span>
            </button>
            <button
              onClick={() => setFilterMode('active')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all cursor-pointer ${
                filterMode === 'active'
                  ? 'bg-[#0052CC] text-white border-[#0052CC] shadow-2xs'
                  : 'bg-blue-50 text-[#0052CC] border-blue-200 hover:bg-blue-100'
              }`}
            >
              Đang có việc
            </button>

            <div className="h-4 w-px bg-slate-200 mx-1 hidden sm:block" />

            <button
              onClick={() => setShowDoneColumn(!showDoneColumn)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-all cursor-pointer flex items-center gap-1.5 shrink-0 ${
                showDoneColumn
                  ? 'bg-slate-100 text-slate-700 border-slate-300 hover:bg-slate-200'
                  : 'bg-emerald-600 text-white border-emerald-600 shadow-2xs'
              }`}
              title="Chuyển đổi giữa 4 cột (gồm Done) và 3 cột (Doing-Review-Fix)"
            >
              <span>{showDoneColumn ? 'Ẩn Cột Done (3 Cột)' : 'Hiện Cột Done (4 Cột)'}</span>
            </button>
          </div>
        </div>

        {/* Designers Workload List */}
        {loading && designers.length === 0 ? (
          <div className="py-20 text-center text-slate-400 bg-white rounded-2xl border border-slate-200">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-3 border-[#0052CC] border-t-transparent mb-3" />
            <p className="text-xs font-semibold text-slate-600">Đang tải dữ liệu tiến độ Designer...</p>
          </div>
        ) : filteredDesigners.length === 0 ? (
          <div className="py-16 text-center text-slate-400 bg-white rounded-2xl border border-slate-200">
            <Package className="h-10 w-10 mx-auto mb-2 opacity-30 text-slate-400" />
            <p className="text-sm font-semibold text-slate-600">Không tìm thấy Designer nào phù hợp</p>
            <p className="text-xs text-slate-400 mt-1">Thử đổi từ khóa tìm kiếm hoặc chọn bộ lọc Tất Cả</p>
          </div>
        ) : (
          <div className="space-y-6">
            {filteredDesigners.map((des) => {
              const completionRate =
                des.total_orders > 0 ? Math.round((des.done_count / des.total_orders) * 100) : 0

              const reviewOrders = des.orders.filter((o) =>
                ['QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE'].includes(o.state.toUpperCase())
              )
              const fixOrders = des.orders.filter((o) =>
                ['REVISION', 'REVISION_REQUESTED'].includes(o.state.toUpperCase())
              )
              const doingOrders = des.orders.filter((o) =>
                ['IN_PROGRESS', 'ASSIGNED', 'WAITING', 'PENDING'].includes(o.state.toUpperCase())
              )
              const doneOrders = des.orders.filter((o) =>
                ['DONE', 'SKIPPED'].includes(o.state.toUpperCase())
              )

              return (
                <div
                  key={des.id}
                  className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden transition-all hover:border-slate-300"
                >
                  {/* Designer Header Card */}
                  <div className="p-5 border-b border-slate-100 bg-slate-50/60 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                    <div className="flex items-center gap-3.5">
                      <div className="h-11 w-11 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 text-white font-bold flex items-center justify-center text-base shadow-sm shrink-0">
                        {des.full_name.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="font-bold text-sm text-slate-900">{des.full_name}</h3>
                          <span className="text-[11px] font-mono text-slate-400">(@{des.username})</span>
                          {des.printerval_designer_option && (
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-blue-50 text-[#0052CC] border border-blue-200">
                              Printerval: {des.printerval_designer_option}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500">
                          <span>Tổng: <strong className="font-mono text-slate-800">{des.total_orders}</strong> đơn</span>
                          <span>•</span>
                          <span className="text-blue-700 font-semibold">Doing: {des.doing_count}</span>
                          <span>•</span>
                          <span className="text-purple-700 font-semibold">Review: {des.review_count}</span>
                          <span>•</span>
                          <span className="text-orange-700 font-semibold">Fix: {des.fix_count}</span>
                          <span>•</span>
                          <span className="text-emerald-700 font-semibold">Done: {des.done_count}</span>
                        </div>
                      </div>
                    </div>

                    {/* Progress indicator */}
                    <div className="w-full md:w-56 shrink-0 space-y-1">
                      <div className="flex justify-between text-[11px] font-semibold text-slate-500">
                        <span>Hoàn thành</span>
                        <span className="font-mono font-bold text-emerald-600">{completionRate}%</span>
                      </div>
                      <div className="w-full h-2 rounded-full bg-slate-200 overflow-hidden">
                        <div
                          className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                          style={{ width: `${completionRate}%` }}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Orders Group Grid */}
                  <div className="p-5">
                    {des.orders.length === 0 ? (
                      <div className="py-6 text-center text-slate-400 text-xs font-medium">
                        Hiện chưa có đơn hàng nào được phân công cho Designer này.
                      </div>
                    ) : (
                      <div className={`grid grid-cols-1 ${showDoneColumn ? 'md:grid-cols-2 lg:grid-cols-4' : 'md:grid-cols-3'} gap-4`}>
                        {/* 1. Doing Column (Đang làm) */}
                        <div className="space-y-3">
                          <div className="flex items-center justify-between pb-2 border-b border-blue-200">
                            <span className="text-xs font-bold text-blue-800 flex items-center gap-1.5">
                              <span className="h-2 w-2 rounded-full bg-blue-500"></span>
                              <span>Doing (Đang Làm)</span>
                            </span>
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-blue-100 text-blue-800">
                              {doingOrders.length}
                            </span>
                          </div>

                          <div className="space-y-2.5 max-h-96 overflow-y-auto pr-1">
                            {doingOrders.length === 0 ? (
                              <div className="p-4 rounded-xl border border-dashed border-slate-200 text-center text-[11px] text-slate-400">
                                Không có đơn đang làm
                              </div>
                            ) : (
                              doingOrders.map((o) => (
                                <div
                                  key={o.id}
                                  className="p-3 rounded-xl border border-blue-100 bg-white hover:bg-blue-50/30 transition-all shadow-2xs space-y-2"
                                >
                                  <div className="flex items-start gap-2.5">
                                    {o.thumbnail_url ? (
                                      <img
                                        src={resolveAssetUrl(o.thumbnail_url)}
                                        alt=""
                                        onClick={() => setSelectedImage(o.thumbnail_url)}
                                        className="h-10 w-10 rounded-lg object-cover border border-slate-200 shrink-0 cursor-pointer hover:scale-105 transition-transform"
                                      />
                                    ) : (
                                      <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                                        <Package className="h-4 w-4" />
                                      </div>
                                    )}
                                    <div className="flex-1 min-w-0">
                                      <Link
                                        to={`/orders/${o.id}`}
                                        className="text-xs font-mono font-bold text-[#0052CC] hover:underline truncate block"
                                      >
                                        {o.external_order_id}
                                      </Link>
                                      <p className="text-[10px] text-slate-500 truncate mt-0.5">
                                        {o.product_name || 'Đơn 2D Custom'}
                                      </p>
                                      {o.deadline_at_ext && (
                                        <p className="text-[10px] text-slate-400 font-mono mt-0.5 flex items-center gap-1">
                                          <Clock className="h-2.5 w-2.5" />
                                          <span>{o.deadline_at_ext}</span>
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                  <div className="pt-1 flex items-center justify-between">
                                    <StatusDropdown
                                      orderId={o.id}
                                      externalOrderId={o.external_order_id}
                                      currentState={o.state}
                                    />
                                    <Link
                                      to={`/orders/${o.id}`}
                                      className="text-[10px] text-[#0052CC] font-semibold hover:underline flex items-center gap-0.5"
                                    >
                                      <span>Xem</span>
                                      <ChevronRight className="h-2.5 w-2.5" />
                                    </Link>
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        </div>

                        {/* 2. Review Column (Cần Admin duyệt - Nổi bật) */}
                        <div className="space-y-3">
                          <div className="flex items-center justify-between pb-2 border-b border-purple-200">
                            <span className="text-xs font-bold text-purple-800 flex items-center gap-1.5">
                              <span className="h-2 w-2 rounded-full bg-purple-500 animate-pulse"></span>
                              <span>Review (Chờ Duyệt)</span>
                            </span>
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-purple-100 text-purple-800">
                              {reviewOrders.length}
                            </span>
                          </div>

                          <div className="space-y-2.5 max-h-96 overflow-y-auto pr-1">
                            {reviewOrders.length === 0 ? (
                              <div className="p-4 rounded-xl border border-dashed border-slate-200 text-center text-[11px] text-slate-400">
                                Không có đơn chờ duyệt
                              </div>
                            ) : (
                              reviewOrders.map((o) => (
                                <div
                                  key={o.id}
                                  className="p-3 rounded-xl border border-purple-200 bg-purple-50/40 hover:bg-purple-50/80 transition-all shadow-2xs space-y-2.5"
                                >
                                  <div className="flex items-start gap-2.5">
                                    {o.thumbnail_url ? (
                                      <img
                                        src={resolveAssetUrl(o.thumbnail_url)}
                                        alt=""
                                        onClick={() => setSelectedImage(o.thumbnail_url)}
                                        className="h-12 w-12 rounded-lg object-cover border border-slate-200 shrink-0 cursor-pointer hover:scale-105 transition-transform"
                                      />
                                    ) : (
                                      <div className="h-12 w-12 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                                        <Package className="h-5 w-5" />
                                      </div>
                                    )}
                                    <div className="flex-1 min-w-0">
                                      <Link
                                        to={`/orders/${o.id}`}
                                        className="text-xs font-mono font-bold text-[#0052CC] hover:underline truncate block"
                                      >
                                        {o.external_order_id}
                                      </Link>
                                      <p className="text-[10px] text-slate-500 truncate mt-0.5">
                                        {o.product_name || 'Đơn 2D Custom'}
                                      </p>
                                      {o.deadline_at_ext && (
                                        <p className="text-[10px] text-slate-400 font-mono mt-0.5 flex items-center gap-1">
                                          <Clock className="h-2.5 w-2.5" />
                                          <span>{o.deadline_at_ext}</span>
                                        </p>
                                      )}
                                    </div>
                                  </div>

                                  {/* Quick Admin Actions for Review */}
                                  <div className="pt-1.5 border-t border-purple-100 flex items-center gap-1.5">
                                    <button
                                      onClick={() => handleQuickState(o.id, 'DONE')}
                                      disabled={actionLoadingId === o.id}
                                      className="flex-1 inline-flex items-center justify-center gap-1 px-2 py-1 text-[11px] font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-all shadow-2xs cursor-pointer disabled:opacity-50"
                                      title="Duyệt bài hoàn thành (Done)"
                                    >
                                      <Check className="h-3 w-3" />
                                      <span>Duyệt Done</span>
                                    </button>

                                    <button
                                      onClick={() => handleQuickState(o.id, 'REVISION')}
                                      disabled={actionLoadingId === o.id}
                                      className="flex-1 inline-flex items-center justify-center gap-1 px-2 py-1 text-[11px] font-bold text-white bg-orange-500 hover:bg-orange-600 rounded-lg transition-all shadow-2xs cursor-pointer disabled:opacity-50"
                                      title="Yêu cầu Des sửa lại bài (Fix)"
                                    >
                                      <Flame className="h-3 w-3" />
                                      <span>Bắt Fix</span>
                                    </button>
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        </div>

                        {/* 3. Fix Column (Cần Des sửa) */}
                        <div className="space-y-3">
                          <div className="flex items-center justify-between pb-2 border-b border-orange-200">
                            <span className="text-xs font-bold text-orange-800 flex items-center gap-1.5">
                              <span className="h-2 w-2 rounded-full bg-orange-500"></span>
                              <span>Fix (Cần Sửa Lại)</span>
                            </span>
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-orange-100 text-orange-800">
                              {fixOrders.length}
                            </span>
                          </div>

                          <div className="space-y-2.5 max-h-96 overflow-y-auto pr-1">
                            {fixOrders.length === 0 ? (
                              <div className="p-4 rounded-xl border border-dashed border-slate-200 text-center text-[11px] text-slate-400">
                                Không có đơn cần sửa
                              </div>
                            ) : (
                              fixOrders.map((o) => (
                                <div
                                  key={o.id}
                                  className="p-3 rounded-xl border border-orange-200 bg-orange-50/40 hover:bg-orange-50/80 transition-all shadow-2xs space-y-2"
                                >
                                  <div className="flex items-start gap-2.5">
                                    {o.thumbnail_url ? (
                                      <img
                                        src={resolveAssetUrl(o.thumbnail_url)}
                                        alt=""
                                        onClick={() => setSelectedImage(o.thumbnail_url)}
                                        className="h-10 w-10 rounded-lg object-cover border border-slate-200 shrink-0 cursor-pointer"
                                      />
                                    ) : (
                                      <div className="h-10 w-10 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                                        <Package className="h-4 w-4" />
                                      </div>
                                    )}
                                    <div className="flex-1 min-w-0">
                                      <Link
                                        to={`/orders/${o.id}`}
                                        className="text-xs font-mono font-bold text-[#0052CC] hover:underline truncate block"
                                      >
                                        {o.external_order_id}
                                      </Link>
                                      <p className="text-[10px] text-slate-500 truncate mt-0.5">
                                        {o.product_name || 'Đơn 2D Custom'}
                                      </p>
                                      {o.deadline_at_ext && (
                                        <p className="text-[10px] text-slate-400 font-mono mt-0.5 flex items-center gap-1">
                                          <Clock className="h-2.5 w-2.5" />
                                          <span>{o.deadline_at_ext}</span>
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                  <div className="pt-1 flex items-center justify-between">
                                    <StatusDropdown
                                      orderId={o.id}
                                      externalOrderId={o.external_order_id}
                                      currentState={o.state}
                                    />
                                    <Link
                                      to={`/orders/${o.id}`}
                                      className="text-[10px] text-[#0052CC] font-semibold hover:underline flex items-center gap-0.5"
                                    >
                                      <span>Xem</span>
                                      <ChevronRight className="h-2.5 w-2.5" />
                                    </Link>
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        </div>

                        {/* 4. Done Column (Đã xong) */}
                        {showDoneColumn && (
                          <div className="space-y-3">
                            <div className="flex items-center justify-between pb-2 border-b border-emerald-200">
                              <span className="text-xs font-bold text-emerald-800 flex items-center gap-1.5">
                                <span className="h-2 w-2 rounded-full bg-emerald-500"></span>
                                <span>Done (Hoàn Thành)</span>
                              </span>
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800">
                                {doneOrders.length}
                              </span>
                            </div>

                            <div className="space-y-2.5 max-h-96 overflow-y-auto pr-1">
                              {doneOrders.length === 0 ? (
                                <div className="p-4 rounded-xl border border-dashed border-slate-200 text-center text-[11px] text-slate-400">
                                  Chưa có đơn hoàn thành
                                </div>
                              ) : (
                                doneOrders.slice(0, 10).map((o) => (
                                  <div
                                    key={o.id}
                                    className="p-3 rounded-xl border border-emerald-100 bg-white hover:bg-emerald-50/20 transition-all shadow-2xs space-y-2"
                                  >
                                    <div className="flex items-start gap-2.5">
                                      {o.thumbnail_url ? (
                                        <img
                                          src={resolveAssetUrl(o.thumbnail_url)}
                                          alt=""
                                          onClick={() => setSelectedImage(o.thumbnail_url)}
                                          className="h-10 w-10 rounded-lg object-cover border border-slate-200 shrink-0 cursor-pointer"
                                        />
                                      ) : (
                                        <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                                          <Package className="h-4 w-4" />
                                        </div>
                                      )}
                                      <div className="flex-1 min-w-0">
                                        <Link
                                          to={`/orders/${o.id}`}
                                          className="text-xs font-mono font-bold text-emerald-700 hover:underline truncate block"
                                        >
                                          {o.external_order_id}
                                        </Link>
                                        <p className="text-[10px] text-slate-400 truncate mt-0.5">
                                          {o.product_name || 'Đơn 2D Custom'}
                                        </p>
                                      </div>
                                    </div>
                                    <div className="pt-1 flex items-center justify-between">
                                      <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-md border border-emerald-200">
                                        <CheckCheck className="h-3 w-3" />
                                        <span>Đã xong</span>
                                      </span>
                                      <Link
                                        to={`/orders/${o.id}`}
                                        className="text-[10px] text-slate-400 hover:text-slate-700 font-semibold hover:underline"
                                      >
                                        Chi tiết
                                      </Link>
                                    </div>
                                  </div>
                                ))
                              )}
                              {doneOrders.length > 10 && (
                                <div className="text-center text-[10px] text-slate-400 pt-1 font-medium">
                                  + {doneOrders.length - 10} đơn hoàn thành khác
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <ImageModal
        isOpen={Boolean(selectedImage)}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
      />
    </DashboardLayout>
  )
}
