# 📊 Data Analysis & Merge Plan

## Source Files

| Property | `anime_data_v2.json` (MAL) | `anilist_data_raw.json` (AniList) |
|---|---|---|
| **Size** | 197 MB | 72 MB |
| **Count** | 30,001 entries | 19,991 entries |
| **Structure** | `dict` keyed by MAL URL | `list` of objects |
| **ID System** | MAL ID in URL (`/anime/{id}/`) | AniList `id` |

---

## Schema Comparison

### MAL Fields (`anime_data_v2.json`)
| Field | Example | Coverage |
|---|---|---|
| `Title` | "Cardfight!! Vanguard G Z" | ✅ all |
| `Synopsis` | Full text synopsis | ✅ most |
| `Japanese` / `English` / `Synonyms` | Alt titles | partial |
| `Type` | "TV", "Movie", "OVA" | ✅ all |
| `Episodes` | "24" (string) | ✅ most |
| `Status` | "Finished Airing" | ✅ all |
| `Aired` / `Premiered` | "Oct 8, 2017 to Apr 1, 2018" | ✅ most |
| `Score` | "6.61" (string, sometimes dirty) | ✅ most |
| `Ranked` / `Popularity` / `Members` / `Favorites` | "#7031" (string) | ✅ most |
| `Genre` or `Genres` | "ActionAction" (duplicated!) | ✅ most |
| `Theme` or `Themes` | "Strategy GameStrategy Game" | partial |
| `Demographic` / `Demographics` | "Shounen" | partial |
| `Studios` / `Producers` / `Licensors` | "OLM" | ✅ most |
| `Source` / `Duration` / `Rating` | Metadata | ✅ most |
| `Reviews` | List of review texts (long) | 12,363 entries |
| `Recommendations` | `[{Title, Text}]` | 8,939 entries |

### AniList Fields (`anilist_data_raw.json`)
| Field | Example | Coverage |
|---|---|---|
| `id` | 3929 (AniList ID) | ✅ all |
| `title` | `{romaji, english, native, userPreferred}` | ✅ all |
| `tags` | `[{name, category, rank, isSpoiler}]` | 16,471 entries |
| `averageScore` / `meanScore` | 42 (int, 0-100) | ✅ most |
| `description` | HTML description | 18,820 entries |
| `genres` | `["Comedy", "Supernatural"]` (list) | 17,553 entries |
| `season` / `seasonYear` | "FALL" / 2017 | partial |
| `status` | "FINISHED" | ✅ all |
| `episodes` / `duration` | 1 / 11 (ints) | ✅ most |
| `reviews.nodes` | `[{id, summary, rating, score}]` | 3,649 entries |
| `recommendations.nodes` | `[{rating, mediaRecommendation: {id, title}}]` | 12,325 entries |

---

## Matching Strategy

> [!IMPORTANT]
> No `idMal` field in AniList data — must match by title.

| Method | Matches |
|---|---|
| MAL title → AniList romaji | 13,974 |
| MAL title → AniList english | 2,028 |
| **Combined (union)** | **14,153** |
| Unmatched MAL entries | ~15,848 |
| Unmatched AniList entries | ~5,838 |

---

## What Each Source Uniquely Contributes

### AniList Exclusive Value 🌟
- **Tags** (16K entries) — granular descriptors like "Psychological", "Dark", "Time Travel", "Male Protagonist" with ranked relevance → **critical for RAG semantic search**
- **AniList Recommendations** with ratings (12K) → stronger rec signal
- **HTML descriptions** — often different/complementary to MAL synopsis
- **Review summaries** (compact, scored) — lighter than MAL's full reviews

### MAL Exclusive Value 🌟
- **More anime** (30K vs 20K) — broader coverage
- **Full review texts** (12K) — richer user opinions
- **Recommendation explanations** — "Both have X" text useful for RAG
- **Ranked / Popularity / Members / Favorites** — popularity metrics
- **Producers / Licensors** — production details
- **Rating** (PG-13, R, etc.) — content rating

---

## Preprocessing & Merge Plan

### Step 1: Clean MAL Data
- Fix duplicated genres (`"ActionAction"` → `"Action"`)
- Parse dirty scores (`"N/A1 (scored by...)"` → `null`)
- Clean placeholders (`"None found, add some"` → `""`)
- Parse numeric strings (`"#7,830"` → `7830`)
- Clean synopsis placeholders
- Truncate reviews (max 400 chars × 5 reviews)

### Step 2: Clean AniList Data
- Strip HTML from descriptions (`<br>`, `<i>`, etc.)
- Extract top tags (sorted by rank, non-spoiler only)
- Flatten review summaries
- Flatten recommendation titles

### Step 3: Match & Merge
- Primary match: MAL title ↔ AniList romaji (case-insensitive)
- Secondary match: MAL title ↔ AniList english title
- Merge enrichment fields into MAL records
- Keep unmatched MAL entries (MAL-only, still valuable)
- Keep unmatched AniList entries (AniList-only, adds coverage)

### Step 4: Build RAG Documents
Each document has:
- **`page_content`** — dense text for embedding/retrieval
- **`metadata`** — structured fields for filtering

### Output Schema
```json
{
  "page_content": "title: Steins;Gate\nalt_titles: シュタインズ・ゲート | Steins;Gate\ngenres: Sci-Fi, Thriller\ntags: Time Travel, Psychological, Conspiracy, Male Protagonist\ntype: TV | episodes: 24 | demographic: Shounen\nscore: 9.08 | premiered: Spring 2011 | studio: White Fox | source: Visual novel\nsimilar_to: Re:Zero, Madoka Magica, ...\nanilist_recs: Puella Magi Madoka Magica, ...\nsynopsis: ...\nreview_1: ...",
  "metadata": {
    "mal_url": "...",
    "mal_id": 9253,
    "anilist_id": 9253,
    "title": "Steins;Gate",
    "type": "TV",
    "episodes": 24,
    "status": "Finished Airing",
    "score_mal": 9.08,
    "score_anilist": 91,
    "ranked": 4,
    "popularity": 3,
    "members": 2345678,
    "favorites": 98765,
    "genres": "Sci-Fi, Thriller",
    "tags": "Time Travel, Psychological, ...",
    "studios": "White Fox",
    "source": "Visual novel",
    "premiered": "Spring 2011",
    "rating": "PG-13",
    "duration": "24 min. per ep.",
    "demographic": "Shounen",
    "similar_to": "Re:Zero, ...",
    "anilist_recs": "Madoka Magica, ...",
    "has_synopsis": true,
    "has_reviews": true,
    "review_count": 5,
    "source_datasets": "mal+anilist"
  }
}
```

### Quality Filter
Skip entries that have **none** of: synopsis, description, reviews, or recommendations.

---

## Expected Output Stats
| Metric | Estimate |
|---|---|
| Combined unique anime | ~35,800 |
| Matched (both sources) | ~14,150 |
| MAL-only | ~15,850 |
| AniList-only | ~5,840 |
| After quality filter | ~30,000+ |
