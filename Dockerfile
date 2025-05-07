FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Required system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget unzip build-essential libglib2.0-0 libnss3 libgconf-2-4 \
    libatk1.0-0 libatk-bridge2.0-0 libx11-xcb1 libxcomposite1 libxdamage1 \
    libxrandr2 libxss1 libxtst6 libxrender1 libasound2 \
    libgtk-3-0 xdg-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Upgrade pip and install Python deps with logging
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt --log install.log || (cat install.log && false)

# Install Playwright Browsers
RUN python -m playwright install --with-deps

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
