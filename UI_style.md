# HƯỚNG DẪN THIẾT KẾ UI/UX (UI/UX DESIGN STYLE GUIDE)
> **Tài liệu hướng dẫn dành cho AI Agent & Developer**  
> *Mô tả chi tiết phong cách, hệ thống quy chuẩn UI/UX, bảng màu, typography, layout và các component mẫu để xây dựng giao diện ứng dụng quản lý doanh nghiệp / bệnh viện chuẩn hóa.*

---

## 1. Tổng Quan Phong Cách (Design Philosophy)

Hệ thống giao diện được thiết kế theo phong cách **Enterprise Admin Dashboard chuyên nghiệp, hiện đại và tập trung vào hiệu suất làm việc (Data-Dense Professional Dashboard)**.

### Các Nguyên Tắc Chủ Đạo:
1. **Độ tập trung & Mật độ dữ liệu cao (High Information Density)**: Tối ưu không gian hiển thị cho bảng biểu, biểu đồ, danh mục vật tư/hàng hóa phức tạp mà không làm rối mắt người dùng.
2. **Bảng màu tin cậy & Chuẩn y tế/doanh nghiệp**: Sử dụng màu **Deep Navy Blue** làm màu chủ đạo (Primary), kết hợp màu **Emerald Green** (Accent/Success) và nền xám xanh nhạt (`tertiary`), tạo cảm giác tin cậy, chính xác, sạch sẽ.
3. **Phân cấp thị giác rõ ràng (Visual Hierarchy)**: 
   - Font chữ **Inter** sắc nét cho toàn bộ văn bản UI.
   - Font **IBM Plex Mono** cho các mã số (Mã vật tư, Mã hóa đơn, Mã hợp đồng, Số tiền).
4. **Trạng thái tương tác rõ ràng (Explicit State Feedback)**: Sử dụng các `Badge` màu phân biệt trạng thái (Chờ duyệt, Đã duyệt, Hủy, Cảnh báo), kết hợp Toast notification và hiệu ứng chuyển cảnh mượt mà.

---

## 2. Hệ Thống Màu Sắc & Design Tokens (Color Palette)

Hệ thống sử dụng không gian màu **HSL** được cấu hình thông qua CSS Variables và Tailwind Extension.

### 2.1. HSL CSS Variables (`src/index.css`)
```css
:root {
  /* Nền trang & Chữ cơ bản */
  --background: 0 0% 100%;             /* Trắng tinh #FFFFFF */
  --foreground: 210 10% 18%;           /* Đen xám đậm #292D32 */

  /* Thẻ (Card) & Popover */
  --card: 0 0% 100%;
  --card-foreground: 210 10% 18%;
  --popover: 0 0% 100%;
  --popover-foreground: 210 10% 18%;

  /* Màu Chủ Đạo (Primary - Deep Navy Blue) */
  --primary: 218 100% 40%;             /* #0052CC - Xanh Navy chuyên nghiệp */
  --primary-foreground: 0 0% 100%;     /* Trắng */

  /* Màu Phụ (Secondary - Bright Blue) */
  --secondary: 218 90% 52%;           /* #1E6FFF - Xanh dương tươi */
  --secondary-foreground: 0 0% 100%;

  /* Màu Nền Phụ (Tertiary Background) */
  --tertiary: 210 16% 96%;            /* #F4F6F8 - Xám xanh nhạt cho body background */
  --tertiary-foreground: 210 10% 18%;

  /* Màu Trung Tính & Muted */
  --neutral: 0 0% 100%;
  --neutral-foreground: 210 10% 18%;
  --muted: 210 14% 90%;               /* #E2E8F0 */
  --muted-foreground: 210 10% 30%;    /* #475569 */

  /* Màu Điểm Nhấn & Trạng Thái (Status Colors) */
  --accent: 148 48% 40%;              /* Emerald Green #34A853 */
  --accent-foreground: 0 0% 100%;

  --success: 148 48% 40%;             /* Xanh lá - Hoàn thành / Đã duyệt */
  --success-foreground: 0 0% 100%;

  --warning: 38 90% 50%;              /* Cam hổ phách - Chờ duyệt / Cảnh báo */
  --warning-foreground: 0 0% 100%;

  --destructive: 0 84% 60%;           /* Đỏ Crimson - Từ chối / Xóa / Lỗi */
  --destructive-foreground: 0 0% 100%;

  /* Viền & Bo góc */
  --border: 210 14% 90%;              /* Viền mỏng nhẹ */
  --input: 210 14% 90%;
  --ring: 218 100% 40%;
  --radius: 0.5rem;                   /* Bo góc chuẩn 8px */
}
```

### 2.2. Custom Gradients (`utilities`)
```css
.gradient-1 {
  background: linear-gradient(135deg, hsl(218, 100%, 40%) 0%, hsl(218, 90%, 52%) 100%);
}

.gradient-2 {
  background: linear-gradient(135deg, hsl(148, 48%, 40%) 0%, hsl(148, 48%, 50%) 100%);
}

.button-border-gradient {
  background: linear-gradient(145deg, hsl(218, 90%, 52%) 0%, hsl(148, 48%, 40%) 100%);
}
```

