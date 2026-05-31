import requests
from bs4 import BeautifulSoup
import re
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def fetch_url(url, headers):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.text
            elif response.status_code == 404:
                logging.warning(f"[Worker] 404 Not Found: {url}")
                return None
            else:
                logging.warning(f"[Worker] Error {response.status_code} fetching {url}. Retrying...")
                time.sleep(2)
        except Exception as e:
            logging.warning(f"[Worker] Exception {e} fetching {url}. Retrying...")
            time.sleep(2)
    return None

def get_data(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    html_content = fetch_url(url, headers)
    if not html_content:
        return None
        
    anime_data = parse_anime_data(html_content)
    
    # Fetch reviews
    reviews_url = url + '/reviews?spoiler=on&sort=suggested'
    reviews_html = fetch_url(reviews_url, headers)
    anime_data['Reviews'] = []
    if reviews_html:
        soup = BeautifulSoup(reviews_html, 'html.parser')
        reviews = soup.select('.review-element')
        for rev in reviews[:5]:
            text_el = rev.select_one('.text')
            if text_el:
                anime_data['Reviews'].append(text_el.text.strip())
                
    # Fetch recommendations
    recs_url = url + '/userrecs'
    recs_html = fetch_url(recs_url, headers)
    anime_data['Recommendations'] = []
    if recs_html:
        soup = BeautifulSoup(recs_html, 'html.parser')
        recs = soup.select('div.borderClass table')
        for table in recs:
            a_tag = table.select_one('strong')
            if not a_tag:
                continue
            title = a_tag.text.strip()
            text_el = table.select_one('.detail-user-recs-text')
            text = text_el.text.strip() if text_el else ''
            anime_data['Recommendations'].append({'Title': title, 'Text': text})
            
    return anime_data

def parse_anime_data(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    anime_data = {}

    # Title
    title_element = soup.select_one('h1.title-name')
    if title_element:
        anime_data['Title'] = title_element.text.strip()

    # Synopsis
    synopsis_element = soup.find('p', itemprop='description')
    if synopsis_element:
        synopsis = synopsis_element.text.strip()
        synopsis = re.sub(r'\n+', '\n', synopsis)
        anime_data['Synopsis'] = synopsis

    # Sidebar Information
    for div in soup.select('div.spaceit_pad'):
        dark_text_span = div.find('span', class_='dark_text')
        if dark_text_span:
            key = dark_text_span.text.strip().replace(':', '')
            dark_text_span.extract()
            
            a_tags = div.find_all('a')
            if a_tags and key in ['Producers', 'Studios', 'Genres', 'Themes', 'Demographic']:
                values = [a.text.strip() for a in a_tags if 'add some' not in a.text.lower()]
                values = list(dict.fromkeys(values))
                value = ', '.join(values)
            else:
                value = div.text.strip()
                value = re.sub(r'\s+', ' ', value)
                value = value.replace(' ,', ',')
                
            anime_data[key] = value

    # Additional cleanup for specific fields
    score_element = soup.find('span', itemprop='ratingValue')
    if score_element:
        anime_data['Score'] = score_element.text.strip()
    
    ranked_element = soup.select_one('span.numbers.ranked strong')
    if ranked_element:
        anime_data['Ranked'] = ranked_element.text.strip()
        
    popularity_element = soup.select_one('span.numbers.popularity strong')
    if popularity_element:
        anime_data['Popularity'] = popularity_element.text.strip()
        
    members_element = soup.select_one('span.numbers.members strong')
    if members_element:
        anime_data['Members'] = members_element.text.strip()

    return anime_data

URLS_FILE = 'anime_urls.json'
OUTPUT_FILE = 'anime_data_v2.json'

file_lock = threading.Lock()

def load_all_urls():
    if not os.path.exists(URLS_FILE):
        logging.error(f"Error: {URLS_FILE} not found. Please run get_url.py first.")
        return []
    with open(URLS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_existing_data():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_data(data):
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def process_url(url, all_data, progress_counter):
    logging.info(f"[Thread-{threading.get_ident()}] Fetching: {url}")
    data = get_data(url)
    
    if data is not None:
        data['url'] = url
        with file_lock:
            all_data[url] = data
            progress_counter[0] += 1
            
            if progress_counter[0] % 10 == 0:
                save_data(all_data)
                logging.info(f"[*] Progress saved. Total records: {len(all_data)}")
                
    time.sleep(1)

def main():
    urls = load_all_urls()
    if not urls:
        return
        
    all_data = load_existing_data()
    
    urls_to_process = [url for url in urls if url not in all_data]
    logging.info(f"Total URLs: {len(urls)} | Already processed: {len(all_data)} | To process: {len(urls_to_process)}")
    
    progress_counter = [0]

    with ThreadPoolExecutor(max_workers=5) as executor:
        for url in urls_to_process:
            executor.submit(process_url, url, all_data, progress_counter)
            
    with file_lock:
        save_data(all_data)
    logging.info(f"[*] Finished crawling! Total records in DB: {len(all_data)}")

if __name__ == "__main__":
    main()