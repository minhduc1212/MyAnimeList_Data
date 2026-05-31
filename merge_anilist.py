"""
merge_anilist.py  —  Merge AniList tags + recs vào prepared_anime.json
=======================================================================
Input:
  prepared_anime.json      (output từ prepare_docs.py)
  anilist_enrichment.json  (output từ fetch_anilist.py)

Output:
  final_anime.json  (sẵn sàng để embed)

Chạy: python merge_anilist.py
"""

import json
from pathlib import Path

PREPARED_FILE   = Path("cleaned_anime_data_v2.json")
ENRICHMENT_FILE = Path("anilist_enrichment.json")
OUTPUT_FILE     = Path("final_anime.json")


def merge(doc: dict, anilist: dict) -> dict:
    """Merge AniList tags + recs vào 1 doc, cả page_content lẫn metadata."""
    if not anilist or not anilist.get("anilist_id"):
        return doc  # không có data AniList → giữ nguyên

    tags     = anilist.get("tags", [])          # ["Psychological", "Dark", ...]
    al_recs  = anilist.get("anilist_recs", [])  # [{"title": ..., "rating": ...}]
    al_title = anilist.get("anilist_title", "")

    # ── Cập nhật page_content ──────────────────────────────────────────────
    lines = doc["page_content"].splitlines()

    # Thêm tags line sau dòng genres
    tag_line = f"tags: {', '.join(tags)}" if tags else ""
    al_rec_titles = [r["title"] for r in al_recs if r.get("title")]
    al_rec_line   = f"anilist_recs: {', '.join(al_rec_titles)}" if al_rec_titles else ""

    new_lines = []
    for line in lines:
        new_lines.append(line)
        # Inject tags + anilist_recs ngay sau dòng genres
        if line.startswith("genres:"):
            if tag_line:
                new_lines.append(tag_line)
            if al_rec_line:
                new_lines.append(al_rec_line)

    doc["page_content"] = "\n".join(new_lines)

    # ── Cập nhật metadata ──────────────────────────────────────────────────
    doc["metadata"]["anilist_id"]   = anilist.get("anilist_id")
    doc["metadata"]["anilist_tags"] = ", ".join(tags[:15])  # top 15 cho filter
    doc["metadata"]["anilist_recs"] = ", ".join(al_rec_titles[:10])

    return doc


def main():
    print(f"Reading {PREPARED_FILE}...")
    if not PREPARED_FILE.exists():
        print(f"Error: {PREPARED_FILE} not found. Run prepare_docs.py first.")
        return
    with PREPARED_FILE.open(encoding="utf-8") as f:
        docs: list = json.load(f)
    print(f"  Docs: {len(docs)}")

    print(f"Reading {ENRICHMENT_FILE}...")
    if not ENRICHMENT_FILE.exists():
        print(f"Error: {ENRICHMENT_FILE} not found. Run fetch_anilist.py first.")
        return
    with ENRICHMENT_FILE.open(encoding="utf-8") as f:
        enrichment: dict = json.load(f)

    matched    = sum(1 for v in enrichment.values() if v.get("anilist_id"))
    not_found  = len(enrichment) - matched
    print(f"  AniList entries: {len(enrichment)}  (matched={matched}, not_found={not_found})")

    # Merge
    merged_count = 0
    for doc in docs:
        url     = doc["metadata"]["url"]
        anilist = enrichment.get(url, {})
        if anilist.get("anilist_id"):
            doc = merge(doc, anilist)
            # doc là dict, mutate in-place đã đủ nhưng reassign để rõ ràng
            docs[docs.index(doc)] = doc
            merged_count += 1

    print(f"\n✅ Merged AniList data into {merged_count}/{len(docs)} docs")

    # Sample
    sample = next((d for d in docs if d["metadata"].get("anilist_id")), docs[0])
    print("\n--- Sample page_content (first matched doc) ---")
    print(sample["page_content"][:800])

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Saved {len(docs)} docs → {OUTPUT_FILE}")
    print("Next step: run embed_anime_openai.py with INPUT_FILE = 'final_anime.json'")


if __name__ == "__main__":
    main()