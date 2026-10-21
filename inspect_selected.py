import json
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('cart_after_select_all.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

mod_data = d.get('module', {}).get('data', {})

print("=== CART ITEMS AFTER SELECT ALL ===")
for k, v in mod_data.items():
    if v.get('tag') == 'item':
        f = v.get('fields', {})
        title = f.get('title', '')
        cb = f.get('checkbox', {})
        valid = f.get('valid')
        status = f.get('status')
        p = f.get('price', {})
        dp = f.get('discountPrice', {})
        selected = cb.get('selected')
        enable = cb.get('enable')
        stock_tip = f.get('stockTip')
        
        print(f"\n* Item: {title[:60]}")
        print(f"  Valid: {valid} | Status: {status} | StockTip: {stock_tip}")
        print(f"  Selected: {selected} | Checkbox Enable: {enable}")
        print(f"  Base Price: {p.get('currentPrice')} ({p.get('price')})")
        if dp:
            print(f"  Discount/Promo Price: {dp}")

print("\n=== ORDER SUMMARY ===")
order_summary = mod_data.get('orderSummary_6', {})
print(json.dumps(order_summary, indent=2, ensure_ascii=False))
