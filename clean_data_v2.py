"""
prepare_docs.py  —  Clean + build embed-ready docs từ raw MAL data
===================================================================
Input : raw_anime.json  (dict keyed by URL, có Reviews + Recommendations)
Output: prepared_anime.json  (list of {page_content, metadata})

Fixes:
  - Score "N/A1 (scored by...)" → None
  - Genre "FantasyFantasy" → "Fantasy"
  - Synopsis placeholder → ""
  - Licensors "None found, add some" → ""
  - Filter doc quá nghèo data (không synopsis + không reviews + không recs)

Chạy: python prepare_docs.py
"""

import json
import re
from pathlib import Path

INPUT_FILE  = Path("anime_data_v2.json")
OUTPUT_FILE = Path("cleaned_anime_data_v2.json")
LOW_QUALITY_FILE = Path("low_quality_anime.json")  # lưu riêng để review sau

MAX_REVIEW_CHARS = 400
MAX_REVIEWS      = 5
MAX_RECS         = 10

# ── Placeholder detection ─────────────────────────────────────────────────────

PLACEHOLDER_SYNOPSIS = [
    "no synopsis information has been added",
    "help improve our database",
]

DIRTY_FIELD_VALUES = {
    "none found, add some",
    "unknown",
    "none",
    "n/a",
}


# ── Cleaners ──────────────────────────────────────────────────────────────────

def strip_source_tag(text: str) -> str:
    return re.sub(r"\s*\(Source:[^)]*\)", "", text).strip()


def clean_text(text: str) -> str:
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s{2,}", " ", text).strip()


def clean_synopsis(text: str) -> str:
    """Trả về '' nếu synopsis là placeholder của MAL."""
    if not text:
        return ""
    cleaned = clean_text(strip_source_tag(text))
    for ph in PLACEHOLDER_SYNOPSIS:
        if ph in cleaned.lower():
            return ""
    return cleaned


def clean_field(value: str) -> str:
    """Trả về '' nếu field là dirty placeholder."""
    if not value:
        return ""
    if value.strip().lower() in DIRTY_FIELD_VALUES:
        return ""
    return value.strip()


def parse_score(value: str) -> float | None:
    """
    Parse score an toàn:
      "6.49"                          → 6.49
      "N/A1 (scored by - users)..."   → None
      "N/A"                           → None
    """
    if not value:
        return None
    match = re.search(r"\b([1-9](\.\d+)?|10(\.0+)?)\b", str(value))
    if match:
        score = float(match.group())
        if 1.0 <= score <= 10.0:
            return score
    return None


def parse_int(value: str) -> int | None:
    """'#7,830' → 7830  |  '24,648' → 24648"""
    if not value:
        return None
    cleaned = re.sub(r"[#,\s]", "", str(value))
    try:
        return int(cleaned)
    except ValueError:
        return None


def dedup_genres(genre_str: str) -> str:
    """
    Fix genre bị duplicate: "FantasyFantasy" → "Fantasy"
    "Action, AdventureAdventure" → "Action, Adventure"
    """
    if not genre_str:
        return ""
    parts = [g.strip() for g in genre_str.split(",")]
    cleaned = []
    for part in parts:
        # Detect và fix kiểu "WordWord" → "Word"
        deduped = re.sub(r"^(.+?)\1+$", r"\1", part)
        deduped = deduped.strip()
        if deduped and deduped not in cleaned:
            cleaned.append(deduped)
    return ", ".join(cleaned)


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def is_low_quality(raw: dict, synopsis: str) -> bool:
    """
    True nếu doc quá nghèo để embed có ý nghĩa.
    Tiêu chí: không synopsis VÀ không reviews VÀ không recommendations.
    """
    return (
        not synopsis
        and not raw.get("Reviews")
        and not raw.get("Recommendations")
    )


# ── Build embed text ──────────────────────────────────────────────────────────

