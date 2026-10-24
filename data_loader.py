
"""Load species data and retrieve animal images with caching and rate-limit protection."""

import json
import os
import tempfile
import threading
import time

import pandas as pd
import requests

from urllib.parse import urlparse, parse_qs
from ranking import threat_rank, STATUS


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

COLUMNS = [
    "taxonid", "kingdom_name", "phylum_name", "class_name",
    "order_name", "family_name", "genus_name", "scientific_name",
    "taxonomic_authority", "infra_rank", "infra_name", "population",
    "category", "main_common_name", "Image_Link",
]

BASE = os.path.dirname(os.path.abspath(__file__))

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

IMAGE_CACHE_FILE = os.path.join(BASE, "image_cache.json")

# Failed lookups are retried after this interval.
NEGATIVE_CACHE_SECONDS = 15 * 60

# After a 429 response, pause additional requests in this process.
RATE_LIMIT_COOLDOWN_SECONDS = 60

# Timeout for Wikimedia API requests.
REQUEST_TIMEOUT = 8

USER_AGENT = (
    "WildlifeGuardian/1.1 "
    "(educational species conservation project)"
)

_image_cache = {}
_cache_lock = threading.RLock()
_request_lock = threading.Lock()
_commons_cooldown_until = 0.0

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


# ---------------------------------------------------------
# Dataset loading helpers
# ---------------------------------------------------------

def _read(path):
    """Read CSV, TXT, or Excel; Image_Link is optional."""

    if path.lower().endswith((".csv", ".txt")):
        return pd.read_csv(
            path,
            usecols=lambda col: col in COLUMNS,
            dtype=str,
        )

    return pd.read_excel(
        path,
        usecols=lambda col: col in COLUMNS,
        dtype=str,
    )


# ---------------------------------------------------------
# Image cache helpers
# ---------------------------------------------------------

