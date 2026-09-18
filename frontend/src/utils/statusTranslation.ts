export type StateInfo = {
  label: string
  description: string
  badgeClass: string
}

export const STATE_MAP: Record<string, StateInfo> = {
  OPEN: {
    label: 'Chờ nhận',
    description: 'Đang chờ được phân công.',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-300',
  },
  WAITING: {
    label: 'Chờ nhận',
    description: 'Đang chờ được phân công.',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-300',
  },
  IN_PROGRESS: {
    label: 'Đang làm',
    description: 'Designer đang thực hiện thiết kế.',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-300',
  },
  DOING: {
    label: 'Đang làm',
    description: 'Designer đang thực hiện thiết kế.',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-300',
  },
  QC_PENDING: {
    label: 'Chờ duyệt',
    description: 'Designer đã làm xong, đang chờ duyệt.',
    badgeClass: 'bg-purple-100 text-purple-800 border-purple-300',
  },
  REVIEW: {
    label: 'Chờ duyệt',
    description: 'Đang chờ duyệt bài thiết kế.',
    badgeClass: 'bg-purple-100 text-purple-800 border-purple-300',
  },
  REVISION: {
    label: 'Cần sửa',
    description: 'Yêu cầu Designer sửa lại bài.',
    badgeClass: 'bg-orange-100 text-orange-800 border-orange-300',
  },
  FIX: {
    label: 'Cần sửa',
    description: 'Yêu cầu Designer sửa lại bài.',
    badgeClass: 'bg-orange-100 text-orange-800 border-orange-300',
  },
  DONE: {
    label: 'Hoàn thành',
    description: 'Đơn hàng đã được duyệt hoàn tất 100%.',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  },
  CANCELLED: {
    label: 'Đã hủy',
    description: 'Đơn hàng đã bị hủy bỏ.',
    badgeClass: 'bg-gray-100 text-gray-700 border-gray-200',
  },
  EXCEPTION: {
    label: 'Lỗi / Ngoại lệ',
    description: 'Đơn gặp sự cố cào dữ liệu hoặc lỗi cần kiểm tra.',
    badgeClass: 'bg-red-100 text-red-800 border-red-200',
  },
  // Legacy compatibility mappings
  DISCOVERED: { label: 'Chờ nhận', description: 'Đang chờ được phân công', badgeClass: 'bg-slate-100 text-slate-700 border-slate-300' },
  CLAIMED_IMPORTED: { label: 'Chờ nhận', description: 'Đang chờ được phân công', badgeClass: 'bg-slate-100 text-slate-700 border-slate-300' },
  OPEN_FOR_ALLOCATION: { label: 'Chờ nhận', description: 'Đang chờ được phân công', badgeClass: 'bg-slate-100 text-slate-700 border-slate-300' },
  ASSIGNMENT_PENDING_APPROVAL: { label: 'Chờ nhận', description: 'Đang chờ được phân công', badgeClass: 'bg-slate-100 text-slate-700 border-slate-300' },
  ASSIGNED: { label: 'Chờ nhận', description: 'Đang chờ được phân công', badgeClass: 'bg-slate-100 text-slate-700 border-slate-300' },
  RESULT_SUBMITTED: { label: 'Chờ duyệt', description: 'Đã nộp kết quả', badgeClass: 'bg-purple-100 text-purple-800 border-purple-300' },
  SUBMITTING_TO_SITE: { label: 'Chờ duyệt', description: 'Đã nộp kết quả', badgeClass: 'bg-purple-100 text-purple-800 border-purple-300' },
  REASSIGNMENT_REQUIRED: { label: 'Lỗi / Ngoại lệ', description: 'Cần gán lại', badgeClass: 'bg-red-100 text-red-800 border-red-200' },
  REVISION_REQUESTED: { label: 'Cần sửa', description: 'Cần sửa lại', badgeClass: 'bg-orange-100 text-orange-800 border-orange-300' },
  SKIPPED: { label: 'Hoàn thành', description: 'Đã hoàn tất', badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-300' },
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
    description: 'Chưa có designer nhận trên Print.',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-200',
  },
  doing: {
    label: 'Doing',
    description: 'Đang được làm trên Print.',
    badgeClass: 'bg-blue-100 text-blue-800 border-blue-200',
  },
  review: {
    label: 'Review',
    description: 'Đã nộp, đang chờ xét duyệt trên Print.',
    badgeClass: 'bg-indigo-100 text-indigo-800 border-indigo-200',
  },
  fix: {
    label: 'Fix',
    description: 'Bị yêu cầu sửa lại (trừ điểm designer trên Print).',
    badgeClass: 'bg-red-100 text-red-800 border-red-200',
  },
  confirm: {
    label: 'Confirm',
    description: 'Đã xác nhận, chờ bước cuối trên Print.',
    badgeClass: 'bg-purple-100 text-purple-800 border-purple-200',
  },
  done: {
    label: 'Done',
    description: 'Đã hoàn tất trên Print.',
    badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  },
}

export function getPrintervalStatusInfo(status: string | null): StateInfo {
  if (!status) {
    return {
      label: 'Chưa đồng bộ',
      description: 'Chưa đồng bộ được trạng thái thật từ Print cho đơn này.',
      badgeClass: 'bg-slate-50 text-slate-400 border-slate-200',
    }
  }
  return (
    PRINTERVAL_STATUS_MAP[status] ?? {
      label: status,
      description: 'Trạng thái thật trên Print',
      badgeClass: 'bg-slate-100 text-slate-700 border-slate-200',
    }
  )
}

/**
 * Safely resolves and validates an external URL.
 * Returns the fully-qualified URL (e.g. "https://drive.google.com/...") if valid.
 * Returns null if the string is plain text/notes (e.g. "1", "Đã nộp bài") or empty.
 */
export function resolveExternalUrl(raw: string | null | undefined): string | null {
  if (!raw || typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed) return null

  // 1. If text contains a full http/https URL, extract it
  const fullUrlMatch = trimmed.match(/https?:\/\/[^\s<>"']+/)
  if (fullUrlMatch) {
    try {
      const parsed = new URL(fullUrlMatch[0])
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return parsed.href
      }
    } catch {
      // ignore
    }
  }

  // 2. Check if it's a domain-like string (e.g., drive.google.com/xxx, dropbox.com/xxx)
  // Must have a valid domain format ending in letters (e.g. .com, .vn, .org)
  const domainPattern = /^[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?:\/[^\s]*)?$/
  if (domainPattern.test(trimmed)) {
    try {
      const parsed = new URL(`https://${trimmed}`)
      if (parsed.hostname.includes('.') && !parsed.hostname.endsWith('.')) {
        return parsed.href
      }
    } catch {
      // ignore
    }
  }

  return null
}
