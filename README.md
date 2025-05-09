# Clutch Scraper API

A FastAPI-based web scraper that extracts agency data from Clutch.co using Playwright.

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
