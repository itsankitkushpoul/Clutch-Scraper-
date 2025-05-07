# ── Stage 1: Build with full Debian slim ────────────────────────────────────
FROM python:3.11-slim-bullseye AS builder

# Environment
ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_NO_CACHE_DIR=1

# Install system build deps + Playwright runtime deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      python3-dev \
      libffi-dev \
      libssl-dev \
      libxml2-dev \
      libxslt1-dev \
      libjpeg-dev \
      zlib1g-dev \
      libpq-dev \
      cargo \
      wget \
      curl \
      gnupg \
      unzip \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libcups2 \
      libdbus-1-3 \
      libgdk-pixbuf2.0-0 \
      libnspr4 \
      libnss3 \
      libxcomposite1 \
      libxdamage1 \
      libxrandr2 \
      libxss1 \
      libgtk-3-0 \
      libx11-xcb1 \
      libxcb1 \
      libxtst6 \
      fonts-liberation \
      xdg-utils \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy & install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN python -m playwright install --with-deps

# ── Stage 2: Runtime ───────────────────────────────────────────────────────
FROM python:3.11-slim-bullseye

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Copy installed packages & browsers from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /ms-playwright /ms-playwright

WORKDIR /app
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
