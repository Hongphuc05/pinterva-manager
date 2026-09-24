export type ReviewStatus = 'pending_review' | 'selected_duplicate' | 'ai_wrong' | 'no_match'

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
  custom_config?: CustomConfig | null
  candidates: Candidate[]
}

export type TabKey = 'todo' | 'done' | 'nomatch'

export const isTodo = (i: Item) => i.review_status === 'pending_review'
export const isDone = (i: Item) => i.review_status === 'selected_duplicate' || i.review_status === 'ai_wrong'
export const isNoMatch = (i: Item) => i.review_status === 'no_match'

/** A pair already sent to Telegram is frozen. */
export const isSent = (i: Item) =>
  i.candidates.some((c) => c.id === i.selected_candidate_id && c.sent_to_telegram)

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

export type DeviceState = 'idle' | 'busy' | 'paused' | 'offline' | 'revoked'

export interface WorkerDevice {
  id: string
  machine_name: string
  state: DeviceState
  user_name: string | null
  busy_with: string | null
  last_seen_at: string | null
  presence_at: string | null
}

export interface QueueJob {
  id: string
  status: string
  requested_count: number
  processed_count: number
  duplicate_count: number
  error_count: number
  requested_by: string | null
  worker_name: string | null
  created_at: string | null
  started_at: string | null
  heartbeat_at: string | null
  finished_at: string | null
  last_error: string | null
  position?: number
}

export interface QueueSearch {
  id: string
  filename: string | null
  status: string
  requested_by: string | null
  created_at: string | null
  finished_at: string | null
  last_error: string | null
}

export interface QueueState {
  workers: { ready: number; paused: number; offline: number; devices: WorkerDevice[] }
  running: QueueJob[]
  queued: QueueJob[]
  searches: QueueSearch[]
  recent: QueueJob[]
}
