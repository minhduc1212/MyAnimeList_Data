"""
fetch_anilist_v2.py  —  Fetch ALL anime từ AniList → match vào MAL data
========================================================================
Strategy (ngược lại so với v1):
  STEP 1: Fetch toàn bộ AniList catalogue qua pagination (50 anime/page)
          → lưu anilist_raw.json
  STEP 2: Match AniList entries vào MAL cleaned data theo tên
          → lưu anilist_enrichment.json  {mal_url: {tags, recs, ...}}
  STEP 3: (chạy riêng) merge_anilist.py thêm vào prepared_anime.json

Tại sao hướng này tốt hơn:
  - Không bị 404 "not found" vì lấy theo ID/page chứ không search tên
  - AniList có ~20k anime → cover gần hết MAL data
  - Match 2 chiều: 1 MAL entry có thể match nhiều AniList title variants

Rate limit: 30 req/phút (degraded) → delay 2.1s
~20k anime / 50 per page = 400 pages → ~14 phút fetch
Match bằng string similarity → không tốn thêm request nào

Chạy:
  python fetch_anilist_v2.py          # full run
  python fetch_anilist_v2.py --step 1 # chỉ fetch AniList
  python fetch_anilist_v2.py --step 2 # chỉ match (nếu đã có anilist_raw.json)
"""

import argparse
import json
import time
import re
import unicodedata
import logging
from pathlib import Path
import requests
import sys

# Reconfigure stdout/stderr to utf-8 for Windows console Unicode safety
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


# ── Config ────────────────────────────────────────────────────────────────────
MAL_INPUT_FILE    = Path("cleaned_anime_data_v2.json")          # raw MAL data hoặc prepared list
ANILIST_RAW_FILE  = Path("anilist_data_raw.json")         # cache AniList catalogue
ENRICHMENT_FILE   = Path("anilist_enrichment.json")  # output: mal_url → anilist data
CHECKPOINT_FILE   = Path("anilist_page_checkpoint.txt")

ANILIST_URL  = "https://graphql.anilist.co"
PER_PAGE     = 50     # max của AniList API
DELAY        = 2.1    # giây giữa requests (an toàn với 30 rpm)
MAX_RETRIES  = 5

# Match threshold — thấp hơn thì match nhiều hơn nhưng có thể sai
MATCH_THRESHOLD = 0.60

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler("fetch_anilist_v2.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
#  STEP 1 — Fetch toàn bộ AniList catalogue
# ════════════════════════════════════════════════════════════════════════════

PAGE_QUERY = """
query ($page: Int, $start_greater: FuzzyDateInt, $start_lesser: FuzzyDateInt) {
  Page(page: $page, perPage: 50) {
    pageInfo {
      hasNextPage
    }
    media(type: ANIME, startDate_greater: $start_greater, startDate_lesser: $start_lesser, sort: ID) {
      id
      title {
        romaji
        english
        native
        userPreferred
      }
      tags {
        name
        category
        rank
        isGeneralSpoiler
        isMediaSpoiler
      }
      averageScore
      meanScore
      description(asHtml: false)
      genres
      season
      seasonYear
      status
      episodes
      duration
      reviews(perPage: 5, sort: RATING_DESC) {
        nodes {
          id
          summary
          rating
          score
        }
      }
      recommendations(perPage: 10, sort: RATING_DESC) {
        nodes {
          rating
          mediaRecommendation {
            id
            title {
              romaji
              english
              native
              userPreferred
            }
          }
        }
      }
    }
  }
}
"""


def gql_request(query: str, variables: dict, attempt: int = 0) -> dict | None:
    try:
        resp = requests.post(
            ANILIST_URL,
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60)) + 2
            log.warning("429 — waiting %ds", wait)
            time.sleep(wait)
            return gql_request(query, variables, attempt + 1)

        if resp.status_code != 200:
            log.error("HTTP %d", resp.status_code)
            if attempt < MAX_RETRIES:
                time.sleep(5 * (attempt + 1))
                return gql_request(query, variables, attempt + 1)
            return None

        return resp.json().get("data")

    except Exception as e:
        log.error("Request error: %s", e)
        if attempt < MAX_RETRIES:
            time.sleep(5)
            return gql_request(query, variables, attempt + 1)
        return None


