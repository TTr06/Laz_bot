import sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('cart_test.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

# Find main content container
for selector in ['#root', '#container', '.cart-container', '.cart-empty', '.list-header', '.cart-item']:
    elems = soup.select(selector)
    print(f"Selector '{selector}': found {len(elems)}")
    for e in elems[:2]:
        print("  Text:", e.get_text(separator=' ', strip=True)[:200])

# Let's search for "giỏ hàng" or "cart" in text
for div in soup.find_all(['div', 'p', 'span']):
    text = div.get_text(strip=True)
    if 'giỏ hàng' in text.lower() or 'cart is empty' in text.lower() or 'không có sản phẩm' in text.lower():
        print("Found cart status:", text[:200])
        break
