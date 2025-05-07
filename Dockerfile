# ─── Base Image & Env ──────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# ─── System Dependencies (build-tools, libs for scrapy & playwright) ─────────────
RUN apt-get update && apt-get install -y \
    # build tools for Python packages
    build-essential \
    python3-dev \
    libxml2-dev libxslt1-dev \
    libffi-dev libssl-dev \
    # Rust toolchain (for cryptography on 3.11 wheels)  
    cargo \
    # Playwright/Chromium libs
    wget curl gnupg unzip \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libgdk-pixbuf2.0-0 libnspr4 libnss3 \
    libxcomposite1 libxdamage1 libxrandr2 libxss1 \
    libgtk-3-0 libx11-xcb1 libxcb1 libxtst6 libgbm-dev \
    fonts-liberation xdg-utils ca-certificates \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# ─── Python Dependencies ─────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ─── Install Playwright Browsers ────────────────────────────────────────────────
RUN playwright install --with-deps

# ─── Copy You Code & Expose ─────────────────────────────────────────────────────
COPY . .

EXPOSE 8000

# ─── Run FastAPI & Shell-out to Scrapy ──────────────────────────────────────────
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