def fetch_all_anilist() -> list[dict]:
    """Fetch toàn bộ AniList catalogue bằng cách chia nhỏ theo startDate range để tránh giới hạn 5000 offset và lỗi seasonYear của AniList."""
    catalogue: list[dict] = []

    # Load existing cache if any
    if ANILIST_RAW_FILE.exists():
        with ANILIST_RAW_FILE.open(encoding="utf-8") as f:
            catalogue = json.load(f)
        log.info("Loaded existing cache: %d entries", len(catalogue))

    # We partition by years. We represent pre-1940 as a single partition "1939".
    # Range of partitions: 1939 (covers pre-1940), 1940, 1941, ..., 2030.
    start_year = 1939
    start_page = 1
    if CHECKPOINT_FILE.exists():
        try:
            parts = CHECKPOINT_FILE.read_text().strip().split(",")
            if len(parts) == 2:
                start_year = int(parts[0])
                start_page = int(parts[1])
                log.info("Resuming from partition/year %d, page %d", start_year, start_page)
            else:
                # Reset if checkpoint is in old ID format
                start_year = 1939
                start_page = 1
                log.info("Resetting checkpoint to 1939, page 1")
        except ValueError:
            log.info("Could not parse checkpoint, starting from 1939, page 1")

    is_first_year = True
    for year in range(start_year, 2031):
        page = start_page if is_first_year else 1
        is_first_year = False

        if year == 1939:
            log.info("--- Starting Pre-1940 Partition ---")
            variables = {
                "page": page,
                "start_greater": 19000000,
                "start_lesser": 19391231
            }
        else:
            log.info("--- Starting Year %d ---", year)
            variables = {
                "page": page,
                "start_greater": year * 10000,
                "start_lesser": year * 10000 + 1231
            }

        while True:
            data = gql_request(PAGE_QUERY, variables)
            if not data:
                log.error("Failed at year %d, page %d, stopping", year, page)
                break

            page_data  = data.get("Page", {})
            page_info  = page_data.get("pageInfo", {})
            media_list = page_data.get("media", [])

            if not media_list:
                log.info("Year %d — no more media at page %d", year, page)
                break

            new_entries = 0
            for media in media_list:
                if media:
                    # Deduplicate to prevent overlapping elements
                    if not any(item.get("id") == media["id"] for item in catalogue):
                        catalogue.append(media)
                        new_entries += 1

            log.info(
                "Year %d, Page %d fetched — got %d entries (%d new, total catalog so far: %d)",
                year, page, len(media_list), new_entries, len(catalogue),
            )

            # Save checkpoint + incremental cache
            CHECKPOINT_FILE.write_text(f"{year},{page}")
            with ANILIST_RAW_FILE.open("w", encoding="utf-8") as f:
                json.dump(catalogue, f, ensure_ascii=False, indent=2)

            if not page_info.get("hasNextPage") or len(media_list) < PER_PAGE:
                break

            page += 1
            variables["page"] = page
            time.sleep(DELAY)

    log.info("✅ Finished fetching AniList catalogue! Total entries: %d", len(catalogue))
    return catalogue


# ════════════════════════════════════════════════════════════════════════════
#  STEP 2 — Match AniList → MAL data
# ════════════════════════════════════════════════════════════════════════════

def normalize(text: str) -> str:
    """
    Normalize title để match: lowercase, bỏ dấu, bỏ ký tự đặc biệt.
    "Fullmetal Alchemist: Brotherhood" → "fullmetal alchemist brotherhood"
    """
    if not text:
        return ""
    # Bỏ dấu unicode (é → e)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Lowercase, bỏ ký tự không phải chữ/số/space
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def title_similarity(a: str, b: str) -> float:
    """
    Simple token overlap similarity — đủ nhanh cho 20k×25k match.
    Không cần fuzzy library.
    """
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    # Loại bỏ stop words ngắn không phân biệt
    noise = {"the", "a", "an", "of", "in", "to", "no", "wa", "ga", "wo"}
    tokens_a -= noise
    tokens_b -= noise
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union        = tokens_a | tokens_b
    jaccard      = len(intersection) / len(union)

    # Bonus nếu một cái là substring của cái kia (sau normalize)
    if na in nb or nb in na:
        jaccard = min(1.0, jaccard + 0.2)

    return jaccard


