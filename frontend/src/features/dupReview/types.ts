export type ReviewStatus = 'pending_review' | 'selected_duplicate' | 'ai_wrong' | 'no_match'

/** Where a compared order stands in its lot (same values as the API `stage`). */
export type Stage = 'todo' | 'unsent' | 'waiting' | 'verified' | 'linked' | 'not_duplicate'

export interface Job {
  id: string
  status: string
  requested_count: number
  processed_count: number
  duplicate_count: number
  error_count: number
  run_id: string | null
  created_at: string | null
  finished_at: string | null
  stages?: Record<Stage, number>
}

export interface Candidate {
  id: string
  rank: number
  order_code: string | null
  product_name: string | null
  image_url: string
  similarity: number
  phash_distance: number | null
  ssim: number | null
  color_delta_e: number | null
  classification: string
  sent_to_telegram: boolean
  decision: string
  custom_config?: CustomConfig | null
}

export interface Item {
  id: string
  order_code: string
  product_name: string | null
  image_url: string
  model_says_duplicate: boolean
  review_status: ReviewStatus | null
  selected_candidate_id: string | null
  reviewed_at: string | null
  stage: Stage | null
  order_tag?: string | null
  /** Support may still tag this order: it is in Waiting and carries no tag yet. */
  taggable?: boolean
  decision?: string | null
  link?: string | null
  custom_config?: CustomConfig | null
  candidates: Candidate[]
}

export type TabKey = 'todo' | 'pending' | 'notdup' | 'link'

export const TAB_OF: Record<Stage, TabKey> = {
  todo: 'todo',
  unsent: 'pending',
  waiting: 'pending',
  verified: 'pending',
  not_duplicate: 'notdup',
  linked: 'link',
}

/** A pair already sent to Telegram is frozen. */
export const isSent = (i: Item) =>
  i.candidates.some((c) => c.id === i.selected_candidate_id && c.sent_to_telegram)

/** The choice can still be made or changed: not yet sent, not already settled by a tag, and the
 * model may have missed a duplicate ("Không thấy trùng") or been marked wrong. */
export const canReview = (i: Item) =>
  !isSent(i) &&
  i.order_tag !== 'duplicate' &&
  i.order_tag !== 'non_duplicate' &&
  (i.stage === 'todo' || i.stage === 'unsent' || i.review_status === 'ai_wrong' || i.review_status === 'no_match')

/** "Model sai" only makes sense while the model still claims a duplicate. */
export const canMarkModelWrong = (i: Item) => canReview(i) && i.review_status !== 'ai_wrong' && i.review_status !== 'no_match'

/** The name of a lot: how many orders and when it was made, e.g. "100 đơn · 09h00 · 13/10". */
export function lotName(job: Pick<Job, 'requested_count' | 'created_at'>): string {
  if (!job.created_at) return `${job.requested_count} đơn`
  const d = new Date(job.created_at)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${job.requested_count} đơn · ${pad(d.getHours())}h${pad(d.getMinutes())} · ${pad(d.getDate())}/${pad(d.getMonth() + 1)}`
}

export interface ConfigEntry {
  key: string
  value: string
}
export interface CustomConfig {
  original?: ConfigEntry[]
  translated_vn?: ConfigEntry[]
}

export interface SearchCandidate {
  rank: number
  order_code: string | null
  product_name: string | null
  image_url: string
  similarity: number
  phash_distance: number | null
  ssim: number | null
  color_delta_e: number | null
  classification: string
  reasons: string[]
  custom_config: CustomConfig | null
}

export interface SearchResult {
  verdict: string
  is_duplicate: boolean
  pool_count: number
  model_version: string
  elapsed_ms: number
  candidates: SearchCandidate[]
}

/** Design options worth showing: Vietnamese if present, minus internal pricing/preview keys. */
export function configEntries(config: CustomConfig | null | undefined): ConfigEntry[] {
  const list = (config?.translated_vn?.length ? config.translated_vn : config?.original) ?? []
  return list.filter((e) => e.key && !/^(extra_discount|url_)/i.test(e.key))
}
