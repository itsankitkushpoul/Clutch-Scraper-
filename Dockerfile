# ─── Base Image & Env Vars ─────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# ─── System Dependencies for Playwright & Chromium ─────────────────────────────
RUN apt-get update && apt-get install -y \
    wget curl gnupg unzip \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libgdk-pixbuf2.0-0 libnspr4 libnss3 \
    libxcomposite1 libxdamage1 libxrandr2 libxss1 \
    libgtk-3-0 libx11-xcb1 libxcb1 libxtst6 \
    fonts-liberation xdg-utils ca-certificates \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# ─── Python Dependencies ─────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ─── Install Playwright Browsers ────────────────────────────────────────────────
RUN playwright install --with-deps

# ─── Copy Source Code ───────────────────────────────────────────────────────────
# This assumes your folders look like:
#  .
#  ├── app.py
#  ├── requirements.txt
#  └── clutch_scraper/    ← your Scrapy project
COPY . .

# ─── Expose & Startup ──────────────────────────────────────────────────────────
EXPOSE 8000

# Use Uvicorn to serve FastAPI; it will shell out to run the Scrapy spider.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
