FROM python:3.10-slim

# system deps for playwright
RUN apt-get update && apt-get install -y \
    curl gnupg && \
    curl -sSL https://deb.nodesource.com/setup_16.x | bash - && \
    apt-get install -y nodejs build-essential libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libxcomposite1 libxdamage1 libxrandr2 libasound2 libpangocairo-1.0-0 \
    libxss1 libgtk-3-0 libgbm-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

COPY main.py ./

# default envs (you can override in Railway UI)
ENV BASE_URL="https://clutch.co/agencies/digital-marketing"
ENV TOTAL_PAGES="3"
ENV HEADLESS="true"

# ⛔ OLD (wrong): CMD ["python", "main.py"]
# ✅ NEW (correct): Start FastAPI using uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
