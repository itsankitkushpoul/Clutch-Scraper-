# 1) Base
FROM python:3.11-slim

# 2) System deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libgtk-3-0 \
  && rm -rf /var/lib/apt/lists/*

# 3) Python deps
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir playwright \
 && playwright install --with-deps

# 4) Copy code
COPY main.py /app/main.py

# 5) Entrypoint
CMD ["python", "main.py"]
