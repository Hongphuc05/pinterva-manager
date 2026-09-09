from app.adapters.db.models import Order
from app.application.crawl import apply_crawled_product_gallery


def test_fallback_crawl_cannot_replace_a_richer_extension_gallery():
    order = Order(
        external_order_id="DJ1",
        state="OPEN",
        product_image_urls=["https://assets.printerval.com/one.jpg", "https://assets.printerval.com/two.jpg"],
    )
    apply_crawled_product_gallery(order, ["https://assets.printerval.com/fallback.jpg"])
    assert order.product_image_urls == [
        "https://assets.printerval.com/one.jpg",
        "https://assets.printerval.com/two.jpg",
    ]
