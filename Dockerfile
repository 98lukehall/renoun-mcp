FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Copy public application code
COPY api.py api_config.py auth.py rate_limiter.py usage.py stripe_billing.py server.py ./
COPY api_client.py email_sender.py pre_tag.py weighted_analysis.py ./
COPY renoun_analyze.py renoun_compare.py renoun_store.py renoun_format.py ./
COPY tool_definition.json ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Create data directory
RUN mkdir -p /root/.renoun

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
