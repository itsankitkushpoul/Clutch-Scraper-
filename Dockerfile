# ─── Base Image ────────────────────────────────────────────────────────────────
# Pin to a specific Playwright version for stability (e.g. 1.51.0)
FROM mcr.microsoft.com/playwright/python:v1.51.0-jammy

# ─── Environment ───────────────────────────────────────────────────────────────
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ─── App Directory ─────────────────────────────────────────────────────────────
WORKDIR /app

# ─── Dependencies ──────────────────────────────────────────────────────────────
# Copy & install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# ─── Copy Source ───────────────────────────────────────────────────────────────
COPY . .

# ─── Expose Port & Start ───────────────────────────────────────────────────────
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
