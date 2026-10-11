FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY domain ./domain
COPY apps ./apps
USER 10001:10001

CMD ["uvicorn", "apps.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
