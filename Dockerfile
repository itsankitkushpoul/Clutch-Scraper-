# Use the official Playwright image with Python support
FROM mcr.microsoft.com/playwright/python:1.35.0-focal

# Ensure we don’t accidentally cache pip layers
ENV PIP_NO_CACHE_DIR=1

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create and use /app as working directory
WORKDIR /app

# Copy only requirements first (leveraging docker cache)
COPY requirements.txt .

# Install Python deps
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose port
EXPOSE 8000

# Run FastAPI via Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
