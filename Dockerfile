# ─── Start with official Python 3.11 image ─────────────────────────────────────
FROM python:3.11-slim

# ─── Environment settings ──────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PIP_NO_CACHE_DIR=1

# ─── Set up working directory ──────────────────────────────────────────────────
WORKDIR /app

# ─── Install dependencies ─────────────────────────────────────────────────────
# Install system dependencies for Playwright browsers
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
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
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# ─── Install Python dependencies ───────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ─── Install Playwright and its browsers ───────────────────────────────────────
RUN pip install playwright && \
    playwright install --with-deps

# ─── Copy application code ─────────────────────────────────────────────────────
COPY . .

# ─── Expose port and run FastAPI with Uvicorn ─────────────────────────────────
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
