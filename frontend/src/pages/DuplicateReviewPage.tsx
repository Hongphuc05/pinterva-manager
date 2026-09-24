import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ClipboardCheck, History, Loader2, Lock, ScanSearch, Search, Settings, type LucideIcon } from 'lucide-react'
import { fetchAccess, LOCKED_EVENT, setReviewToken } from '../features/dupReview/access'
import { LockScreen } from '../features/dupReview/components/LockScreen'
import { Lightbox } from '../features/dupReview/components/Lightbox'
import { SearchPage } from '../features/dupReview/components/SearchPage'
import { useSearchHistory } from '../features/dupReview/hooks'
import { JobsView } from '../features/dupReview/views/JobsView'
import { ReviewView } from '../features/dupReview/views/ReviewView'
import { SettingsView } from '../features/dupReview/views/SettingsView'

type TabId = 'review' | 'search' | 'jobs' | 'settings'

const NAV: { id: TabId; label: string; icon: LucideIcon }[] = [
  { id: 'review', label: 'Duyệt kết quả', icon: ClipboardCheck },
  { id: 'search', label: 'Tìm ảnh', icon: Search },
  { id: 'jobs', label: 'Lịch sử job', icon: History },
  { id: 'settings', label: 'Cài đặt', icon: Settings },
]

type Access = 'loading' | 'setup' | 'locked' | 'unlocked'

/**
 * Hidden area of the Support role (no menu entry; opened by address). It has its own password,
 * changeable inside, and its own layout: a job/duplicate management console, not a dashboard page.
 */
export function DuplicateReviewPage() {
  const [access, setAccess] = useState<Access>('loading')

  const check = useCallback(async () => {
    try {
      const state = await fetchAccess()
      setAccess(!state.has_password ? 'setup' : state.unlocked ? 'unlocked' : 'locked')
    } catch {
      setAccess('locked')
    }
  }, [])

  useEffect(() => {
    void check()
    const onLocked = () => setAccess('locked')
    window.addEventListener(LOCKED_EVENT, onLocked)
    return () => window.removeEventListener(LOCKED_EVENT, onLocked)
  }, [check])

  if (access === 'loading') {
    return (
      <div className="grid min-h-[100dvh] place-items-center bg-slate-50 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    )
  }
  if (access !== 'unlocked') return <LockScreen firstUse={access === 'setup'} onUnlocked={() => setAccess('unlocked')} />
  return (
    <Console
      onLock={() => {
        setReviewToken(null)
        setAccess('locked')
      }}
    />
  )
}

function Console({ onLock }: { onLock: () => void }) {
  const [params, setParams] = useSearchParams()
  const [zoom, setZoom] = useState<string | null>(null)
  const searchHistory = useSearchHistory() // lives here so a search survives switching tabs
  const requested = params.get('tab')
  const tab: TabId = NAV.some((n) => n.id === requested) ? (requested as TabId) : 'review'
  const jobId = params.get('job')

  const go = (next: TabId, job?: string | null) => {
    const copy = new URLSearchParams()
    if (next !== 'review') copy.set('tab', next)
    if (job) copy.set('job', job)
    setParams(copy, { replace: false })
  }

  return (
    <div className="min-h-[100dvh] bg-slate-50 text-[13px] text-slate-900">
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-slate-200 bg-white px-4 shadow-sm md:px-6">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-blue-600 p-2 text-white shadow-sm">
            <ScanSearch className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-base font-bold leading-tight text-slate-900">Quản lý trùng lặp</h1>
            <p className="hidden text-[11px] font-medium text-slate-500 sm:block">Khu vực riêng của Support</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/orders"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            <ArrowLeft className="h-3.5 w-3.5" />Về hệ thống
          </Link>
          <button
            type="button"
            onClick={onLock}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white shadow-sm transition hover:bg-slate-700"
          >
            <Lock className="h-3.5 w-3.5" />Khóa
          </button>
        </div>
      </header>

      <div className="mx-auto flex max-w-[1500px] flex-col gap-4 p-4 md:flex-row md:p-6">
        <nav aria-label="Chức năng" className="md:sticky md:top-20 md:w-52 md:flex-none md:self-start">
          <ul role="tablist" className="flex gap-1 overflow-x-auto md:flex-col">
            {NAV.map(({ id, label, icon: Icon }) => (
              <li key={id} className="flex-none md:flex-auto">
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => go(id)}
                  className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-semibold transition ${
                    tab === id ? 'bg-blue-600 text-white shadow-sm' : 'text-slate-600 hover:bg-white hover:text-slate-900'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <main className="min-w-0 flex-1">
          {tab === 'review' && (
            <ReviewView jobId={jobId} onJobChange={(id) => go('review', id)} onZoom={setZoom} zoomOpen={zoom !== null} />
          )}
          {tab === 'search' && <SearchPage history={searchHistory} onZoom={setZoom} />}
          {tab === 'jobs' && <JobsView onOpen={(id) => go('review', id)} />}
          {tab === 'settings' && <SettingsView onLock={onLock} />}
        </main>
      </div>
      <Lightbox src={zoom} onClose={() => setZoom(null)} />
    </div>
  )
}
