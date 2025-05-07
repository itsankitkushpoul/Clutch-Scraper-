# ── Stage 1: Base OS & Python setup ────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_NO_CACHE_DIR=1

# Install OS packages (build tools + Playwright deps)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libffi-dev \
      libxml2-dev \
      libxslt1-dev \
      libssl-dev \
      python3-dev \
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

# Install Playwright browsers (Chromium, WebKit, Firefox)
RUN python -m playwright install --with-deps

# ── Stage 2: Application Copy & Runtime ──────────────────────────────────
FROM base AS runtime

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
