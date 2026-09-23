import { useMemo, type ReactNode } from 'react'

const ALLOWED_TAGS = new Set([
  'a',
  'b',
  'blockquote',
  'br',
  'code',
  'del',
  'em',
  'i',
  'ins',
  'pre',
  's',
  'span',
  'strike',
  'strong',
  'u',
])

function safeHref(value: string | null) {
  const href = value?.trim() || ''
  if (!href) return null

  try {
    const url = new URL(href, window.location.origin)
    if (url.protocol === 'http:' || url.protocol === 'https:' || url.protocol === 'tg:') {
      return href
    }
  } catch {
    // Invalid URLs are rendered as plain text instead of becoming links.
  }
  return null
}

function renderNode(node: Node, key: string): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.nodeValue
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null
  }

  const element = node as HTMLElement
  const tag = element.tagName.toLowerCase()
  const children = Array.from(element.childNodes).map((child, index) => renderNode(child, `${key}-${index}`))

  if (!ALLOWED_TAGS.has(tag)) {
    return children
  }

  if (tag === 'br') return <br key={key} />

  if (tag === 'a') {
    const href = safeHref(element.getAttribute('href'))
    if (!href) return children
    return (
      <a
        key={key}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[#0052CC] underline decoration-[#0052CC]/40 underline-offset-2"
      >
        {children}
      </a>
    )
  }

  if (tag === 'b' || tag === 'strong') return <strong key={key}>{children}</strong>
  if (tag === 'i' || tag === 'em') return <em key={key}>{children}</em>
  if (tag === 'u' || tag === 'ins') return <u key={key}>{children}</u>
  if (tag === 's' || tag === 'strike' || tag === 'del') return <s key={key}>{children}</s>
  if (tag === 'code') return <code key={key} className="rounded bg-slate-100 px-1 font-mono text-[0.95em]">{children}</code>
  if (tag === 'pre') return <pre key={key} className="overflow-x-auto whitespace-pre-wrap font-mono">{children}</pre>
  if (tag === 'blockquote') return <blockquote key={key} className="border-l-2 border-slate-300 pl-3 italic">{children}</blockquote>

  // Telegram spoiler markup uses either <tg-spoiler> or a span class. Keep
  // the content visible in the admin preview while discarding the class.
  return <span key={key}>{children}</span>
}

export function TelegramHtmlPreview({ html }: { html: string }) {
  const renderedNodes = useMemo(() => {
    if (!html) return []
    const parsed = new DOMParser().parseFromString(html, 'text/html')
    return Array.from(parsed.body.childNodes).map((node, index) => renderNode(node, `telegram-preview-${index}`))
  }, [html])

  return <>{renderedNodes}</>
}