def get_all_mal_titles(raw: dict) -> list[str]:
    """Lấy tất cả variant tên của 1 MAL entry."""
    titles = []
    for key in ("Title", "English", "Synonyms", "Japanese"):
        val = raw.get(key, "")
        if not val:
            continue
        # Synonyms có thể là "A, B, C" hoặc "A | B | C"
        if key == "Synonyms":
            for sep in (",", "|"):
                if sep in val:
                    titles.extend([t.strip() for t in val.split(sep) if t.strip()])
                    break
            else:
                titles.append(val.strip())
        else:
            titles.append(val.strip())
    return [t for t in titles if t]


def get_all_anilist_titles(media: dict) -> list[str]:
    """Lấy tất cả variant tên của 1 AniList entry."""
    title_obj = media.get("title") or {}
    titles = []
    for key in ("english", "romaji", "native", "userPreferred"):
        val = title_obj.get(key, "")
        if val:
            titles.append(val)
    return titles


def best_match_score(mal_titles: list[str], al_titles: list[str]) -> float:
    """Tính max similarity giữa mọi cặp (mal_title, al_title)."""
    best = 0.0
    for mt in mal_titles:
        for at in al_titles:
            s = title_similarity(mt, at)
            if s > best:
                best = s
            if best == 1.0:
                return 1.0
    return best


def parse_anilist_entry(media: dict) -> dict:
    """Extract tags + recs từ 1 AniList media object."""
    # Tags — bỏ spoiler, lấy rank >= 60
    tags = []
    for tag in (media.get("tags") or []):
        if tag.get("isGeneralSpoiler") or tag.get("isMediaSpoiler"):
            continue
        name = tag.get("name", "")
        rank = tag.get("rank", 0)
        category = tag.get("category", "")
        if name and rank >= 60:
            tags.append({"name": name, "rank": rank, "category": category})
    tags.sort(key=lambda x: x["rank"], reverse=True)

    # Recommendations
    recs = []
    for node in ((media.get("recommendations") or {}).get("nodes") or []):
        if not node:
            continue
        rating   = node.get("rating", 0)
        rec_med  = node.get("mediaRecommendation")
        if not rec_med or not rating:
            continue
        t = rec_med.get("title") or {}
        title = t.get("english") or t.get("romaji") or t.get("userPreferred") or t.get("native") or ""
        if title:
            recs.append({"title": title, "rating": rating})

    # Reviews
    reviews = []
    for node in ((media.get("reviews") or {}).get("nodes") or []):
        if not node:
            continue
        summary = node.get("summary", "")
        rating  = node.get("rating", 0)
        score   = node.get("score", 0)
        reviews.append({
            "id": node.get("id"),
            "summary": summary,
            "rating": rating,
            "score": score
        })

    al_titles = get_all_anilist_titles(media)

    return {
        "anilist_id":    media.get("id"),
        "anilist_title": al_titles[0] if al_titles else "",
        "average_score": media.get("averageScore"),
        "mean_score":    media.get("meanScore"),
        "description":   media.get("description"),
        "genres":        media.get("genres", []),
        "status":        media.get("status"),
        "episodes":      media.get("episodes"),
        "duration":      media.get("duration"),
        "season":        media.get("season"),
        "season_year":   media.get("seasonYear"),
        "tags":          [t["name"] for t in tags[:20]],
        "tag_details":   tags[:20],
        "anilist_recs":  recs,
        "reviews":       reviews,
    }


def match_anilist_to_mal(catalogue: list[dict], mal_data: dict) -> dict:
    """
    Match từng AniList entry vào MAL data.
    mal_data: {mal_url: raw_mal_dict}
    Returns: {mal_url: anilist_enrichment}
    """
    log.info("Building MAL title index...")
    # Build index: mal_url → list of normalized titles
    mal_index = {}
    for url, raw in mal_data.items():
        titles = get_all_mal_titles(raw)
        if titles:
            mal_index[url] = titles

    log.info("Matching %d AniList entries against %d MAL entries...", len(catalogue), len(mal_index))

    enrichment: dict = {}
    matched = 0
    skipped = 0

    for i, media in enumerate(catalogue):
        al_titles = get_all_anilist_titles(media)
        if not al_titles:
            skipped += 1
            continue

        best_url   = None
        best_score = 0.0

        for url, mal_titles in mal_index.items():
            score = best_match_score(mal_titles, al_titles)
            if score > best_score:
                best_score = score
                best_url   = url
            if best_score == 1.0:
                break

        if best_url and best_score >= MATCH_THRESHOLD:
            # Nếu url này đã được match bởi entry khác, giữ cái có score cao hơn
            existing = enrichment.get(best_url, {})
            if not existing or best_score > existing.get("_match_score", 0):
                entry = parse_anilist_entry(media)
                entry["_match_score"] = round(best_score, 3)
                enrichment[best_url]  = entry
                matched += 1

        if (i + 1) % 1000 == 0:
            log.info("  Progress: %d/%d matched=%d", i + 1, len(catalogue), matched)

    log.info("Match complete: %d/%d MAL entries matched (%.1f%%)",
             matched, len(mal_index), matched / len(mal_index) * 100)
    return enrichment


