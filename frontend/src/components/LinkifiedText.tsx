import { ExternalLink } from 'lucide-react'
import { resolveExternalUrl } from '../utils/statusTranslation'

const URL_PATTERN = /(https?:\/\/[^\s<>"']+)/g

type LinkifiedTextProps = {
  text: string
  linkClassName?: string
}

export function LinkifiedText({ text, linkClassName = 'font-semibold text-[#0052CC] underline underline-offset-2 hover:text-[#003D99]' }: LinkifiedTextProps) {
  const parts = text.split(URL_PATTERN)

  return (
    <>
      {parts.map((part, index) => {
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
