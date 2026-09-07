export type StateInfo = {
  label: string
  description: string
  badgeClass: string
}

export const STATE_MAP: Record<string, StateInfo> = {
  DISCOVERED: {
    label: 'Đã Quét (Chờ xử lý)',
    description: 'Đơn hàng vừa được phát hiện qua hệ thống quét Printerval, chờ phân bổ hoặc claim.',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-200',
  },
  OPEN_FOR_ALLOCATION: {
    label: 'Mở Phân Bổ',
    description: 'Đơn hàng sẵn sàng để Admin phân công cho Designer đảm nhận.',
    badgeClass: 'bg-amber-100 text-amber-800 border-amber-200',
  },
  ASSIGNED: {
    label: 'Đã Phân Công',
    description: 'Đơn hàng đã được giao cho Designer cụ thể.',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-200',
  },
  IN_PROGRESS: {
    label: 'Đang Thực Hiện',
    description: 'Designer đang thiết kế / xử lý công việc.',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-200',
  },
  SUBMITTING_TO_SITE: {
    label: 'Đang Gửi Printerval',
    description: 'Đang đẩy link kết quả thiết kế lên hệ thống Printerval.',
    badgeClass: 'bg-indigo-100 text-indigo-800 border-indigo-200',
  },
  CLAIMED_IMPORTED: {
    label: 'Đã Claim (Nhập kho)',
    description: 'Đã nhận đơn thành công trên Printerval và nhập thông tin đầy đủ.',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  },
  DONE: {
    label: 'Hoàn Thành',
    description: 'Đơn hàng đã hoàn tất toàn bộ quy trình.',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  },
  CANCELLED: {
    label: 'Đã Hủy',
    description: 'Đơn hàng đã bị hủy bỏ.',
    badgeClass: 'bg-red-100 text-red-800 border-red-200',
  },
  EXCEPTION: {
    label: 'Ngoại Lệ / Lỗi',
    description: 'Đơn gặp lỗi hoặc sự cố, cần Admin kiểm tra thủ công.',
    badgeClass: 'bg-red-100 text-red-800 border-red-200',
  },
  ASSIGNMENT_PENDING_APPROVAL: {
    label: 'Chờ Duyệt Phân Công',
    description: 'Đơn đang trong quá trình chờ phê duyệt phân công.',
    badgeClass: 'bg-purple-100 text-purple-800 border-purple-200',
  },
  QC_PENDING: {
    label: 'Chờ Kiểm Hàng (QC)',
    description: 'Kết quả thiết kế đang chờ kiểm tra chất lượng (QC).',
    badgeClass: 'bg-cyan-100 text-cyan-800 border-cyan-200',
  },
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
