import json
import re

with open('cart_test.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Let's search for window variables or JSON in script tags
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
print(f"Total scripts: {len(scripts)}")

for i, s in enumerate(scripts):
    if "cart" in s.lower() and len(s) > 100:
        # Check for keywords like items, sku, price
        matches = [kw for kw in ['shop', 'items', 'seller', 'sku', 'price', 'cartList', 'cartItem'] if kw in s]
        if len(matches) >= 3:
            print(f"\n--- Script #{i} has {matches} (length {len(s)}) ---")
            lines = [l.strip() for l in s.splitlines() if any(m in l for m in matches)]
            for l in lines[:10]:
                print("  ", l[:120])
