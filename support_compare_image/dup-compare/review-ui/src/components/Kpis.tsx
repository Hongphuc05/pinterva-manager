import { AlertTriangle, CheckCircle2, Clock, Search, type LucideIcon } from 'lucide-react'
import type { Job } from '../types'

function Kpi({ label, value, note, Icon }: { label: string; value: number; note: string; Icon: LucideIcon }) {
  return (
    <div className="rounded-xl border border-border bg-card px-5 py-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-center justify-between text-[13px] font-medium text-muted-foreground">
        <span>{label}</span>
        <Icon className="size-4 text-primary" />
      </div>
      <div className="mt-2 font-mono text-[26px] font-bold">{value}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{note}</div>
    </div>
  )
}

export function Kpis({ job, todo, done, noMatch }: { job: Job; todo: number; done: number; noMatch: number }) {
  return (
    <section className="grid grid-cols-1 gap-4 min-[520px]:grid-cols-2 xl:grid-cols-4">
      <Kpi label="Cần duyệt" value={todo} note="Đơn model nghi trùng" Icon={Clock} />
      <Kpi label="Đã duyệt" value={done} note="Đã chọn ảnh hoặc Model sai" Icon={CheckCircle2} />
      <Kpi label="Không thấy trùng" value={noMatch} note="Chờ /handle" Icon={Search} />
      <Kpi
        label="Lỗi"
        value={job.error_count}
        note={`Job ${job.status} · ${job.processed_count}/${job.requested_count} đơn`}
        Icon={AlertTriangle}
      />
    </section>
  )
}
