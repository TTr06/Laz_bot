import sys
import re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('cart_test.html', 'r', encoding='utf-8') as f:
    html = f.read()

print('HTML length:', len(html))
keywords = ['cart-item', 'cart', 'checkbox', 'checkout', 'giá', '₫', 'vnd', 'tổng', 'shop', 'item', 'price', 'product']
for kw in keywords:
    matches = len(re.findall(kw, html, re.IGNORECASE))
    print(f'Keyword "{kw}": {matches} occurrences')

# Let's search for price pattern
prices = re.findall(r'₫\s*[\d\.,]+|[\d\.,]+\s*₫', html)
print('\nFound prices (sample):', prices[:10])

# Let's search for potential product titles or item containers
items = re.findall(r'class="[^"]*(?:cart|item|product|price)[^"]*"', html, re.IGNORECASE)
print('\nSample matching classes:', list(set(items))[:15])

# Let's check window or script tags containing cart data
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
for i, s in enumerate(scripts):
    if any(k in s.lower() for k in ['cartdata', 'cartlist', 'itemlist', 'shoplist', 'cart_items']):
        print(f"\nScript {i} matches cart keywords! Length: {len(s)}")
        print(s[:500])
