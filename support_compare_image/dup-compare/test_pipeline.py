"""
Smoke test bằng ảnh synthetic (vẽ bằng PIL) để chứng minh pipeline chạy
đúng logic 4 nhãn TRƯỚC KHI bạn cắm ảnh sản phẩm thật vào. Không cần
mạng/GPU (dùng embedding_backend nào cũng chạy được — nếu offline sẽ tự
fallback sang classical, in ra rõ trong output).

Chạy: python3 test_pipeline.py
"""
import io
from PIL import Image, ImageDraw

from backend.classifier import classify
from backend.embedding import get_embedder
from backend.signals import color_delta_e, phash_distance, ssim_score


def make_shirt(body_color, text="TEXAS", icon=True, size=(300, 380)):
    """Vẽ mockup áo đơn giản: thân áo màu `body_color`, artwork/text cố định
    ở giữa ngực (mô phỏng 'form/design' giống hệt nhau giữa các biến thể)."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    # thân áo (hình chữ nhật bo góc thô)
    d.rounded_rectangle([40, 60, 260, 360], radius=30, fill=body_color, outline="black", width=3)
    # tay áo
    d.polygon([(40, 70), (0, 140), (40, 170)], fill=body_color, outline="black")
    d.polygon([(260, 70), (300, 140), (260, 170)], fill=body_color, outline="black")
    # cổ áo
    d.ellipse([120, 55, 180, 90], fill="white", outline="black")
    # artwork/text cố định giữa ngực -> đại diện cho "cùng design"
    d.text((90, 180), text, fill="black")
    if icon:
        d.ellipse([130, 220, 170, 260], outline="black", width=3)  # icon giả (quả bóng)
    return img


def to_pil(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def run_case(name, img_old, img_new):
    embedder = get_embedder()
    e_old, e_new = embedder.encode(img_old), embedder.encode(img_new)
    sim = embedder.cosine_similarity(e_old, e_new)
    p_dist = phash_distance(img_old, img_new)
    ssim_v = ssim_score(img_old, img_new)
    de = color_delta_e(img_old, img_new)
    result = classify(sim, p_dist, de, ssim_v)

    print(f"\n=== Case: {name} (embedding_backend = {embedder.name}) ===")
    print(f"  visual_similarity = {sim:.3f} | phash_dist = {p_dist} | ssim = {ssim_v:.3f} | color_dE = {de:.2f}")
    print(f"  -> classification = {result.classification} (confidence={result.confidence:.3f})")
    return result.classification


if __name__ == "__main__":
    pink = make_shirt((240, 130, 170), text="TEXAS")
    white = make_shirt((250, 250, 250), text="TEXAS")
    pink_resized = to_pil(pink.resize((150, 190)).resize((300, 380)))  # mô phỏng resize/nén
    different = make_shirt((240, 130, 170), text="TEXAS", icon=False, size=(300, 380))
    different_design = Image.new("RGB", (300, 380), (30, 30, 30))

    results = {}
    results["exact_duplicate (resize nhẹ)"] = run_case("EXACT_DUPLICATE kỳ vọng", pink, pink_resized)
    results["same_form_diff_color"] = run_case("SAME_FORM_DIFFERENT_COLOR kỳ vọng", pink, white)
    results["different_design"] = run_case("DIFFERENT_DESIGN kỳ vọng", pink, different_design)

    print("\n=== Tổng kết ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