def build_embed_text(raw: dict, synopsis: str, genres: str) -> str:
    parts = []

    # 1. Titles
    title    = raw.get("Title", "")
    synonyms = raw.get("Synonyms", "")
    japanese = raw.get("Japanese", "")
    english  = raw.get("English", "")
    alt = [t for t in [synonyms, english, japanese] if t]

    parts.append(f"title: {title}")
    if alt:
        # Dùng | nhất quán — tên có thể chứa dấu , nên không dùng , làm separator
        parts.append(f"alt_titles: {' | '.join(alt)}")

    # 2. Genres (đã merge Theme từ bên ngoài, truyền vào qua tham số genres)
    if genres:
        parts.append(f"genres: {genres}")

    # 3. Type + Episodes + Demographic
    anime_type  = raw.get("Type", "")
    episodes    = raw.get("Episodes", "")
    demographic = raw.get("Demographic", "")
    line = f"type: {anime_type} | episodes: {episodes}"
    if demographic:
        line += f" | demographic: {demographic}"
    parts.append(line)

    # 4. Score + Premiered + Studio + Source
    score     = parse_score(raw.get("Score", ""))
    premiered = raw.get("Premiered", "")
    studio    = clean_field(raw.get("Studios", ""))
    source    = raw.get("Source", "")
    score_str = str(score) if score else "N/A"
    parts.append(
        f"score: {score_str} | premiered: {premiered}"
        + (f" | studio: {studio}" if studio else "")
        + (f" | source: {source}" if source else "")
    )

    # 5. Similar titles
    recs = raw.get("Recommendations", [])
    rec_titles = [r["Title"] for r in recs[:MAX_RECS] if r.get("Title")]
    if rec_titles:
        parts.append(f"similar_to: {', '.join(rec_titles)}")

    # 6. Synopsis
    if synopsis:
        parts.append(f"synopsis: {synopsis}")

    # 7. Reviews — strip non-ASCII (Arabic/Japanese trong review gây nhiễu embedding)
    for i, review in enumerate(raw.get("Reviews", [])[:MAX_REVIEWS], 1):
        cleaned = clean_text(review)
        # Strip non-ASCII: giữ lại Latin + phổ biến, bỏ Japanese/Arabic/etc trong review text
        cleaned = re.sub(r"[^-]+", " ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        if cleaned:
            parts.append(f"review_{i}: {truncate(cleaned, MAX_REVIEW_CHARS)}")

    return "\n".join(parts)


# ── Build metadata ────────────────────────────────────────────────────────────

def build_metadata(raw: dict, url: str, synopsis: str, genres: str) -> dict:
    # genres đã được merge với Theme từ bước build_embed_text → nhất quán với embed text
    rec_titles = [r["Title"] for r in raw.get("Recommendations", [])[:MAX_RECS]
                  if r.get("Title")]
    return {
        "url":          url,
        "title":        raw.get("Title", ""),
        "type":         raw.get("Type", ""),
        "episodes":     parse_int(raw.get("Episodes", "")) or 0,
        "status":       raw.get("Status", ""),
        "score":        parse_score(raw.get("Score", "")) or 0.0,
        "ranked":       parse_int(raw.get("Ranked", "")) or 0,
        "popularity":   parse_int(raw.get("Popularity", "")) or 0,
        "members":      parse_int(raw.get("Members", "")) or 0,
        "favorites":    parse_int(raw.get("Favorites", "")) or 0,
        "genres":       genres,
        "studios":      clean_field(raw.get("Studios", "")),
        "source":       raw.get("Source", ""),
        "premiered":    raw.get("Premiered", ""),
        "rating":       raw.get("Rating", ""),
        "duration":     raw.get("Duration", ""),
        "demographic":  raw.get("Demographic", ""),
        "similar_to":   ", ".join(rec_titles),
        "has_reviews":  len(raw.get("Reviews", [])) > 0,
        "review_count": len(raw.get("Reviews", [])),
        "has_synopsis": bool(synopsis),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Reading {INPUT_FILE}...")
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found.")
        return

    with INPUT_FILE.open(encoding="utf-8") as f:
        raw_data: dict = json.load(f)

    print(f"Total anime: {len(raw_data)}")

    docs         = []
    low_quality  = []
    stats = {
        "no_synopsis":  0,
        "no_reviews":   0,
        "no_recs":      0,
        "dirty_score":  0,
        "dirty_genre":  0,
        "low_quality":  0,
    }

    for url, raw in raw_data.items():
        if not raw.get("Title"):
            continue

        # Clean core fields
        synopsis = clean_synopsis(raw.get("Synopsis", ""))
        genres   = dedup_genres(raw.get("Genres") or raw.get("Genre") or "")
        score_raw = raw.get("Score", "")
        score    = parse_score(score_raw)

        # Track stats
        if not synopsis:
            stats["no_synopsis"] += 1
        if not raw.get("Reviews"):
            stats["no_reviews"] += 1
        if not raw.get("Recommendations"):
            stats["no_recs"] += 1
        if score is None and score_raw:
            stats["dirty_score"] += 1

        # Check genre dedup
        orig = raw.get("Genres") or raw.get("Genre") or ""
        if orig != genres:
            stats["dirty_genre"] += 1

        # Low quality check
        if is_low_quality(raw, synopsis):
            stats["low_quality"] += 1
            low_quality.append({"url": url, "title": raw.get("Title", "")})
            continue  # bỏ qua, không embed

        # Merge genres + Theme một lần, dùng cho cả embed text lẫn metadata
        theme = raw.get("Theme", "")
        if theme:
            theme_clean = dedup_genres(theme)
            extra = [t for t in theme_clean.split(", ")
                     if t and t.lower() not in genres.lower()]
            merged_genres = genres + " | " + ", ".join(extra) if extra else genres
        else:
            merged_genres = genres

        page_content = build_embed_text(raw, synopsis, merged_genres)
        metadata     = build_metadata(raw, url, synopsis, merged_genres)

        docs.append({
            "page_content": page_content,
            "metadata":     metadata,
        })

    # ── Print stats ───────────────────────────────────────────────────────────
    total_input = len(raw_data)
    print(f"\n{'='*50}")
    print(f"Input total        : {total_input:>6}")
    print(f"Low quality (skip) : {stats['low_quality']:>6}  ({stats['low_quality']/total_input*100:.1f}%)")
    print(f"Output docs        : {len(docs):>6}")
    print(f"  - No synopsis    : {stats['no_synopsis']:>6}  ({stats['no_synopsis']/total_input*100:.1f}%)")
    print(f"  - No reviews     : {stats['no_reviews']:>6}  ({stats['no_reviews']/total_input*100:.1f}%)")
    print(f"  - No recs        : {stats['no_recs']:>6}  ({stats['no_recs']/total_input*100:.1f}%)")
    print(f"  - Dirty score    : {stats['dirty_score']:>6}")
    print(f"  - Genre deduped  : {stats['dirty_genre']:>6}")
    print(f"{'='*50}")

    # Sample
    print("\n--- Sample embed text ---")
    print(docs[0]["page_content"])

    # Save
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Saved {len(docs)} docs → {OUTPUT_FILE}")

    with LOW_QUALITY_FILE.open("w", encoding="utf-8") as f:
        json.dump(low_quality, f, ensure_ascii=False, indent=2)
    print(f"⚠️  Saved {len(low_quality)} low-quality anime → {LOW_QUALITY_FILE}")

    # Token/cost estimate
    total_chars = sum(len(d["page_content"]) for d in docs)
    est_tokens  = total_chars // 4
    est_cost    = est_tokens / 1_000_000 * 0.02
    print(f"\nEmbed estimate:")
    print(f"  Tokens : ~{est_tokens:,}")
    print(f"  Cost   : ~${est_cost:.2f}  (text-embedding-3-small)")


if __name__ == "__main__":
    main()