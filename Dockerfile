# backend/Dockerfile
# Use the official Playwright image (latest tag ensures valid version)
FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Start server
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "${PORT:-8000}"]
