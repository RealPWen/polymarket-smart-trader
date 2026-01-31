import requests
import json
addr = '0xd7f85d0eb0fe0732ca38d9107ad0d4d01b1289e4'

url = 'https://data-api.polymarket.com/closed-positions'
r = requests.get(url, params={'user': addr, 'limit': 50})
data = r.json()

with open('output/tdrhrhhd_closed.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"Closed Positions: {len(data)} records")
print()

# Top 10 by PnL
print("Top 10 by Realized PnL:")
for p in sorted(data, key=lambda x: float(x.get('realizedPnl', 0) or 0), reverse=True)[:10]:
    title = p.get('title', '?')[:45]
    pnl = float(p.get('realizedPnl', 0) or 0)
    bought = float(p.get('totalBought', 0) or 0)
    event = p.get('eventSlug', '?')[:35]
    print(f"  {title}")
    print(f"    Event: {event}")
    print(f"    Bought: ${bought:,.0f} | PnL: ${pnl:,.0f}")
    print()

# Summary
total_pnl = sum(float(p.get('realizedPnl', 0) or 0) for p in data)
total_bought = sum(float(p.get('totalBought', 0) or 0) for p in data)
print(f"TOTAL: Bought ${total_bought:,.0f} | PnL ${total_pnl:,.0f}")
