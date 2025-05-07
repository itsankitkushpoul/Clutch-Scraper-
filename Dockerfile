FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl unzip gnupg build-essential \
    libglib2.0-0 libnss3 libgconf-2-4 libatk1.0-0 \
    libatk-bridge2.0-0 libx11-xcb1 libxcomposite1 libxdamage1 \
    libxrandr2 libxss1 libxtst6 libxrender1 libasound2 \
    libgtk-3-0 xdg-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser dependencies
RUN python -m playwright install --with-deps

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
