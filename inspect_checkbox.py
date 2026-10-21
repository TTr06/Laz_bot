import sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('cart_test.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("Looking for Select All checkbox elements...")
# Check input checkboxes
checkboxes = soup.find_all('input', {'type': 'checkbox'})
print(f"Total <input type='checkbox'> found: {len(checkboxes)}")
for i, cb in enumerate(checkboxes):
    print(f"CB {i}: id={cb.get('id')} name={cb.get('name')} class={cb.get('class')}")

# Check any element with text 'Select all' or 'Chọn tất cả'
for el in soup.find_all(True):
    text = el.get_text(strip=True)
    if 'select all' in text.lower() or 'chọn tất cả' in text.lower():
        if len(text) < 50:
            print(f"Tag <{el.name}> class={el.get('class')} -> text='{text}' parent={el.parent.name} parent_class={el.parent.get('class')}")
