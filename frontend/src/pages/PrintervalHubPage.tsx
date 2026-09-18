import {
  Globe,
  ExternalLink,
  CheckCircle2,
  HelpCircle,
  Download,
  FolderArchive,
  Settings,
  Zap,
  Server,
  Laptop,
} from 'lucide-react'
import { DashboardLayout } from '../components/DashboardLayout'

export function PrintervalHubPage() {
  const printervalAdminUrl = 'https://printerval.com/central/outsource/pod/design-job/admin'
  const downloadExtensionUrl = '/api/integrations/extension/download'

  return (
    <DashboardLayout>
      <div className="max-w-4xl mx-auto space-y-6 pt-4 pb-12">
        {/* Header Banner */}
        <div className="rounded-xl bg-[#0052CC] p-7 text-white shadow-sm border border-blue-600">
          <div className="space-y-4">
            <div className="space-y-1.5">
              <h1 className="text-xl lg:text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
                <Globe className="h-6 w-6 text-blue-200" />
                <span>Mở Printerval & Đồng Bộ Bộ Ảnh</span>
              </h1>
              <p className="text-xs text-blue-100/90 max-w-2xl leading-relaxed">
                Mở trang quản lý Printerval chỉ với 1 click. Tiện ích mở rộng <strong>Tacahu Sync (CopyImage)</strong> hỗ trợ trích xuất và đồng bộ hàng loạt toàn bộ ảnh sản phẩm về hệ thống Tacahu Ops (VPS hoặc Localhost).
              </p>
            </div>

            {/* Main Action Buttons */}
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <a
                href={printervalAdminUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-white text-[#0052CC] hover:bg-blue-50 font-semibold text-xs shadow-sm transition-all"
              >
                <Globe className="h-4 w-4 text-[#0052CC]" />
                <span>Mở Trang Quản Lý Printerval</span>
                <ExternalLink className="h-3.5 w-3.5 opacity-70" />
              </a>

              <a
                href={downloadExtensionUrl}
                download="tacahu-copyimage-extension.zip"
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-blue-700/80 text-white hover:bg-blue-800 border border-blue-400/40 font-semibold text-xs shadow-sm transition-all"
              >
                <Download className="h-4 w-4 text-white" />
                <span>Tải Tiện Ích CopyImage (.ZIP)</span>
              </a>
            </div>
          </div>
        </div>

        {/* 4-Step Installation & Setup Guide */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs space-y-5">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
              <Settings className="h-4 w-4 text-blue-600" />
              <span>Hướng Dẫn Cài Đặt & Cấu Hình Tiện Ích (Đồng Bộ VPS / Local)</span>
            </h2>
            <span className="text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              Hoàn toàn tự động
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Step 1 */}
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
              <div className="flex items-center gap-2 text-slate-800 font-bold text-xs">
                <span className="h-5 w-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs">1</span>
                <FolderArchive className="h-4 w-4 text-blue-600" />
                <span>Tải & Giải Nén Extension</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                Bấm nút tải về bên dưới để nhận file <code className="bg-slate-200/80 px-1 py-0.5 rounded text-slate-800 font-mono text-[11px]">tacahu-copyimage-extension.zip</code>, sau đó giải nén ra một thư mục trên máy tính.
              </p>
              <div className="pt-1">
                <a
                  href={downloadExtensionUrl}
                  download="tacahu-copyimage-extension.zip"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 font-medium text-xs shadow-xs transition-colors"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>Tải Extension (.zip)</span>
                </a>
              </div>
            </div>

            {/* Step 2 */}
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
              <div className="flex items-center gap-2 text-slate-800 font-bold text-xs">
                <span className="h-5 w-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs">2</span>
                <Globe className="h-4 w-4 text-blue-600" />
                <span>Cài Đặt Vào Trình Duyệt (Chrome / Cốc Cốc)</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                Mở tab mới truy cập <code className="bg-slate-200/80 px-1 py-0.5 rounded text-slate-800 font-mono text-[11px]">chrome://extensions/</code> $\rightarrow$ Bật công tắc <strong>Developer mode</strong> (góc trên bên phải) $\rightarrow$ Bấm <strong>Tải tiện ích đã giải nén (Load unpacked)</strong> và chọn thư mục vừa giải nén.
              </p>
            </div>

            {/* Step 3 */}
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
              <div className="flex items-center gap-2 text-slate-800 font-bold text-xs">
                <span className="h-5 w-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs">3</span>
                <Server className="h-4 w-4 text-blue-600" />
                <span>Cấu Hình Địa Chỉ Web Tacahu Ops</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                Chuột phải vào icon Extension $\rightarrow$ Chọn <strong>Tùy chọn (Options)</strong>. Tại ô <em>Tacahu Ops API URL</em>:
              </p>
              <div className="space-y-1.5 text-[11px] bg-white p-2.5 rounded border border-slate-200">
                <div className="flex items-center gap-1.5 text-slate-700">
                  <Server className="h-3.5 w-3.5 text-blue-600 shrink-0" />
                  <span><strong>VPS Production:</strong> Nhập <code className="bg-slate-100 px-1 py-0.5 rounded text-blue-700 font-mono font-bold">https://tacahu.fun</code></span>
                </div>
                <div className="flex items-center gap-1.5 text-slate-700">
                  <Laptop className="h-3.5 w-3.5 text-slate-500 shrink-0" />
                  <span><strong>Chạy Localhost:</strong> Nhập <code className="bg-slate-100 px-1 py-0.5 rounded text-slate-700 font-mono font-bold">http://localhost:8000</code></span>
                </div>
              </div>
              <p className="text-[11px] text-slate-500 leading-relaxed">
                Bấm <strong>[Kiểm tra]</strong> (hiện thông báo xanh thành công) $\rightarrow$ Bấm <strong>[Lưu Cấu Hình]</strong>.
              </p>
            </div>

            {/* Step 4 */}
            <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
              <div className="flex items-center gap-2 text-slate-800 font-bold text-xs">
                <span className="h-5 w-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs">4</span>
                <Zap className="h-4 w-4 text-blue-600" />
                <span>Quét & Đồng Bộ Ảnh Tự Động</span>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                Bấm nút <strong>[Mở Trang Quản Lý Printerval]</strong> ở trên $\rightarrow$ Sang trang Printerval, bấm nút <strong>Quét & Đồng Bộ Bộ Ảnh</strong> (ở sát cạnh dưới chính giữa màn hình, có thể bấm dấu ✕ để thu gọn thành nút tròn).
              </p>
              <p className="text-[11px] text-emerald-700 font-medium bg-emerald-50 px-2 py-1.5 rounded border border-emerald-200">
                ✓ Toàn bộ ảnh sản phẩm sẽ được gửi thẳng về hệ thống Tacahu Ops tương ứng mà không cần thao tác từng đơn!
              </p>
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
      </div>
    </DashboardLayout>
  )
}

