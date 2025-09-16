FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY sdtrepricer ./sdtrepricer
COPY docs ./docs

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

COPY docker-compose.yml Makefile .env.example ./

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request, sys;\
import json;\
req=urllib.request.Request('http://localhost:8000/api/metrics/dashboard');\
req.add_header('Accept','application/json');\
resp=urllib.request.urlopen(req, timeout=3);\
sys.exit(0 if resp.status < 500 else 1)" || exit 1

CMD ["uvicorn", "sdtrepricer.app:app", "--host", "0.0.0.0", "--port", "8000"]