def _read_image_cache():
    """Read the existing image cache, including older cache formats."""

    try:
        with open(IMAGE_CACHE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except (OSError, json.JSONDecodeError):
        return {}


def _save_image_cache():
    """Save the cache atomically to reduce the risk of corrupting JSON."""

    directory = os.path.dirname(IMAGE_CACHE_FILE) or BASE
    temp_path = None

    try:
        os.makedirs(directory, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            delete=False,
            suffix=".tmp",
        ) as file:
            temp_path = file.name
            json.dump(
                _image_cache,
                file,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        os.replace(temp_path, IMAGE_CACHE_FILE)

    except OSError as error:
        print(f"Could not save image cache: {error}", flush=True)

        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _cached_url(cache_key):
    """Return a valid cached URL, or None when a lookup can be retried."""

    entry = _image_cache.get(cache_key)

    # Backwards compatibility with the previous cache format:
    # {"lion|panthera leo": "https://..."}
    if isinstance(entry, str):
        if entry:
            return entry

        # Old empty entries may have resulted from a temporary 429.
        # Allow them to be looked up again.
        return None

    if not isinstance(entry, dict):
        return None

    url = entry.get("url", "")
    expires_at = entry.get("expires_at", 0)

    if url:
        return url

    # An empty result is a negative cache entry.
    if expires_at and time.time() < expires_at:
        return ""

    return None


def _cache_result(cache_key, url, negative_ttl=NEGATIVE_CACHE_SECONDS):
    """Cache a successful URL or temporarily cache a failed lookup."""

    if url:
        _image_cache[cache_key] = {
            "url": url,
            "expires_at": None,
        }
    else:
        _image_cache[cache_key] = {
            "url": "",
            "expires_at": time.time() + negative_ttl,
        }

    _save_image_cache()


# Load cache once when this module starts.
_image_cache.update(_read_image_cache())


# ---------------------------------------------------------
# Wikimedia image lookup
# ---------------------------------------------------------

def _search_query(common_name, scientific_name, image_link):
    """Use an existing Wikimedia search query when available."""

    if image_link:
        try:
            parsed = urlparse(image_link)

            if parsed.netloc.endswith("wikimedia.org"):
                query = parse_qs(parsed.query).get("search", [""])[0]

                if query:
                    return query

        except (ValueError, TypeError):
            pass

    return f"{common_name} {scientific_name}".strip()


def _fetch_commons_image(query):
    """Fetch one thumbnail from Wikimedia Commons."""

    global _commons_cooldown_until

    with _request_lock:
        # A previous 429 means we should pause before sending more requests.
        remaining = _commons_cooldown_until - time.time()

        if remaining > 0:
            print(
                f"Wikimedia cooldown active; skipping image lookup "
                f"for {remaining:.0f}s.",
                flush=True,
            )
            return ""

        try:
            response = _session.get(
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
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")

                try:
                    cooldown = max(
                        RATE_LIMIT_COOLDOWN_SECONDS,
                        int(retry_after),
                    )
                except (ValueError, TypeError):
                    cooldown = RATE_LIMIT_COOLDOWN_SECONDS

                _commons_cooldown_until = (
                    time.time() + min(cooldown, 3600)
                )

                print(
                    f"Wikimedia rate limit reached (429). "
                    f"Pausing image requests for "
                    f"{min(cooldown, 3600)}s.",
                    flush=True,
                )
                return ""

            response.raise_for_status()
            data = response.json()

            pages = data.get("query", {}).get("pages", {})

            for page in sorted(
                pages.values(),
                key=lambda item: item.get("index", 999999),
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
                        return image_url

        except (requests.RequestException, ValueError, KeyError) as error:
            print(
                f"Wikimedia image lookup failed: {error}",
                flush=True,
            )

        return ""


def get_first_image_url(common_name, scientific_name="", image_link=""):
    """
    Return one direct image URL.

    Successful URLs are cached permanently until the cache is changed.
    Empty results expire, allowing temporary failures to be retried later.
    """

    common_name = str(common_name or "").strip()
    scientific_name = str(scientific_name or "").strip()
    image_link = str(image_link or "").strip()

    if not common_name:
        return ""

    # Already a direct Wikimedia image URL: no API request is needed.
    if image_link.startswith(
        ("https://upload.wikimedia.org/", "http://upload.wikimedia.org/")
    ):
        return image_link

    cache_key = f"{common_name.lower()}|{scientific_name.lower()}"

    # The lock prevents duplicate lookups within this Python process.
    with _cache_lock:
        cached = _cached_url(cache_key)

        if cached is not None:
            return cached

        query = _search_query(
            common_name,
            scientific_name,
            image_link,
        )

        image_url = _fetch_commons_image(query)

        # If the request was rate-limited, do not cache the empty result
        # for the full negative-cache interval. Use the cooldown duration.
        if not image_url:
            remaining = _commons_cooldown_until - time.time()

            if remaining > 0:
                ttl = max(60, int(remaining) + 10)
            else:
                ttl = NEGATIVE_CACHE_SECONDS

            _cache_result(cache_key, "", negative_ttl=ttl)

            print(
                f"No image currently available for {common_name}.",
                flush=True,
            )
            return ""

        _cache_result(cache_key, image_url)

        print(f"Cached image for {common_name}.", flush=True)

        return image_url


# ---------------------------------------------------------
# Species dataset loader
# ---------------------------------------------------------

def load_records(path):
    """Read species data into dictionaries used by the search trees."""

    if not os.path.isfile(path):
        raise FileNotFoundError(f"Species dataset not found: {path}")

    cache = path + ".cache.pkl"

    if (
        os.path.exists(cache)
        and os.path.getmtime(cache) >= os.path.getmtime(path)
    ):
        print(f"Loading cached data: {cache}", flush=True)
        df = pd.read_pickle(cache)

    else:
        print(
            f"Reading {path} (first run may take some time)...",
            flush=True,
        )

        df = _read(path)

        # Image_Link is optional in the original dataset.
        if "Image_Link" not in df.columns:
            df["Image_Link"] = ""

        df.to_pickle(cache)

    # Older pickle files may not contain the image column.
    if "Image_Link" not in df.columns:
        df["Image_Link"] = ""

    df = df.fillna("")
    records = []

    for row in df.to_dict("records"):
        try:
            taxonid = int(float(row.get("taxonid", 0)))
        except (ValueError, TypeError):
            taxonid = 0

        category = str(row.get("category", "")).strip()
        rank = threat_rank(category)

        scientific_name = str(
            row.get("scientific_name", "")
        ).strip()

        common_name = str(
            row.get("main_common_name", "")
        ).strip()

        image_link = str(
            row.get("Image_Link", "")
        ).strip()

        infra_rank = str(row.get("infra_rank", "")).strip()

        records.append({
            "taxonid": taxonid,
            "kingdom": str(row.get("kingdom_name", "")).strip(),
            "phylum": str(row.get("phylum_name", "")).strip(),
            "class": str(row.get("class_name", "")).strip(),
            "order": str(row.get("order_name", "")).strip(),
            "family": str(row.get("family_name", "")).strip(),
            "genus": str(row.get("genus_name", "")).strip(),
            "scientific_name": scientific_name,
            "authority": str(
                row.get("taxonomic_authority", "")
            ).strip(),
            "infra_rank": infra_rank,
            "infra_name": str(row.get("infra_name", "")).strip(),
            "population": str(row.get("population", "")).strip(),
            "category": category,
            "common_name": common_name,
            "image_link": image_link,
            "image_url": "",
            "threat_rank": rank,
            "status_code": STATUS[rank][0],
            "status": STATUS[rank][1],
            "is_species": not bool(infra_rank),
        })

    print(f"{len(records):,} records loaded.", flush=True)
    print(
        "Image URLs are resolved on demand and cached.",
        flush=True,
    )

    counts = df["category"].value_counts()

    print("Category values found:", flush=True)

    for category, count in counts.items():
        print(
            f"   {count:>8,}  {category!r:40} "
            f"-> rank {threat_rank(category)}",
            flush=True,
        )

    return records
