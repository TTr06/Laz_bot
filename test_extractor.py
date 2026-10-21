import json

with open("cart_init_data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

mod_data = data.get("module", {}).get("data", {})
products = []

for key, val in mod_data.items():
    if val.get("tag") == "item":
        fields = val.get("fields", {})
        title = fields.get("title", "")
        price_info = fields.get("price", {}) or {}
        price = price_info.get("price")
        price_text = price_info.get("currentPrice", "")
        sku_info = fields.get("sku", {}) or fields.get("skuInfo", {})
        sku_text = sku_info.get("skuText", "")
        url = fields.get("url") or fields.get("itemUrl") or ""
        
        products.append({
            "name": title,
            "price": price,
            "price_text": price_text,
            "sku": sku_text,
            "url": url
        })

print(f"Successfully extracted {len(products)} products from cart!")
for i, p in enumerate(products, 1):
    print(f"{i}. {p['name'][:60]} | Giá: {p['price']:,.0f}₫ | SKU: {p['sku']}")
