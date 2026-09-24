import { Cpu, Loader2 } from 'lucide-react'
import { useWorker } from './WorkerProvider'

/** Asked once per login, on the machine that runs the agent. */
export function ConsentDialog() {
  const { agent, busy, allow, decline } = useWorker()
  if (!agent) return null
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-[1px]" role="dialog" aria-modal="true" aria-label="Cho phép dùng máy này">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center gap-3">
          <div className="rounded-lg bg-blue-600 p-2 text-white shadow-sm">
            <Cpu className="h-5 w-5" />
          </div>
          <h2 className="text-base font-bold text-slate-900">Cho phép dùng máy này để chạy hàng đợi?</h2>
        </div>
        <p className="text-sm leading-relaxed text-slate-600">
          Hệ thống muốn dùng <b>GPU/CPU</b> của máy <b>{agent.name}</b> để so sánh ảnh các job đang chờ kiểm tra trùng.
          Máy chỉ chạy trong phiên đăng nhập này: đăng xuất hoặc đóng web thì máy tự dừng.
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={decline}
            disabled={busy}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
          >
            Không
          </button>
          <button
            type="button"
            onClick={() => void allow()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50"
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}Có
          </button>
        </div>
      </div>
    </div>
  )
}
