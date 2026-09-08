import { useState } from 'react'
import { CloudDownload, Download, ExternalLink, Copy, Check } from 'lucide-react'

export type SourceFile = {
  name: string
  url: string
}

type Props = {
  sourceFiles?: SourceFile[] | null
  downloadAllUrl?: string | null
}

export function SourceFilesCard({ sourceFiles, downloadAllUrl }: Props) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)

  if ((!sourceFiles || sourceFiles.length === 0) && !downloadAllUrl) {
    return null
  }

  function handleCopy(url: string, index: number) {
    navigator.clipboard.writeText(url)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  const filesCount = sourceFiles ? sourceFiles.length : 0

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-xs">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <CloudDownload className="h-4 w-4 text-[#0052CC]" />
          <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">SOURCE</h3>
        </div>
        {filesCount > 0 && (
          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-200 text-slate-700">
            {filesCount} file
          </span>
        )}
      </div>

      {/* List of files */}
      {sourceFiles && sourceFiles.length > 0 && (
        <div className="p-3 space-y-2 divide-y divide-slate-100 max-h-60 overflow-y-auto">
          {sourceFiles.map((file, i) => (
            <div key={i} className="pt-2 first:pt-0 flex items-center justify-between gap-2 text-xs">
              <a
                href={file.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 font-mono text-[#0052CC] hover:underline truncate max-w-[80%]"
                title={file.url}
              >
                <ExternalLink className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                <span className="truncate">{file.name}</span>
              </a>

              <button
                type="button"
                onClick={() => handleCopy(file.url, i)}
                className="p-1 rounded-md text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors shrink-0 cursor-pointer"
                title="Sao chép link ảnh"
              >
                {copiedIndex === i ? (
                  <Check className="h-3.5 w-3.5 text-emerald-600" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Download All Button */}
      {downloadAllUrl && (
        <div className="p-3 bg-slate-50 border-t border-slate-100">
          <a
            href={downloadAllUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl shadow-2xs transition-colors cursor-pointer"
          >
            <Download className="h-4 w-4" />
            <span>Download tất cả</span>
          </a>
        </div>
      )}
    </div>
  )
}
