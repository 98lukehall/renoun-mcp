FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Copy application code (core.py must be present on the server)
COPY api.py api_config.py auth.py rate_limiter.py usage.py stripe_billing.py server.py ./
COPY tool_definition.json ./

# Create data directory
RUN mkdir -p /root/.renoun

# Default port
ENV RENOUN_API_PORT=8080
EXPOSE 8080

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
