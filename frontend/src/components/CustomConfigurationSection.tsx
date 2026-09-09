import { useState } from 'react'
import { Check, Copy, ExternalLink, Image, Languages, Link2, Sliders, Type } from 'lucide-react'

export type CustomConfigurationEntry = { key: string; value: string }
type Props = { entries: CustomConfigurationEntry[]; translated?: boolean }
type ImageEntry = { value?: unknown }
type TextEntry = { text?: unknown; font?: unknown }

function isUrl(value: string) { return /^https?:\/\//i.test(value) }
function filename(value: string) { try { return new URL(value).pathname.split('/').filter(Boolean).pop() || value } catch { return value } }
function parseList(value: string): unknown[] { try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed : [] } catch { return [] } }

// Orders crawled before the API mapper fix contain Python list syntax. Extract only
// the fields visible to the operator so those historic orders remain readable.
function legacyMatches(value: string, first: string, second?: string) {
  const pattern = (field: string) => new RegExp(`[\\"']${field}[\\"']\\s*:\\s*[\\"']([^\\"']+)[\\"']`, 'g')
  const one = [...value.matchAll(pattern(first))].map((match) => match[1])
  const two = second ? [...value.matchAll(pattern(second))].map((match) => match[1]) : []
  return one.map((item, index) => ({ first: item, second: two[index] }))
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() { await navigator.clipboard.writeText(value); setCopied(true); window.setTimeout(() => setCopied(false), 1800) }
  return <button type="button" onClick={copy} title="Sao chép link" className="rounded-md border border-slate-200 p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800">{copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}</button>
}

function FileValue({ url }: { url: string }) {
  return <div className="flex min-w-0 items-center gap-2"><a href={url} target="_blank" rel="noopener noreferrer" title={url} className="flex min-w-0 items-center gap-1.5 text-indigo-600 hover:underline"><ExternalLink className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{filename(url)}</span></a><CopyButton value={url} /></div>
}

function FieldCard({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="grid grid-cols-[80px_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-lg bg-slate-50 px-3 py-2.5 text-sm"><span className="font-semibold text-slate-600">{label}</span><div className="min-w-0">{children}</div></div>
}

function ImageList({ value }: { value: string }) {
  const parsed = parseList(value).map((item) => item as ImageEntry)
  const images = parsed.length ? parsed.map((item) => typeof item.value === 'string' ? item.value : '').filter(isUrl) : legacyMatches(value, 'value').map((item) => item.first).filter(isUrl)
  return <div className="space-y-2">{images.map((url, index) => <FieldCard key={`${url}-${index}`} label="type"><><span>image</span><FieldCard label="value"><FileValue url={url} /></FieldCard></></FieldCard>)}</div>
}

function TextList({ value }: { value: string }) {
  const parsed = parseList(value).map((item) => item as TextEntry)
  const values = parsed.length ? parsed.map((item) => ({ text: typeof item.text === 'string' ? item.text : '', font: typeof item.font === 'string' ? item.font : '' })) : legacyMatches(value, 'text', 'font').map((item) => ({ text: item.first, font: item.second || '' }))
  return <div className="space-y-2">{values.map((item, index) => <FieldCard key={`${item.text}-${index}`} label="text"><><span>{item.text || '—'}</span><FieldCard label="font">{item.font && isUrl(item.font) ? <FileValue url={item.font} /> : <span>{item.font || '—'}</span>}</FieldCard></></FieldCard>)}</div>
}

function SimpleValue({ value }: { value: string }) { return isUrl(value) ? <FileValue url={value} /> : <span className={value.toLowerCase() === 'true' ? 'font-medium text-emerald-700' : 'whitespace-pre-wrap break-words text-slate-700'}>{value || '—'}</span> }
function sectionIcon(key: string) { const n = key.toLowerCase(); if (n === 'images' || n === 'hình_ảnh') return <Image className="h-4 w-4" />; if (n === 'texts' || n === 'văn_bản') return <Type className="h-4 w-4" />; if (n.includes('url')) return <Link2 className="h-4 w-4" />; return null }

export function CustomConfigurationSection({ entries, translated = false }: Props) {
  const accent = translated ? 'border-indigo-200' : 'border-slate-200'
  const header = translated ? 'bg-indigo-50 text-indigo-700 border-indigo-200' : 'bg-slate-50 text-slate-800 border-slate-200'
  return <section className={`overflow-hidden rounded-xl border bg-white ${accent}`}><div className={`flex items-center gap-2 border-b px-4 py-3 text-xs font-bold uppercase tracking-wider ${header}`}>{translated ? <Languages className="h-4 w-4" /> : <Sliders className="h-4 w-4 text-[#0052CC]" />}<span>{translated ? 'Bản dịch tiếng Việt' : 'Cấu hình custom (Custom configurations)'}</span>{translated && <span className="ml-auto rounded-full bg-indigo-100 px-2 py-0.5 text-[10px]">VN</span>}</div><div className="max-h-[420px] overflow-y-auto">{entries.map((entry, index) => { const key = entry.key.toLowerCase(); const grouped = key === 'images' || key === 'hình_ảnh' || key === 'texts' || key === 'văn_bản'; return <div key={`${entry.key}-${index}`} className="border-b border-slate-100 last:border-b-0">{grouped ? <div className="p-4"><div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-indigo-600">{sectionIcon(entry.key)}<span>{entry.key}</span></div>{key === 'images' || key === 'hình_ảnh' ? <ImageList value={entry.value} /> : <TextList value={entry.value} />}</div> : <div className="grid grid-cols-[minmax(150px,1fr)_minmax(0,3fr)] gap-4 px-4 py-3 text-sm"><span className="flex items-center gap-2 font-mono font-semibold text-slate-600">{sectionIcon(entry.key)}{entry.key}</span><SimpleValue value={entry.value} /></div>}</div> })}</div></section>
}
