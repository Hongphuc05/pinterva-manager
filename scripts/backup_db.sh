#!/usr/bin/env bash
set -euo pipefail

# 1. Thư mục gốc dự án
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$ROOT_DIR/backup"
RAW_DIR="$BACKUP_DIR/raw"

# Tạo thư mục backup/raw nếu chưa tồn tại
mkdir -p "$RAW_DIR"

# 2. Đọc cấu hình từ .env.production nếu có
ENV_FILE="$ROOT_DIR/.env.production"
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

DB_NAME="${POSTGRES_DB:-tacahu_ops}"
DB_USER="${POSTGRES_USER:-postgres}"

# Tự động nhận diện container Postgres đang chạy
CONTAINER_NAME="${POSTGRES_CONTAINER:-$(docker ps --filter "name=postgres" --format "{{.Names}}" | head -n 1)}"
if [ -z "$CONTAINER_NAME" ]; then
    CONTAINER_NAME="$(docker ps --filter "name=db" --format "{{.Names}}" | head -n 1)"
fi

if [ -z "$CONTAINER_NAME" ]; then
    echo "[ERROR] Không tìm thấy container PostgreSQL đang chạy!" >&2
    exit 1
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
FILENAME="db_${DB_NAME}_${TIMESTAMP}.sql.gz"
OUTPUT_FILE="$RAW_DIR/$FILENAME"

echo "[$(date +"%Y-%m-%d %H:%M:%S")] Đang tiến hành dump database '$DB_NAME'..."

# Thực hiện pg_dump và nén trực tiếp sang gzip (.sql.gz)
docker exec -t "$CONTAINER_NAME" pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --clean | gzip > "$OUTPUT_FILE"

# Kiểm tra file đã được tạo thành công và không bị rỗng
if [ ! -s "$OUTPUT_FILE" ]; then
    echo "[ERROR] File dump tạo ra bị rỗng!" >&2
    rm -f "$OUTPUT_FILE"
    exit 1
fi

echo "[SUCCESS] Đã tạo bản backup thành công: $OUTPUT_FILE ($(du -h "$OUTPUT_FILE" | cut -f1))"

# 3. Cơ chế tự động giới hạn chỉ giữ lại tối đa 3 bản backup mới nhất (xoá các bản cũ hơn)
cd "$RAW_DIR"
DELETED_FILES=$(ls -t db_*.sql.gz 2>/dev/null | tail -n +4 || true)
if [ -n "$DELETED_FILES" ]; then
    echo "Đang xoá các bản backup cũ quá 3 ngày:"
    echo "$DELETED_FILES"
    echo "$DELETED_FILES" | xargs rm -f
fi

echo -e "\n=== Danh sách 3 bản backup mới nhất trong thư mục backup/raw ==="
ls -lh "$RAW_DIR"/db_*.sql.gz 2>/dev/null || echo "Chưa có file backup."