---

## 3. Kiểu Chữ & Typography

Hệ thống kết hợp 2 font chữ chuẩn từ Google Fonts:

1. **Inter (`font-sans`)**: Dành cho tất cả UI Text, Nhãn, Tiêu đề, Button, Navigation.
   - Weights sử dụng: `400` (Regular), `500` (Medium), `600` (SemiBold), `700` (Bold).
2. **IBM Plex Mono (`font-mono`)**: Dành riêng cho dữ liệu số, Mã số, Mã vật tư, Giá tiền, Ngày tháng trong Table.
   - Weights sử dụng: `400` (Regular), `500` (Medium).

### Quy Chuẩn Cỡ Chữ (Font Size Scale):
- **Page Title**: `text-2xl font-bold tracking-tight` (24px)
- **Section Title / Card Title**: `text-lg font-semibold` (18px)
- **Body / Form Label**: `text-sm font-medium` (14px)
- **Table Data / Secondary Text**: `text-xs` hoặc `text-sm` (12px - 14px)
- **Badge / Micro Tag**: `text-xs font-semibold` (12px)

---

## 4. Kiến Trúc Bố Cục (Layout Architecture)

Ứng dụng sử dụng bố cục **Sidebar + Topbar cố định** (2-Column Layout with Sticky Header):

```
+-----------------------------------------------------------------------+
|  SIDEBAR (w-64, bg-primary)  | TOPBAR (h-16, bg-neutral, sticky)      |
|  - Logo + App Header         | - App Title / Hospital Name            |
|  - Nav Links (Vertical)      | - Activity Notification Bell + Badge   |
|  - Active Item:              | - User Profile Dropdown Menu           |
|    bg-primary-foreground/20  +----------------------------------------+
|  - Hover:                    | MAIN CONTENT AREA (bg-tertiary)        |
|    hover:bg-primary-foreground/10 | - Page Title + Action Controls      |
|                              | - Collapsible Filter Bar               |
|                              | - KPI Summary Cards Grid               |
|                              | - Dynamic Data Table / Charts          |
+------------------------------+----------------------------------------+
```

### Chi Tiết Thành Phần Layout:
1. **Sidebar (`w-64 bg-primary text-primary-foreground`)**:
   - Cố định phía bên trái (`fixed lg:sticky top-0 h-screen`).
   - Phía trên là Logo thương hiệu + Tên ban ngành/hệ thống.
   - Danh sách Navigation link chuẩn icon + text.
   - Tích hợp Badge chấm đỏ báo hiệu dữ liệu mới (ví dụ: đơn hàng mới cần xử lý).
   - Đầy đủ Responsive Drawer cho màn hình Mobile với lớp mờ che nền (`bg-gray-900/50`).
2. **Topbar (`h-16 bg-neutral border-b border-border`)**:
   - Sticky phía trên cùng (`sticky top-0 z-40`).
   - Trái: Tên tổ chức / Tiêu đề ứng dụng.
   - Phải: Chuông thông báo (Bell icon) có đếm số lượng chưa đọc + Dropdown danh sách hoạt động gần đây (ScrollArea tối đa 30 item); Menu tài khoản (User Dropdown) gồm thông tin Role, đường dẫn Tác vụ, Hồ sơ và Đăng xuất.
3. **Main Content (`bg-tertiary p-6 lg:p-8 space-y-6`)**:
   - Nền xám nhạt nhẹ nhàng (`bg-tertiary`), tạo độ tương phản cao với các Card màu trắng.

---

## 5. Thư Viện Component Chuẩn (UI Components)

Giao diện được xây dựng trên nền tảng **Radix UI Primitives + Tailwind CSS + Lucide Icons**.

### 5.1. Thẻ Thống Kê KPI (Metric Cards)
```tsx
<Card className="rounded-xl border border-border bg-card shadow-sm hover:shadow-md transition-shadow">
  <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
    <CardTitle className="text-sm font-medium text-muted-foreground">Tổng Kinh Phí Dự Trù</CardTitle>
    <DollarSign className="h-4 w-4 text-primary" />
  </CardHeader>
  <CardContent>
    <div className="text-2xl font-bold font-mono text-foreground">1.250.000.000 ₫</div>
    <p className="text-xs text-emerald-600 flex items-center gap-1 mt-1">
      <ArrowUpRight className="h-3 w-3" /> +12% so với tháng trước
    </p>
  </CardContent>
</Card>
```

### 5.2. Nút Bấm (Button Variants)
- **Primary Button**: `bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm`
- **Secondary Button**: `bg-secondary text-secondary-foreground hover:bg-secondary/80`
- **Destructive Button**: `bg-destructive text-destructive-foreground hover:bg-destructive/90`
- **Outline Button**: `border border-input bg-background hover:bg-accent hover:text-accent-foreground`
- **Ghost Button**: `hover:bg-accent hover:text-accent-foreground`
- **Size**: Default (`h-9 px-4 py-2`), Small (`h-8 px-3 text-xs`), Icon (`h-9 w-9`).

