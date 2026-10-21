import sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('cart_after_select_all.json', 'r', encoding='utf-8') as f:
    pass

# Read cart_selected.html or let's inspect the DOM prices
# Let's see what is inside cart_after_select_all.json
import json
with open('cart_after_select_all.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

mod_data = d.get('module', {}).get('data', {})

print("=== SO SÁNH GIÁ GỐC VÀ GIÁ KHUYẾN MÃI (DISCOUNTED) ===")
for k, v in mod_data.items():
    if v.get('tag') == 'item':
        f = v.get('fields', {})
        title = f.get('title', '')
        valid = f.get('valid')
        p = f.get('price', {}) or {}
        dp = f.get('discountPrice', {}) or {}
        
        base_price_str = p.get('currentPrice', 'N/A')
        base_num = p.get('price')
        
        # Check discount price
        discount_price_str = dp.get('price')
        discount_num = dp.get('priceAmtValue')
        
        status_tag = "[CÒN HÀNG]" if valid else "[HẾT HÀNG/KHÔNG KHẢ DỤNG]"
        
        if discount_num:
            print(f"{status_tag} {title[:55]}")
            print(f"   Giá gốc: {base_price_str}₫  -->  🔥 GIÁ THỰC TẾ: {discount_num:,.0f}₫ (Giảm {base_num - discount_num:,.0f}₫)\n")
        else:
            print(f"{status_tag} {title[:55]}")
            print(f"   Giá thực tế: {base_num:,.0f}₫\n")
