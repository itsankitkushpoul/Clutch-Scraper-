# ─── Start with official Python 3.11 image ─────────────────────────────────────
FROM python:3.11-slim

# ─── Set environment variables ────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PIP_NO_CACHE_DIR=1

# ─── Install system dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl unzip gnupg \
    build-essential python3-dev libffi-dev libssl-dev \
    libxml2 libxslt1-dev zlib1g-dev \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
    libgdk-pixbuf2.0-0 libnspr4 libnss3 libxcomposite1 libxdamage1 \
    libxrandr2 libxss1 libgtk-3-0 libx11-xcb1 libxcb1 libxtst6 \
    fonts-liberation xdg-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ─── Set work directory ───────────────────────────────────────────────────────
WORKDIR /app

# ─── Copy dependency list ─────────────────────────────────────────────────────
COPY requirements.txt .

# ─── Upgrade pip and install Python dependencies ──────────────────────────────
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# ─── Install Playwright and its browsers ──────────────────────────────────────
RUN playwright install --with-deps

# ─── Copy project code ────────────────────────────────────────────────────────
COPY . .

# ─── Expose port and start FastAPI server ─────────────────────────────────────
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
