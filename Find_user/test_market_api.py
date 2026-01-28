import requests
import json

# Get a trade
resp = requests.get('https://data-api.polymarket.com/trades', params={'user': '0x80cd8310aa624521e9e1b2b53b568cafb0ef0273', 'limit': 1})
data = resp.json()
cid = data[0]['conditionId']
asset_id = data[0]['asset']
price = data[0]['price']
size = data[0]['size']
side = data[0]['side']

print(f"Trade: {side} {size} @ {price}")
print(f"conditionId: {cid}")
print(f"asset (token_id): {asset_id}")

# Get market info from CLOB API
mresp = requests.get(f'https://clob.polymarket.com/markets/{cid}')
m = mresp.json()
print(f"\nMarket closed: {m.get('closed')}")
print(f"Tokens:")
for t in m.get('tokens', []):
    print(f"  outcome={t.get('outcome')}, price={t.get('price')}, winner={t.get('winner')}, token_id={t.get('token_id')}")

# Check if our asset matches any token
print(f"\nOur asset matches: ", end="")
for t in m.get('tokens', []):
    if t.get('token_id') == asset_id:
        print(f"outcome={t.get('outcome')}, winner={t.get('winner')}")
        break
else:
    print("No match found")
