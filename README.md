# Clutch Scraper API

A FastAPI-based web scraper for Clutch.co data.

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
playwright install chromium
```

2. Create a `.env` file based on `.env.example`

3. Run the server:
```bash
uvicorn main:app --reload
```

## Railway Deployment

1. Fork this repository to your GitHub account

2. Create a new project in Railway.app

3. Connect your GitHub repository

4. Add the following environment variables in Railway:
   - `HEADLESS=true`
   - `USE_AGENT=true`
   - `ENABLE_CORS=true`
   - `PAGE_TIMEOUT=30000`
   - `MAX_RETRIES=3`
   - Add `PROXY_LIST` if you have proxies

5. Railway will automatically:
   - Install dependencies
   - Install Playwright browsers
   - Start the server

## API Endpoints

- `GET /`: Health check
- `GET /health`: Detailed health check
- `POST /scrape`: Scrape data
  ```json
  {
    "base_url": "https://clutch.co/your-category",
    "total_pages": 3
  }
  ```

## Troubleshooting

If you get a 502 error:
1. Check the Railway logs
2. Ensure all environment variables are set
3. Try reducing `total_pages` in your request
4. Check if the target website is accessible

## License

MIT

## Features

- Scrapes company name, website, and location
- Supports featured and regular listings
- Configurable user agents and proxy support
- CORS-enabled for frontend integration

## Requirements

- Python 3.8+
- Playwright browser binaries

## Installation

```bash
git clone https://github.com/yourusername/clutch-scraper-api.git
cd clutch-scraper-api
python -m venv env
source env/bin/activate  # or env\Scripts\activate on Windows
pip install -r requirements.txt
playwright install
