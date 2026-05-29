# MyAnimeList Data

This repository contains scripts to scrape and process data from MyAnimeList.

## Dataset

The resulting dataset generated from these scripts is hosted on Kaggle. You can find it here:
[MyAnimeList 2026 Data](https://www.kaggle.com/datasets/minhduc1212/myanimelist-2026-data)

## How to Use

1. **Install dependencies:**
   Make sure you have the required packages installed.
   ```bash
   pip install -r requirements.txt
   ```

2. **Crawl URLs:**
   First, run the URL crawler to collect the list of anime URLs to scrape.
   This will generate an `anime_urls.json` file.
   ```bash
   python get_url.py
   ```

3. **Scrape Anime Data:**
   Once the URLs are collected, run the data scraper to fetch the details for each anime.
   This will read from `anime_urls.json` and generate an `all_anime_data.json` file.
   ```bash
   python get_data.py
   ```
