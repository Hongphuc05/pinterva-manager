export type StateInfo = {
  label: string
  description: string
  badgeClass: string
}

export const STATE_MAP: Record<string, StateInfo> = {
  OPEN: {
    label: 'Chờ phân công',
    description: 'Đơn hàng vừa cào về hoặc đã nhập kho, sẵn sàng để giao cho Designer.',
    badgeClass: 'bg-amber-100 text-amber-800 border-amber-200',
  },
  IN_PROGRESS: {
    label: 'Đang làm',
    description: 'Đã giao cho Designer và Designer đang làm bài thiết kế.',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-200',
  },
  QC_PENDING: {
    label: 'Chờ duyệt (QC)',
    description: 'Designer đã nộp bài (link Drive), đang chờ Admin kiểm tra hoặc đẩy lên Printerval.',
    badgeClass: 'bg-purple-100 text-purple-800 border-purple-200',
  },
  REVISION: {
    label: 'Yêu cầu sửa',
    description: 'Admin kiểm tra bài chưa đạt và yêu cầu Designer sửa lại.',
    badgeClass: 'bg-orange-100 text-orange-800 border-orange-200',
  },
  DONE: {
    label: 'Hoàn thành',
    description: 'Đơn hàng đã hoàn tất 100% quy trình.',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  },
  CANCELLED: {
    label: 'Đã hủy',
    description: 'Đơn hàng đã bị hủy bỏ.',
    badgeClass: 'bg-gray-100 text-gray-700 border-gray-200',
  },
  EXCEPTION: {
    label: 'Lỗi / Ngoại lệ',
    description: 'Đơn gặp sự cố cào dữ liệu hoặc lỗi cần Admin kiểm tra.',
    badgeClass: 'bg-red-100 text-red-800 border-red-200',
  },
  // Legacy compatibility mappings
  DISCOVERED: { label: 'Chờ phân công', description: 'Đơn hàng vừa cào về', badgeClass: 'bg-amber-100 text-amber-800 border-amber-200' },
  CLAIMED_IMPORTED: { label: 'Chờ phân công', description: 'Đã nhập kho', badgeClass: 'bg-amber-100 text-amber-800 border-amber-200' },
  OPEN_FOR_ALLOCATION: { label: 'Chờ phân công', description: 'Sẵn sàng phân công', badgeClass: 'bg-amber-100 text-amber-800 border-amber-200' },
  ASSIGNMENT_PENDING_APPROVAL: { label: 'Chờ phân công', description: 'Chờ duyệt gán', badgeClass: 'bg-amber-100 text-amber-800 border-amber-200' },
  ASSIGNED: { label: 'Đang làm', description: 'Đã phân công', badgeClass: 'bg-blue-100 text-blue-800 border-blue-200' },
  RESULT_SUBMITTED: { label: 'Chờ duyệt (QC)', description: 'Đã nộp kết quả', badgeClass: 'bg-purple-100 text-purple-800 border-purple-200' },
  SUBMITTING_TO_SITE: { label: 'Chờ duyệt (QC)', description: 'Đang đẩy Printerval', badgeClass: 'bg-purple-100 text-purple-800 border-purple-200' },
  REASSIGNMENT_REQUIRED: { label: 'Lỗi / Ngoại lệ', description: 'Cần gán lại', badgeClass: 'bg-red-100 text-red-800 border-red-200' },
  REVISION_REQUESTED: { label: 'Yêu cầu sửa', description: 'Cần sửa lại', badgeClass: 'bg-orange-100 text-orange-800 border-orange-200' },
  SKIPPED: { label: 'Hoàn thành', description: 'Đã hoàn tất', badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200' },
}

export function getStatusInfo(state: string): StateInfo {
  return (
    STATE_MAP[state] ?? {
      label: state,
      description: 'Trạng thái xử lý hệ thống',
      badgeClass: 'bg-slate-100 text-slate-700 border-slate-200',
    }
  )
}

// The 6 real site statuses on Printerval itself (docs/phase0-field-map.md §1),
// mirrored read-only into Order.printerval_status — distinct from STATE_MAP above,
// which is this app's own internal workflow state.
export const PRINTERVAL_STATUS_MAP: Record<string, StateInfo> = {
  waiting: {
    label: 'Waiting',
    description: 'Chưa có designer nhận trên Printerval.',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-200',
  },
  doing: {
    label: 'Doing',
    description: 'Đang được làm trên Printerval.',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-200',
  },
  review: {
    label: 'Review',
    description: 'Đã nộp, đang chờ xét duyệt trên Printerval.',
    badgeClass: 'bg-indigo-100 text-indigo-800 border-indigo-200',
  },
  fix: {
    label: 'Fix',
    description: 'Bị yêu cầu sửa lại (trừ điểm designer trên Printerval).',
    badgeClass: 'bg-red-100 text-red-800 border-red-200',
  },
  confirm: {
    label: 'Confirm',
    description: 'Đã xác nhận, chờ bước cuối trên Printerval.',
    badgeClass: 'bg-purple-100 text-purple-800 border-purple-200',
  },
  done: {
    label: 'Done',
    description: 'Đã hoàn tất trên Printerval.',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  },
}

export function getPrintervalStatusInfo(status: string | null): StateInfo {
  if (!status) {
    return {
      label: 'Chưa đồng bộ',
      description: 'Chưa đồng bộ được trạng thái thật từ Printerval cho đơn này.',
      badgeClass: 'bg-slate-50 text-slate-400 border-slate-200',
    }
  }
  return (
    PRINTERVAL_STATUS_MAP[status] ?? {
      label: status,
      description: 'Trạng thái thật trên Printerval',
      badgeClass: 'bg-slate-100 text-slate-700 border-slate-200',
    }
  )
}
