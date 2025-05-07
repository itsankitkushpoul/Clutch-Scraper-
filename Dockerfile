# Use official Python 3.11 slim image
FROM python:3.11-slim

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PIP_NO_CACHE_DIR=1

# Install OS-level dependencies required for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
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
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency file
COPY requirements.txt .

# Upgrade pip and install Python packages
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Install Playwright browsers
RUN python -m playwright install --with-deps

# Copy the app source code
COPY . .

# Expose port (adjust if needed)
EXPOSE 8000

# Command to run the FastAPI app (adjust module name if not "app")
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
