# Tacahu Ops Core

> **Nguồn tài liệu hiện hành** cho nghiệp vụ, luồng đơn và vận hành Tacahu Ops.
> Cập nhật theo code tại `main` ngày 2026-09-21. Khi tài liệu khác mâu thuẫn,
> code, migration và test là bằng chứng cuối cùng.

## Đọc theo mục đích

| Cần biết | Đọc |
| --- | --- |
| Hệ thống gồm những gì, dữ liệu nào là authoritative | [architecture.md](architecture.md) |
| Dữ liệu nào được lưu ở DB, VPS volume hay hệ thống ngoài | [data-storage.md](data-storage.md) |
| Một đơn đi từ crawl đến Done/Fix ra sao | [order-workflow.md](order-workflow.md) |
| Quyền từng role, private data và ngoại lệ Duplicate Board | [access-and-privacy.md](access-and-privacy.md) |
| API đang dùng và endpoint đã deprecate | [api-surface.md](api-surface.md) |
| Chạy local, deploy, backup và kiểm tra production | [operations.md](operations.md) |
| Tài liệu cũ/spec/plan có còn áp dụng không | [archive.md](archive.md) |

## Quy ước bảo trì

1. Thay đổi state, authorization, external write, persistence hoặc worker phải cập nhật
   tài liệu core tương ứng trong cùng commit.
2. Không biến plan/spec có ngày tháng trong `docs/superpowers/` thành source of truth.
   Chúng là bằng chứng quyết định lịch sử.
3. Không ghi secret, token, cookie, URL nội bộ nhạy cảm hay dữ liệu đơn thật vào tài liệu.
