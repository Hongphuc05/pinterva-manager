import { useState } from 'react'
import { CloudDownload, Download, Image as ImageIcon, Copy, Check } from 'lucide-react'
import { ImageModal } from './ImageModal'

export type SourceFile = {
  name: string
  url: string
}

type Props = {
  sourceFiles?: SourceFile[] | null
  downloadAllUrl?: string | null
  isAdmin?: boolean
}

export function SourceFilesCard({ sourceFiles, downloadAllUrl, isAdmin = false }: Props) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const [selectedImageUrl, setSelectedImageUrl] = useState<string | null>(null)
  const [selectedAltText, setSelectedAltText] = useState<string>('Source Image')
  const files = sourceFiles ?? []

  if (files.length === 0) {
    return null
  }

  function handleCopy(url: string, index: number) {
    navigator.clipboard.writeText(url)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  async function handleDownloadSingle(file: SourceFile) {
    try {
      const response = await fetch(file.url)
      if (!response.ok) throw new Error('download failed')
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = file.name
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(objectUrl)
    } catch {
      window.open(file.url, '_blank', 'noopener,noreferrer')
    }
  }

  const filesCount = files.length

  async function downloadAll() {
    if (downloadAllUrl && isAdmin) {
      window.open(downloadAllUrl, '_blank', 'noopener,noreferrer')
      return
    }
    for (const file of files) {
      await handleDownloadSingle(file)
    }
  }

  return (
    <>
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
        {files.length > 0 && (
          <div className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
            {files.map((file, i) => (
              <div key={i} className="flex items-center justify-between gap-2 px-4 py-3 text-xs">
                <button
                  type="button"
                  onClick={() => {
                    setSelectedImageUrl(file.url)
                    setSelectedAltText(file.name)
                  }}
                  className="flex items-center gap-1.5 font-mono text-[#0052CC] hover:underline truncate max-w-[70%] text-left cursor-pointer"
                  title="Click để xem ảnh trong modal"
                >
                  <ImageIcon className="h-3.5 w-3.5 shrink-0 text-blue-500" />
                  <span className="truncate">{file.name}</span>
                </button>

                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={() => handleDownloadSingle(file)}
                    className="p-1.5 rounded-md text-slate-500 hover:text-blue-600 hover:bg-blue-50 transition-colors cursor-pointer text-xs flex items-center gap-1"
                    title="Tải file này về máy"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span className="text-[10px] font-semibold hidden sm:inline">Tải về</span>
                  </button>

                  {isAdmin && (
                    <button
                      type="button"
                      onClick={() => handleCopy(file.url, i)}
                      className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
                      title="Sao chép link ảnh gốc (Admin)"
                    >
                      {copiedIndex === i ? (
                        <Check className="h-3.5 w-3.5 text-emerald-600" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" />
                      )}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Download All Button */}
        {(downloadAllUrl || filesCount > 0) && (
          <div className="p-3 bg-slate-50 border-t border-slate-100">
            <button
              type="button"
              onClick={downloadAll}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl shadow-2xs transition-colors cursor-pointer"
            >
              <Download className="h-4 w-4" />
              <span>Download tất cả</span>
            </button>
          </div>
        )}
      </div>

      <ImageModal
        isOpen={!!selectedImageUrl}
        onClose={() => setSelectedImageUrl(null)}
        imageUrl={selectedImageUrl}
        altText={selectedAltText}
        hideExternalLink={!isAdmin}
      />
    </>
  )
}
