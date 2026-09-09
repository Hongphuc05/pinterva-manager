import { X, ExternalLink, FileText, Download } from 'lucide-react'
import { resolveAssetUrl } from '../api/client'

export type PsdFile = {
  url?: string
  note?: string
  image_url?: string
}

export type TemplateJob = {
  id?: number
  provider_name?: string
  category_name?: string
  note?: string
  psd_file?: PsdFile[]
  state?: string
}

type TemplateModalProps = {
  isOpen: boolean
  onClose: () => void
  templateJobs?: TemplateJob[] | null
  orderId?: string
}

export function TemplateModal({ isOpen, onClose, templateJobs, orderId }: TemplateModalProps) {
  if (!isOpen) return null

  const items = templateJobs && templateJobs.length > 0 ? templateJobs : []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-2xl bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh] border border-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/70">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-[#0052CC]" />
            <h2 className="text-base font-bold text-slate-800">Template Details</h2>
            {orderId && <span className="text-xs font-mono font-semibold text-slate-500">({orderId})</span>}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-4 max-h-[75vh]">
          {items.length === 0 ? (
            <div className="text-center py-10 text-slate-400 font-medium text-xs space-y-2">
              <FileText className="h-10 w-10 mx-auto text-slate-300" />
              <p>Chưa có dữ liệu mẫu template cho đơn hàng này.</p>
            </div>
          ) : (
            items.map((job, idx) => (
              <div
                key={idx}
                className="rounded-xl border border-slate-200 bg-slate-50/40 p-4 space-y-3 shadow-2xs"
              >
                {/* Header Info */}
                <div className="space-y-1 text-xs">
                  <div className="font-semibold text-slate-800">
                    <strong>Nhà in: </strong>
                    <span className="text-slate-700">{job.provider_name || job.category_name || 'Lux-P'}</span>
                  </div>

                  {job.note && (
                    <div className="flex items-center gap-1.5 pt-0.5">
                      <strong className="text-slate-800">Note:</strong>
                      <span className="inline-block px-2 py-0.5 rounded bg-amber-100/80 text-amber-900 font-mono text-[11px]">
                        {job.note.replace(/<[^>]*>/g, '')}
                      </span>
                    </div>
                  )}
                </div>

                {/* PSD Files */}
                {job.psd_file && job.psd_file.length > 0 && (
                  <div className="space-y-3 pt-2">
                    {job.psd_file.map((psd, pIdx) => (
                      <div
                        key={pIdx}
                        className="flex flex-col sm:flex-row items-start gap-4 p-3 bg-white rounded-xl border border-slate-200 shadow-2xs"
                      >
                        {psd.image_url ? (
                          <img
                            src={resolveAssetUrl(psd.image_url)}
                            alt="PSD Preview"
                            className="h-24 w-24 rounded-lg object-cover border border-slate-200 shrink-0"
                          />
                        ) : (
                          <div className="h-24 w-24 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                            <Download className="h-8 w-8" />
                          </div>
                        )}

                        <div className="space-y-2 text-xs overflow-hidden flex-1">
                          {psd.url && (
                            <div>
                              <strong className="text-slate-800 block mb-1">Link Psd / Link template:</strong>
                              <a
                                href={psd.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[#0052CC] font-mono text-[11px] font-semibold hover:underline inline-flex items-center gap-1 break-all bg-blue-50/50 px-2 py-1 rounded border border-blue-100 max-w-full"
                              >
                                <span className="truncate">{psd.url}</span>
                                <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                              </a>
                            </div>
                          )}

                          {psd.note && (
                            <div className="pt-1">
                              <strong className="text-slate-800">Note: </strong>
                              <span className="inline-block px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-mono text-[10px] font-bold">
                                {psd.note}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end px-6 py-3 border-t border-slate-100 bg-slate-50">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-bold text-slate-700 bg-slate-200 hover:bg-slate-300 rounded-lg transition-colors cursor-pointer"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  )
}
