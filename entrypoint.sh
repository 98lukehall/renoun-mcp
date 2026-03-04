#!/bin/bash
set -e

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
for fname in ['core.py', 'novelty_dual_pass.py']:
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

# Start the server
exec uvicorn api:app --host 0.0.0.0 --port 8080
