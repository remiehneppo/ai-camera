FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=10001:10001 domain ./domain
COPY --chown=10001:10001 apps ./apps
RUN mkdir -p /tmp/ai-camera-evidence && chown 10001:10001 /tmp/ai-camera-evidence
USER 10001:10001

CMD ["uvicorn", "apps.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
