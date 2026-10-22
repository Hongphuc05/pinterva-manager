import { useState } from 'react'
import { LayoutTemplate } from 'lucide-react'
import { resolveAssetUrl } from '../api/client'
import { ImageModal } from './ImageModal'
import { LinkifiedText, OpenExternalLinkButton } from './LinkifiedText'

export type JobTemplate = {
  url: string | null
  note: string | null
  image_url: string | null
}

/** The templates of the job: preview image, PSD folder link and the note beside it. */
export function JobTemplatesCard({ templates }: { templates?: JobTemplate[] | null }) {
  const [zoomed, setZoomed] = useState<string | null>(null)
  if (!templates?.length) return null

  return (
    <section aria-label="Template của job" className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-xs">
      <h3 className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-slate-800">
        <LayoutTemplate className="h-4 w-4 text-[#0052CC]" />
        <span>Template của job</span>
        <span className="rounded-full bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">{templates.length}</span>
      </h3>
      <ul className="space-y-2">
        {templates.map((template, index) => (
          <li key={`${template.url ?? template.image_url}-${index}`} className="flex gap-3 rounded-lg border border-slate-200 p-2.5">
            {template.image_url ? (
              <button type="button" onClick={() => setZoomed(resolveAssetUrl(template.image_url!))} aria-label="Xem ảnh template"
                className="h-24 w-24 shrink-0 cursor-zoom-in overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                <img src={resolveAssetUrl(template.image_url)} alt="Ảnh template" loading="lazy" className="h-full w-full object-contain" />
              </button>
            ) : (
              <div className="h-24 w-24 shrink-0 rounded-lg bg-slate-100" />
            )}
            <div className="min-w-0 flex-1 space-y-1.5">
              {template.url && (
                <div className="flex items-start gap-2">
                  <div className="min-w-0">
                    <div className="font-bold text-slate-700">Link PSD:</div>
                    <div className="break-all text-slate-800"><LinkifiedText text={template.url} /></div>
                  </div>
                  <OpenExternalLinkButton url={template.url} label="Mở" />
                </div>
              )}
              {template.note && (
                <div>
                  <span className="font-bold text-slate-700">Note: </span>
                  <span className="rounded bg-amber-50 px-1.5 py-0.5 text-slate-800">{template.note}</span>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
      <ImageModal isOpen={Boolean(zoomed)} imageUrl={zoomed ?? ''} altText="Template" hideExternalLink onClose={() => setZoomed(null)} />
    </section>
  )
}