### 5.3. Nhãn Trạng Thái (Status Badges)
| Trạng Thái | Variant | Mã CSS / Class |
| :--- | :--- | :--- |
| **Đã duyệt / Success** | `default` (Accent) | `bg-emerald-100 text-emerald-800 border-emerald-200` |
| **Chờ duyệt / Pending** | `warning` | `bg-amber-100 text-amber-800 border-amber-200` |
| **Từ chối / Rejected** | `destructive` | `bg-red-100 text-red-800 border-red-200` |
| **Gửi CHK / Submitted**| `secondary` | `bg-blue-100 text-blue-800 border-blue-200` |

### 5.4. Bảng Dữ Liệu Dense Grid (Data Table UI)
- Header cố định, chữ in hoa nhẹ hoặc viết hoa chữ cái đầu: `text-xs font-semibold text-muted-foreground bg-muted/50`.
- Hàng dữ liệu: Pad đứng vừa phải (`py-3 px-4`), phân cách đường kẻ ngang `border-b border-border/70`, có hover highlight `hover:bg-muted/40`.
- Mã số sử dụng font monospace: `<span className="font-mono text-xs">{item.materialCode}</span>`.
- Số lượng & đơn giá căn phải (right-aligned) để dễ theo dõi.

---

## 6. Mô Hình Tương Tác & Nguyên Tắc UX (UX Patterns)

### 6.1. Bộ Lọc Phân Cấp Linh Hoạt (Cascading Dynamic Filters)
- Giao diện quản lý hỗ trợ lọc theo cấp độ (Cấp 1 -> Cấp 2 -> Cấp 3 -> Nhà thầu).
- Khi chọn Cấp 1, danh sách Cấp 2 tự động lọc lại. Tương tự với Cấp 3.
- Cung cấp nút **"Xóa bộ lọc"** nhanh (`handleResetFilters`) để reset toàn bộ về mặc định.
- Hỗ trợ ẩn/hiện thanh bộ lọc (`Collapsible Filter Panel`) giúp tiết kiệm diện tích trên màn hình nhỏ.

### 6.2. Phản Hồi Trạng Thái Tương Tác (Interactive Feedback)
- **Loading State**: Sử dụng Icon `Loader2 animate-spin` hoặc màn hình Skeleton nhạt (`PageFallback`).
- **Notification Toast**: Mọi hành động thành công/thất bại (Lưu ghi chú, Duyệt dự trù, Đăng xuất tự động) đều hiển thị Toast góc dưới bên phải.
- **Empty State**: Khi không có dữ liệu, hiển thị khối thông báo trung tâm có icon và dòng hướng dẫn rõ ràng ("Chưa có dữ liệu dự trù cho kỳ này").

### 6.3. Quản Lý Phiên Đăng Nhập & Bảo Mật UX (Session UX)
- **Tự động đăng xuất sau 30 phút không hoạt động (Idle Timeout)**: Hiển thị Toast thông báo lý do rõ ràng khi bị đăng xuất.
- **Phân quyền giao diện (Role-Based UI Rendering)**:
  - Chỉ hiển thị các tab/nút bấm nâng cao (Tạo user, Quản lý hóa đơn, Duyệt CHK) nếu User có Role hợp lệ (`ADMIN`, `KHO`, `CHK`, `BAN_KHVT`).

---

## 7. Checklist Thực Thi Cho AI Agent Khi Làm Dự Án Mới

Khi được yêu cầu xây dựng ứng dụng theo phong cách trang web này, Agent cần tuân thủ các bước sau:

1. **Khởi tạo Tailwind & Theme HSL**:
   - Đảm bảo khai báo đủ các biến HSL `--primary`, `--secondary`, `--tertiary`, `--accent`, `--warning`, `--destructive` trong `index.css`.
   - Cài đặt font `Inter` và `IBM Plex Mono` từ Google Fonts.
2. **Xây Dựng Cấu Trúc Bố Cục (Layout)**:
   - Sử dụng `Sidebar` nền xanh navy (`bg-primary`) và `Topbar` trắng xám nhẹ (`bg-neutral`).
   - Sử dụng `DashboardLayout` bọc quanh `Outlet` của React Router.
3. **Sử Dụng Component Chuẩn**:
   - Sử dụng Radix UI / Shadcn UI cho Button, Card, Badge, Dialog, Dropdown, Select, Tabs, Toaster.
   - Thêm `Lucide React` làm bộ Icon đồng nhất.
4. **Trình Bày Dữ Liệu**:
   - Dùng `font-mono` cho các cột mã số, mã vật tư, giá tiền.
   - Dùng Badge màu phân biệt rõ các trạng thái công việc.
5. **Hiệu Ứng & Micro-interactions**:
   - Bo góc chuẩn `rounded-xl` cho Card, `rounded-md` cho Button và Badge.
   - Hiệu ứng hover nhẹ (`hover:shadow-md transition-all duration-200`).

---
*Tài liệu được trích xuất và tổng hợp chuẩn hóa từ hệ thống Quản lý Vật tư Y tế BV108.*