# ════════════════════════════════════════════════════════════════════════════
#  Load MAL data (support list + dict format)
# ════════════════════════════════════════════════════════════════════════════

def load_mal_data() -> dict:
    """Load MAL data, normalize thành {url: {Title, Synonyms, ...}}"""
    if not MAL_INPUT_FILE.exists():
        log.error("File not found: %s", MAL_INPUT_FILE)
        return {}

    with MAL_INPUT_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        first = next(iter(raw.values()), {})
        if "page_content" in first:
            # Dict of prepared docs → extract từ metadata + page_content
            result = {}
            for url, doc in raw.items():
                meta    = doc.get("metadata", {})
                content = doc.get("page_content", "")
                synonyms = ""
                for line in content.splitlines():
                    if line.startswith("alt_titles:"):
                        synonyms = line.replace("alt_titles:", "").strip()
                        break
                result[url] = {"Title": meta.get("title", ""), "Synonyms": synonyms}
            return result
        else:
            return raw  # raw MAL dict

    elif isinstance(raw, list):
        # List of prepared docs
        result = {}
        for doc in raw:
            meta    = doc.get("metadata", {})
            content = doc.get("page_content", "")
            url     = meta.get("url", "")
            if not url:
                continue
            synonyms = ""
            for line in content.splitlines():
                if line.startswith("alt_titles:"):
                    synonyms = line.replace("alt_titles:", "").strip()
                    break
            result[url] = {"Title": meta.get("title", ""), "Synonyms": synonyms}
        return result

    return {}


# ════════════════════════════════════════════════════════════════════════════
#  Main
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=int, choices=[1, 2],
                        help="1=fetch only, 2=match only")
    args = parser.parse_args()

    run_step1 = args.step in (None, 1)
    run_step2 = args.step in (None, 2)

    # ── STEP 1: Fetch AniList catalogue ──────────────────────────────────────
    if run_step1:
        log.info("=" * 55)
        log.info("STEP 1 — Fetching AniList catalogue")
        log.info("=" * 55)
        catalogue = fetch_all_anilist()
        log.info("Total AniList entries fetched: %d", len(catalogue))
    else:
        if not ANILIST_RAW_FILE.exists():
            log.error("anilist_raw.json not found. Run step 1 first.")
            return
        with ANILIST_RAW_FILE.open(encoding="utf-8") as f:
            catalogue = json.load(f)
        log.info("Loaded cached AniList: %d entries", len(catalogue))

    # ── STEP 2: Match to MAL data ─────────────────────────────────────────────
    if run_step2:
        log.info("=" * 55)
        log.info("STEP 2 — Matching AniList → MAL data")
        log.info("=" * 55)

        mal_data = load_mal_data()
        if not mal_data:
            log.error("Could not load MAL data from %s", MAL_INPUT_FILE)
            return
        log.info("MAL entries loaded: %d", len(mal_data))

        enrichment = match_anilist_to_mal(catalogue, mal_data)

        with ENRICHMENT_FILE.open("w", encoding="utf-8") as f:
            json.dump(enrichment, f, ensure_ascii=False, indent=2)

        log.info("✅ Saved %d enrichments → %s", len(enrichment), ENRICHMENT_FILE)
        log.info("Next: python merge_anilist.py")

        # Print sample
        sample = next(iter(enrichment.values()), {})
        log.info("\nSample enrichment:")
        log.info("  anilist_id   : %s", sample.get("anilist_id"))
        log.info("  anilist_title: %s", sample.get("anilist_title"))
        log.info("  tags         : %s", sample.get("tags", [])[:5])
        log.info("  match_score  : %s", sample.get("_match_score"))


if __name__ == "__main__":
    main()