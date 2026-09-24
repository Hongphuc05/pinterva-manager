import { useState, type ReactNode } from 'react'
import { Box, Image as ImageIcon, Layers, Menu, ScanSearch } from 'lucide-react'

const link = 'flex items-center gap-3 rounded-lg px-3 py-2.5 font-medium text-inherit no-underline transition-colors'

export function Layout({ connected, children }: { connected: boolean | null; children: ReactNode }) {
  const [drawer, setDrawer] = useState(false)
  return (
    <div className="flex min-h-screen">
      {drawer && <div className="fixed inset-0 z-[45] bg-gray-900/50 lg:hidden" onClick={() => setDrawer(false)} />}
      <aside
        className={`fixed left-0 top-0 z-50 flex h-screen w-64 flex-none flex-col bg-primary text-primary-foreground transition-transform lg:sticky lg:translate-x-0 ${
          drawer ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-3 border-b border-white/15 p-5">
          <div className="grid size-10 place-items-center rounded-xl bg-white/20">
            <Box className="size-[22px]" />
          </div>
          <div>
            <b className="block text-[17px] font-bold tracking-tight">Tacahu Ops</b>
            <span className="text-xs opacity-80">Kiểm tra trùng thiết kế</span>
          </div>
        </div>
        <nav className="flex flex-col gap-1 px-3 py-4">
          <div className="px-3 pb-1 pt-3 text-[11px] font-semibold tracking-widest opacity-65">VẬN HÀNH</div>
          <a href="/" className={`${link} bg-white/20`} aria-current="page">
            <Layers className="size-4" />Duyệt kết quả
          </a>
          <div className="px-3 pb-1 pt-3 text-[11px] font-semibold tracking-widest opacity-65">CÔNG CỤ KHÁC</div>
          <a href="/index.html" className={`${link} hover:bg-white/10`}>
            <ImageIcon className="size-4" />So sánh 1-1
          </a>
          <a href="/scan.html" className={`${link} hover:bg-white/10`}>
            <ScanSearch className="size-4" />Quét pool
          </a>
        </nav>
        <div className="mt-auto border-t border-white/15 px-5 py-4 text-xs opacity-75">
          Chỉ chạy trên máy local. Không ghi vào bảng đơn hàng.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-border bg-white px-4 lg:px-6">
          <button
            type="button"
            aria-label="Mở menu"
            onClick={() => setDrawer(true)}
            className="grid size-9 place-items-center rounded-lg border border-border bg-white lg:hidden"
          >
            <Menu className="size-4" />
          </button>
          <h2 className="text-base font-semibold">Duyệt kết quả kiểm tra trùng</h2>
          <div className="flex-1" />
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <i className={`size-2 rounded-full ${connected === false ? 'bg-destructive' : 'bg-accent'}`} />
            {connected === null ? 'Đang kết nối…' : connected ? 'Đã kết nối DB' : 'Mất kết nối DB'}
          </span>
        </header>
        <main className="flex flex-col gap-6 p-4 lg:p-8">{children}</main>
      </div>
    </div>
  )
}
