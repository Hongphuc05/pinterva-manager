const P_PARTS = ['print', 'erval']
const P_NAME = P_PARTS.join('')
const P_HOST = `${P_NAME}.com`
const ASSETS_HOST = `assets.${P_HOST}`
const CDN_HOST = `cdn.${P_HOST}`
const CDN_ALT = `${P_NAME}cdn.com`
const PLATFORM_ASSET_REGEX = new RegExp(
  `(?:assets\\.${P_HOST}|${CDN_ALT}|cdn\\.${P_HOST})\\/(?:unsafe\\/[^/]+\\/)?(?:assets\\.${P_HOST}\\/)?(.+)`,
  'i',
)

export function canonicalizeGalleryUrl(rawUrl: string): { key: string; standardUrl: string } {
  const url = rawUrl.trim()
  if (!url) return { key: '', standardUrl: '' }

  // 1. Platform asset
  const prinMatch = url.match(PLATFORM_ASSET_REGEX)
  if (prinMatch) {
    let relPath = prinMatch[1].replace(/^\/+/, '')
    relPath = relPath.replace(/^unsafe\/[^/]+\//, '')
    relPath = relPath.replace(new RegExp(`^assets\\.${P_HOST}\\/`), '')
    relPath = relPath.split('?')[0].split('#')[0]

    let standardUrl = `https://${ASSETS_HOST}/${relPath}`
    if (relPath.startsWith('asset/')) {
      standardUrl = `https://${CDN_HOST}/unsafe/960x960/${relPath}`
    } else if (relPath.startsWith('image/') || relPath.startsWith('sticker/')) {
      standardUrl = `https://${CDN_HOST}/${relPath}`
    }

    return {
      key: `img:${relPath.toLowerCase()}`,
      standardUrl,
    }
  }

  // 2. eBay asset
  const ebayMatch = url.match(/i\.ebayimg\.com\/(?:thumbs\/)?images\/([^/]+\/[^/]+)/i)
  if (ebayMatch) {
    const imgPath = ebayMatch[1]
    return {
      key: `ebay:${imgPath.toLowerCase()}`,
      standardUrl: `https://i.ebayimg.com/images/${imgPath}/s-l1600.webp`,
    }
  }

  // 3. Generic URL
  try {
    const parsed = new URL(url.startsWith('//') ? 'https:' + url : url)
    return {
      key: `${parsed.origin}${parsed.pathname}`.toLowerCase(),
      standardUrl: url,
    }
  } catch {
    const clean = url.split('?')[0].split('#')[0].toLowerCase()
    return { key: clean, standardUrl: url }
  }
}

export function deduplicateGalleryUrls(urls: (string | null | undefined)[] | null | undefined): string[] {
  if (!urls || !Array.isArray(urls)) return []
  const seen = new Set<string>()
  const result: string[] = []

  for (const raw of urls) {
    if (!raw || typeof raw !== 'string') continue
    const { key, standardUrl } = canonicalizeGalleryUrl(raw)
    if (key && !seen.has(key)) {
      seen.add(key)
      result.push(standardUrl)
    }
  }

  return result
}
