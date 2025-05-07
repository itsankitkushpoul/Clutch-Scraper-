# Use Debian Bullseye slim for widest wheel compatibility
FROM python:3.11-slim-bullseye

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_NO_CACHE_DIR=1

# Install system deps for C‑extensions and Playwright
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential python3-dev libffi-dev libssl-dev \
      libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev cargo \
      wget curl gnupg unzip libgtk-3-0 libnss3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# 1) Core FastAPI deps (should pass)
RUN pip install --upgrade pip \
 && pip install --no-cache-dir fastapi uvicorn[standard] pydantic aiofiles

# 2) Scrapy + Playwright deps (isolates the failure)
RUN pip install --no-cache-dir scrapy scrapy-playwright playwright

# Install browsers
RUN python -m playwright install --with-deps

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
