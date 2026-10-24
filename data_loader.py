
"""Load species data and retrieve one image per animal when needed."""

import os
import json
import pandas as pd
import requests

from urllib.parse import urlparse, parse_qs, unquote_plus
from ranking import threat_rank, STATUS

COLUMNS = [
    "taxonid", "kingdom_name", "phylum_name", "class_name",
    "order_name", "family_name", "genus_name", "scientific_name",
    "taxonomic_authority", "infra_rank", "infra_name", "population",
    "category", "main_common_name", "Image_Link",
]

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Keep the image cache beside this Python file.
IMAGE_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "image_cache.json"
)


def _read(path):
    """Read CSV, TXT, or Excel; Image_Link is optional."""
    if path.lower().endswith((".csv", ".txt")):
        return pd.read_csv(
            path,
            usecols=lambda col: col in COLUMNS,
            dtype=str
        )

    return pd.read_excel(
        path,
        usecols=lambda col: col in COLUMNS,
        dtype=str
    )


def _load_image_cache():
    """Load previously resolved image URLs."""
    try:
        with open(IMAGE_CACHE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_image_cache(cache):
    """Save resolved URLs so the same animal isn't searched repeatedly."""
    try:
        with open(IMAGE_CACHE_FILE, "w", encoding="utf-8") as file:
            json.dump(cache, file, ensure_ascii=False, indent=2)
    except OSError:
        pass


_image_cache = _load_image_cache()


def get_first_image_url(common_name, scientific_name="", image_link=""):
    """
    Return one direct thumbnail URL for an animal.

    If Image_Link is already a direct image URL, use it.
    Otherwise, search Wikimedia Commons and return the first image.
    Results are cached to avoid repeated API requests.
    """
    common_name = str(common_name or "").strip()
    scientific_name = str(scientific_name or "").strip()
    image_link = str(image_link or "").strip()

    # No common name means we cannot reliably search for the animal.
    if not common_name:
        return ""

    # If the column already contains a direct image URL, use it.
    if image_link.startswith(
        ("https://upload.wikimedia.org/", "http://upload.wikimedia.org/")
    ):
        return image_link

    cache_key = f"{common_name.lower()}|{scientific_name.lower()}"

    if cache_key in _image_cache:
        return _image_cache[cache_key]

    # If Image_Link is a Wikimedia search link, reuse its search query.
    query = ""
    if image_link:
        try:
            parsed_url = urlparse(image_link)
            if parsed_url.netloc.endswith("wikimedia.org"):
                query = parse_qs(parsed_url.query).get("search", [""])[0]
                query = unquote_plus(query)
        except (ValueError, TypeError):
            query = ""

    # Fall back to common and scientific names.
    if not query:
        query = f"{common_name} {scientific_name}".strip()

    image_url = ""

    try:
        response = requests.get(
            COMMONS_API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": 5,
                "prop": "imageinfo",
                "iiprop": "url",
                "iiurlwidth": 500,
            },
            headers={
                "User-Agent": "WildlifeGuardian/1.0 (species conservation project)"
            },
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()

        pages = data.get("query", {}).get("pages", {})

        # Pick the first result that has an image URL.
        for page in sorted(
            pages.values(),
            key=lambda item: item.get("index", 999999)
        ):
            image_info = page.get("imageinfo", [])

            if image_info:
                info = image_info[0]
                image_url = (
                    info.get("thumburl")
                    or info.get("url")
                    or ""
                )
                if image_url:
                    break

    except (requests.RequestException, ValueError, KeyError) as error:
        print(f"Image lookup failed for {common_name}: {error}")

    # Cache successful URLs and empty results alike.
    # Empty results are retried only after the cache is cleared.
    _image_cache[cache_key] = image_url
    _save_image_cache(_image_cache)

    return image_url


def load_records(path):
    """Read the species file into plain dictionaries."""
    cache = path + ".cache.pkl"

    if (
        os.path.exists(cache)
        and os.path.getmtime(cache) >= os.path.getmtime(path)
    ):
        print(f"Loading cached data: {cache}")
        df = pd.read_pickle(cache)
    else:
        print(f"Reading {path} (first run may take some time)...")
        df = _read(path)
        df.to_pickle(cache)

    # Older files may not contain the new image column.
    if "Image_Link" not in df.columns:
        df["Image_Link"] = ""

    df = df.fillna("")
    records = []

    for row in df.to_dict("records"):
        try:
            taxonid = int(float(row.get("taxonid", 0)))
        except (ValueError, TypeError):
            taxonid = 0

        rank = threat_rank(row.get("category", ""))
        sci = str(row.get("scientific_name", "")).strip()
        common = str(row.get("main_common_name", "")).strip()
        image_link = str(row.get("Image_Link", "")).strip()

        records.append({
            "taxonid": taxonid,
            "kingdom": str(row.get("kingdom_name", "")).strip(),
            "phylum": str(row.get("phylum_name", "")).strip(),
            "class": str(row.get("class_name", "")).strip(),
            "order": str(row.get("order_name", "")).strip(),
            "family": str(row.get("family_name", "")).strip(),
            "genus": str(row.get("genus_name", "")).strip(),
            "scientific_name": sci,
            "authority": str(
                row.get("taxonomic_authority", "")
            ).strip(),
            "infra_rank": str(row.get("infra_rank", "")).strip(),
            "infra_name": str(row.get("infra_name", "")).strip(),
            "population": str(row.get("population", "")).strip(),
            "category": str(row.get("category", "")).strip(),
            "common_name": common,
            "image_link": image_link,
            # Resolved on demand when the species is displayed.
            "image_url": "",
            "threat_rank": rank,
            "status_code": STATUS[rank][0],
            "status": STATUS[rank][1],
            "is_species": not str(
                row.get("infra_rank", "")
            ).strip(),
        })

    print(f"{len(records):,} records loaded.")
    print("Image links are resolved when a species is displayed.")

    counts = df["category"].value_counts()
    print("Category values found:")
    for cat, n in counts.items():
        print(f"   {n:>8,}  {cat!r:40} -> rank {threat_rank(cat)}")

    return records
