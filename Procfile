web: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: celery -A main.celery_app worker --concurrency=4 --loglevel=info
