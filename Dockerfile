FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Copy public application code
COPY api.py api_config.py auth.py rate_limiter.py usage.py stripe_billing.py server.py ./
COPY api_client.py email_sender.py ./
COPY tool_definition.json ./

# Download proprietary engine files from private GitHub repo
# Set GITHUB_TOKEN as a Railway build variable (classic PAT with repo scope)
ARG GITHUB_TOKEN
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -fsSL -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Accept: application/vnd.github.v3.raw" \
      "https://api.github.com/repos/98lukehall/renoun-engine/contents/core.py" -o core.py && \
    curl -fsSL -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Accept: application/vnd.github.v3.raw" \
      "https://api.github.com/repos/98lukehall/renoun-engine/contents/novelty_dual_pass.py" -o novelty_dual_pass.py && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Create data directory
RUN mkdir -p /root/.renoun

EXPOSE 8080

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
