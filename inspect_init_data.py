import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('cart_test.html', 'r', encoding='utf-8') as f:
    html = f.read()

m = re.search(r'window\.__initData__\s*=\s*(\{[\s\S]*?\});\s*(?:</script>|\n)', html)
if not m:
    m = re.search(r'window\.__initData__\s*=\s*(\{.*?\});', html)

if m:
    data_str = m.group(1)
    print("Found window.__initData__! Length:", len(data_str))
    data = json.loads(data_str)
    
    # Save to file to inspect cleanly
    with open("cart_init_data.json", "w", encoding="utf-8") as out:
        json.dump(data, out, indent=2, ensure_ascii=False)
    print("Saved to cart_init_data.json")

    # Let's inspect data keys
    mod_data = data.get("module", {}).get("data", {})
    print(f"Total keys in module.data: {len(mod_data)}")
    for k, v in list(mod_data.items())[:20]:
        tag = v.get("tag") or v.get("componentType") or type(v).__name__
        fields = v.get("fields", {})
        title = fields.get("title") or fields.get("itemName")
        price = fields.get("price") or fields.get("itemPrice") or fields.get("payPrice")
        if title or price:
            print(f"Key: {k} (tag: {tag}) -> Title: {title} | Price: {price}")
else:
    print("window.__initData__ not matched by regex!")
