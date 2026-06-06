import json, sys
sys.stdout.reconfigure(encoding='utf-8')

# === Analyze anime_data_v2.json ===
print("=== anime_data_v2.json ===")
with open('anime_data_v2.json', 'r', encoding='utf-8') as f:
    mal_data = json.load(f)

all_keys = set()
genre_key_variants = set()
has_recs = 0
has_reviews = 0
rec_types = set()

for url, v in mal_data.items():
    all_keys.update(v.keys())
    if 'Genre' in v:
        genre_key_variants.add('Genre')
    if 'Genres' in v:
        genre_key_variants.add('Genres')
    if v.get('Recommendations'):
        has_recs += 1
        if isinstance(v['Recommendations'], list) and v['Recommendations']:
            rec_types.add(type(v['Recommendations'][0]).__name__)
    if v.get('Reviews'):
        has_reviews += 1

print(f"Total: {len(mal_data)}")
print(f"All keys: {sorted(all_keys)}")
print(f"Genre key variants: {genre_key_variants}")
print(f"Has recommendations: {has_recs}")
print(f"Has reviews: {has_reviews}")
print(f"Recommendation item types: {rec_types}")

# Show a sample rec
for url, v in mal_data.items():
    if v.get('Recommendations') and isinstance(v['Recommendations'], list) and len(v['Recommendations']) > 0:
        print(f"\nSample rec from {v.get('Title')}:")
        print(json.dumps(v['Recommendations'][:2], ensure_ascii=False, indent=2))
        break

# === Analyze anilist_data_raw.json ===
print("\n\n=== anilist_data_raw.json ===")
with open('anilist_data_raw.json', 'r', encoding='utf-8') as f:
    al_data = json.load(f)

print(f"Total: {len(al_data)}")
has_tags = sum(1 for d in al_data if d.get('tags'))
has_desc = sum(1 for d in al_data if d.get('description'))
has_recs_al = sum(1 for d in al_data if d.get('recommendations', {}).get('nodes'))
has_reviews_al = sum(1 for d in al_data if d.get('reviews', {}).get('nodes'))
has_genres_al = sum(1 for d in al_data if d.get('genres'))

print(f"Has tags: {has_tags}")
print(f"Has description: {has_desc}")
print(f"Has genres: {has_genres_al}")
print(f"Has recommendations: {has_recs_al}")
print(f"Has reviews: {has_reviews_al}")

# Check title structures for matching
print("\n=== Title matching analysis ===")
al_romaji = {d.get('title', {}).get('romaji', '').lower().strip() for d in al_data if d.get('title', {}).get('romaji')}
al_english = {d.get('title', {}).get('english', '').lower().strip() for d in al_data if d.get('title', {}).get('english')}
al_ids = {d['id'] for d in al_data}

mal_titles = set()
for url, v in mal_data.items():
    if v.get('Title'):
        mal_titles.add(v['Title'].lower().strip())

matched_by_title = mal_titles & al_romaji
matched_by_english = mal_titles & al_english

print(f"MAL unique titles: {len(mal_titles)}")
print(f"AniList romaji titles: {len(al_romaji)}")
print(f"AniList english titles: {len(al_english)}")
print(f"Matched by romaji: {len(matched_by_title)}")
print(f"Matched by english: {len(matched_by_english)}")
print(f"Combined match: {len(matched_by_title | matched_by_english)}")

# Check MAL ID extraction from URL
import re
mal_ids = set()
for url in mal_data.keys():
    m = re.search(r'/anime/(\d+)/', url)
    if m:
        mal_ids.add(int(m.group(1)))
print(f"\nMAL IDs extractable from URLs: {len(mal_ids)}")
print(f"Sample MAL IDs: {list(mal_ids)[:10]}")
