import { ExternalLink } from 'lucide-react'
import { resolveAssetUrl } from '../api/client'
import { resolveExternalUrl } from '../utils/statusTranslation'

// Full links, and Tacahu's image-proxy paths (QC images in a Fix note, shown as "Ảnh 1, Ảnh 2…").
const URL_PATTERN = /(https?:\/\/[^\s<>"']+|\/api\/assets\/proxy\?u=[A-Za-z0-9_=-]+)/g
const PROXY_PATH = /^\/api\/assets\/proxy\?u=/

type LinkifiedTextProps = {
  text: string
  linkClassName?: string
}

export function LinkifiedText({ text, linkClassName = 'font-semibold text-[#0052CC] underline underline-offset-2 hover:text-[#003D99]' }: LinkifiedTextProps) {
  const parts = text.split(URL_PATTERN)
  let imageCount = 0

  return (
    <>
      {parts.map((part, index) => {
        if (PROXY_PATH.test(part)) {
          imageCount += 1
          return (
            <a key={`img-${index}`} href={resolveAssetUrl(part)} target="_blank" rel="noopener noreferrer"
              className={linkClassName} title="Mở ảnh ở tab mới">
              Ảnh {imageCount}
            </a>
          )
        }
        const url = resolveExternalUrl(part)
        if (!url) return <span key={`text-${index}`}>{part}</span>

        return (
          <a
            key={`url-${index}`}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className={linkClassName}
            title="Mở link ở tab mới"
          >
            {part}
          </a>
        )
      })}
    </>
  )
}

export function OpenExternalLinkButton({ url, label = 'Mở link' }: { url: string | null | undefined; label?: string }) {
  const validUrl = resolveExternalUrl(url)
  if (!validUrl) return null

  return (
    <a
      href={validUrl}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => event.stopPropagation()}
      className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2 py-1.5 text-[11px] font-bold text-[#0052CC] transition-colors hover:bg-blue-100"
      title="Mở link ở tab mới"
    >
      <ExternalLink className="h-3 w-3" />
      <span>{label}</span>
    </a>
  )
}
