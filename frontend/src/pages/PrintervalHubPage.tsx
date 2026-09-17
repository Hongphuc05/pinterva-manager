import { Globe, ExternalLink, CheckCircle2, ShieldCheck, HelpCircle } from 'lucide-react'
import { DashboardLayout } from '../components/DashboardLayout'

export function PrintervalHubPage() {
  const printervalWaitingUrl = 'https://printerval.com/admin/design-job'

  return (
    <DashboardLayout>
      <div className="max-w-4xl mx-auto space-y-6 pt-4 pb-12">
        {/* Header Banner */}
        <div className="rounded-xl bg-[#0052CC] p-7 text-white shadow-sm border border-blue-600">
          <div className="space-y-3">
            <h1 className="text-xl lg:text-2xl font-bold tracking-tight text-white">
              Mở Printerval & Đồng Bộ Bộ Ảnh
            </h1>
            <p className="text-xs text-blue-100/90 max-w-2xl leading-relaxed">
              Mở trang quản lý Printerval chỉ với 1 click, tiện ích mở rộng <strong>Tacahu Sync</strong> sẽ hỗ trợ trích xuất và đồng bộ toàn bộ ảnh sản phẩm về hệ thống.
            </p>

            {/* Main Action Button */}
            <div className="pt-2">
              <a
                href={printervalWaitingUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-white text-[#0052CC] hover:bg-blue-50 font-semibold text-xs shadow-sm transition-all"
              >
                <Globe className="h-4 w-4 text-[#0052CC]" />
                <span>Mở Trang Quản Lý Printerval (Design Job)</span>
                <ExternalLink className="h-3.5 w-3.5 opacity-70" />
              </a>
            </div>
          </div>
        </div>

        {/* Extension Mechanism & Scope Brief */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-blue-600" />
              <span>Cơ Chế & Phạm Vi Quét Của Extension</span>
            </h2>
            <span className="text-xs text-slate-400">Đối soát thông minh theo mã đơn DJ...</span>
          </div>

          <div className="space-y-3 text-xs text-slate-600 leading-relaxed">
            <div className="p-3.5 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
              <p>
                • <strong>Quét đúng các đơn đang hiển thị trên màn hình:</strong> Extension hoạt động trực tiếp trên giao diện trình duyệt hiện tại. Bạn đang lọc Tab nào (ví dụ Tab <em>Waiting</em>), lọc theo ngày hay lọc theo Designer nào trên Printerval thì Extension sẽ quét chính xác tất cả các đơn đang hiển thị trên trang đó.
              </p>
              <p>
                • <strong>Tự động đối soát (Mapping) với Tacahu Ops:</strong> Dù trên Printerval bạn quét 100 đơn nhưng trên Tacahu Ops chỉ mới có 50 đơn, Backend sẽ tự động so khớp mã đơn và <strong>chỉ cập nhật ảnh cho đúng 50 đơn</strong> đang có trên hệ thống. Các đơn khác được bỏ qua an toàn mà không sinh lỗi.
              </p>
              <p>
                • <strong>Mẹo phân trang:</strong> Trên Printerval, hãy chỉnh mục <em>Rows per page</em> thành <strong>50 hoặc 100 đơn/trang</strong>. Bạn chỉ cần 1 cú click là quét xong toàn bộ đơn của cả trang trong 2-3 giây. Nếu có trang 2, 3 thì chuyển trang và quét tiếp.
              </p>
            </div>
          </div>
        </div>

        {/* 3-Step Standard Operating Flow */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h2 className="text-sm font-bold text-slate-800">
              Quy Trình Quét & Đồng Bộ 3 Bước Chuẩn
            </h2>
            <span className="text-xs text-slate-400">Nhanh chóng • Không tốn thời gian chờ</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-1.5">
              <div className="flex items-center gap-2 text-slate-700 font-bold text-xs">
                <span className="h-5 w-5 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center text-xs">1</span>
                <span>Quét Đơn Waiting</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                Trên web Tacahu Ops (Tab Đơn Hàng), bấm <strong>[Quét đơn]</strong> để nạp các đơn mới từ tab Waiting về hệ thống.
              </p>
            </div>

            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-1.5">
              <div className="flex items-center gap-2 text-slate-700 font-bold text-xs">
                <span className="h-5 w-5 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center text-xs">2</span>
                <span>Kích Hoạt Extension</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                Bấm nút <strong>[Mở Trang Quản Lý Printerval]</strong> ở trên, sang tab Design Job và bấm <strong>Quét & Đồng Bộ Bộ Ảnh</strong> (góc dưới bên phải).
              </p>
            </div>

            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-1.5">
              <div className="flex items-center gap-2 text-slate-700 font-bold text-xs">
                <span className="h-5 w-5 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center text-xs">3</span>
                <span>Hoàn Tất & Đủ Ảnh</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                Quay lại Tacahu Ops bấm <strong>F5 (Tải lại)</strong>. Toàn bộ đơn hàng đã có đủ 100% bộ ảnh HD sẵn sàng cho Designer làm việc.
              </p>
            </div>
          </div>
        </div>

        {/* 2 Pro Tips For Admins */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Tip 1 */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs space-y-3">
            <div>
              <span className="text-[11px] font-bold text-blue-700 uppercase tracking-wide">Mẹo 1</span>
              <h3 className="text-sm font-bold text-slate-900 mt-0.5">Bật Chế Độ Tự Động Quét (Auto-Scan)</h3>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              Trong phần <strong>Tùy chọn (Options)</strong> của Extension, tích chọn mục <strong>"Tự động quét bộ ảnh ngay khi mở trang Design Job"</strong>.
            </p>
            <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-700 space-y-1">
              <div className="flex items-center gap-1.5 text-slate-800 font-semibold">
                <CheckCircle2 className="h-3.5 w-3.5 text-blue-600" />
                <span>Lợi ích:</span>
              </div>
              <p className="text-[11px] text-slate-600 leading-relaxed">
                Mỗi khi bạn mở trang Printerval, tiện ích sẽ tự động quét và đẩy ngầm tất cả ảnh về Tacahu trong 2 giây mà không cần bấm nút.
              </p>
            </div>
          </div>

          {/* Tip 2 */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs space-y-3">
            <div>
              <span className="text-[11px] font-bold text-blue-700 uppercase tracking-wide">Mẹo 2</span>
              <h3 className="text-sm font-bold text-slate-900 mt-0.5">Xem Trước & Click-to-Copy Sang Figma/Photoshop</h3>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              Trên bảng đơn Printerval, Extension sẽ hiển thị các ô ảnh thu nhỏ (1, 2, 3...) ngay dưới từng mã đơn <code className="text-slate-800 font-mono bg-slate-100 px-1 py-0.5 rounded">DJ...</code>.
            </p>
            <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-700 space-y-1">
              <div className="flex items-center gap-1.5 text-slate-800 font-semibold">
                <CheckCircle2 className="h-3.5 w-3.5 text-blue-600" />
                <span>Thao tác nhanh:</span>
              </div>
              <p className="text-[11px] text-slate-600 leading-relaxed">
                • <strong>Rê chuột:</strong> Phóng to ảnh HD để xem chi tiết.<br />
                • <strong>Click chuột trái:</strong> Copy ngay ảnh vào Clipboard, paste thẳng (<code className="text-slate-800 bg-slate-100 px-1 rounded">Ctrl+V</code>) vào Figma/Photoshop.
              </p>
            </div>
          </div>
        </div>

        {/* Extension Installation Reminder Box */}
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 flex items-start gap-3 text-xs text-slate-600">
          <ShieldCheck className="h-4 w-4 text-slate-700 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="font-semibold text-slate-800 text-xs">Cài đặt tiện ích Tacahu Sync trên trình duyệt</h4>
            <p className="text-slate-600 leading-relaxed">
              Mở <code className="bg-slate-200/80 px-1 py-0.5 rounded text-slate-800">chrome://extensions/</code> $\rightarrow$ Bật Developer mode $\rightarrow$ Bấm <strong>Tải tiện ích đã giải nén (Load unpacked)</strong> và chọn thư mục <code className="bg-slate-200/80 px-1 py-0.5 rounded text-slate-800">CopyImage</code> trong mã nguồn dự án.
            </p>
          </div>
        </div>
      </div>
    </DashboardLayout>
  )
}
