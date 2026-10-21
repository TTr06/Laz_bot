import sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('cart_test.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

body_text = soup.body.get_text(separator=' | ', strip=True) if soup.body else ''
print('Length of body text:', len(body_text))
print('\nSample body text:\n', body_text[:1500])

# Check account header
headers = soup.select('.lzd-nav-cart, .my-account-name, #topActionUser, [data-spm="myacc"]')
print('\nHeader elements found:', [h.get_text(strip=True) for h in headers])
