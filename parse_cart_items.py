import sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('cart_test.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("Finding cart items...")

# Let's search for links or items
for el in soup.find_all(True):
    cls = el.get("class", [])
    if any("item" in c.lower() for c in cls):
        text = el.get_text(separator=" | ", strip=True)
        if "₫" in text or "d" in text or "vnd" in text.lower():
            if len(text) < 300 and len(text) > 20:
                print(f"Class: {cls} -> {text}\n")
