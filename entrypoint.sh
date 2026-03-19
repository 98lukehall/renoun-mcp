#!/bin/bash
set -e

# Ensure persistent data directory exists
DATA_DIR="${RENOUN_DATA_DIR:-/root/.renoun}"
mkdir -p "$DATA_DIR"
echo "[entrypoint] Data directory: $DATA_DIR"

# Download proprietary engine files from private GitHub repo at startup
# GITHUB_TOKEN must be set as a Railway env var
if [ -n "$GITHUB_TOKEN" ] && [ ! -f /app/core.py ]; then
    echo "[entrypoint] Downloading engine files from private repo..."
    python3 -c "
import urllib.request, os
token = os.environ['GITHUB_TOKEN']
headers = {
    'Authorization': f'Bearer {token}',
    'Accept': 'application/vnd.github.v3.raw',
}
base = 'https://api.github.com/repos/98lukehall/renoun-engine/contents'
for fname in ['core.py', 'novelty_dual_pass.py', 'regime_service.py', 'regime_halflife.py', 'regime_drift.py']:
    url = f'{base}/{fname}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        with open(f'/app/{fname}', 'wb') as f:
            f.write(resp.read())
    print(f'  Downloaded {fname}')
print('[entrypoint] Engine files ready.')
"
elif [ -f /app/core.py ]; then
    echo "[entrypoint] Engine files already present."
else
    echo "[entrypoint] WARNING: GITHUB_TOKEN not set, engine will use remote API fallback."
fi

# Bootstrap API keys from environment variables on every startup
# With RENOUN_DATA_DIR + persistent volume, agent keys also survive redeploys
# Set RENOUN_BOOTSTRAP_KEYS in Railway as a JSON array:
#   [{"raw_key":"rn_live_...","tier":"pro","owner":"user@email.com"}]
python3 -c "
import os, json
bootstrap = os.environ.get('RENOUN_BOOTSTRAP_KEYS', '')
if not bootstrap:
    print('[entrypoint] No RENOUN_BOOTSTRAP_KEYS set, skipping key bootstrap.')
else:
    from auth import _load_keys, _save_keys, _hash_key, KEY_PREFIX
    from datetime import datetime
    data = _load_keys()
    existing_hashes = {e['key_hash'] for e in data['keys']}
    keys = json.loads(bootstrap)
    added = 0
    for k in keys:
        raw_key = k['raw_key']
        key_hash = _hash_key(raw_key)
        if key_hash not in existing_hashes:
            entry = {
                'key_id': k.get('key_id', KEY_PREFIX + raw_key[-16:]),
                'key_hash': key_hash,
                'tier': k.get('tier', 'pro'),
                'owner': k.get('owner', ''),
                'created_at': k.get('created_at', datetime.utcnow().isoformat()),
                'active': True,
            }
            # Restore Stripe linking if present
            if k.get('stripe_customer_id'):
                entry['stripe_customer_id'] = k['stripe_customer_id']
            if k.get('stripe_subscription_id'):
                entry['stripe_subscription_id'] = k['stripe_subscription_id']
            data['keys'].append(entry)
            existing_hashes.add(key_hash)
            added += 1
    if added:
        _save_keys(data)
        print(f'[entrypoint] Bootstrapped {added} API key(s).')
    else:
        print('[entrypoint] All bootstrap keys already exist.')
"

# Start the server
exec uvicorn api:app --host 0.0.0.0 --port 8080
