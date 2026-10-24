
"""Wildlife Guardian — Endangered Species Finder.

Builds BST and AVL trees when the module is imported, so the app
works both locally and when deployed with Gunicorn on Render.
"""

import math
import os
import sys
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

from avl import AVLTree
from bst import BST
from data_loader import load_records
from ranking import more_endangered, rank_key


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))

DATA_FILE = os.environ.get(
    "SPECIES_FILE",
    os.path.join(BASE, "data", "species.csv"),
)

app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static",
)

# Tree counters are shared between requests.
# This lock allows only one search to update them at a time.
lock = threading.Lock()

TREES = {}
BUILD = {}


# ---------------------------------------------------------
# Build BST and AVL trees
# ---------------------------------------------------------

def build_trees(records):
    """Build the common-name and conservation-ranking trees."""

    # Clear previous trees and statistics if this function is called again.
    TREES.clear()
    BUILD.clear()

    for kind, cls in (("bst", BST), ("avl", AVLTree)):
        names = cls()
        ranks = cls()

        # Build common-name search tree.
        start_names = time.perf_counter()

        for record in records:
            common_name = str(record.get("common_name") or "").strip()

            if common_name:
                names.insert(common_name.lower(), record)

        end_names = time.perf_counter()

        # Build ranking tree using sufficiently threatened species.
        start_ranks = time.perf_counter()

        for record in records:
            if (
                record.get("is_species")
                and record.get("class")
                and 2 <= record.get("threat_rank", 0) <= 6
            ):
                ranks.insert(rank_key(record), record)

        end_ranks = time.perf_counter()

        TREES[kind] = {
            "names": names,
            "ranks": ranks,
        }

        BUILD[kind] = {
            "label": cls.name,
            "name_nodes": names.size,
            "name_height": names.height(),
            "name_min_height": (
                math.ceil(math.log2(names.size + 1))
                if names.size
                else 0
            ),
            "name_build_s": round(end_names - start_names, 2),
            "name_build_comparisons": names.comparisons,
            "rank_nodes": ranks.size,
            "rank_height": ranks.height(),
            "rank_build_s": round(end_ranks - start_ranks, 2),
            "rotations": (
                getattr(names, "rotations", 0)
                + getattr(ranks, "rotations", 0)
            ),
        }

        print(
            f"{cls.name}: "
            f"name nodes={names.size:,}, "
            f"name height={names.height()}, "
            f"ranking nodes={ranks.size:,}, "
            f"ranking height={ranks.height()}, "
            f"name build={end_names - start_names:.2f}s, "
            f"ranking build={end_ranks - start_ranks:.2f}s",
            flush=True,
        )


# ---------------------------------------------------------
# Autocomplete suggestions
# ---------------------------------------------------------

def prefix_suggest(names, prefix, limit=8):
    """Return common names beginning with the supplied prefix."""

    prefix = (prefix or "").strip().lower()

    if not prefix:
        return []

    suggestions = []

    for node in names.iter_from(prefix):
        if not node.key.startswith(prefix):
            break

        if node.values:
            common_name = node.values[0].get("common_name", "")

            if common_name:
                suggestions.append(common_name)

        if len(suggestions) >= limit:
            break

    return suggestions


# ---------------------------------------------------------
# Prepare public species information
# ---------------------------------------------------------

def public(record):
    """Return the species fields needed by the frontend."""

    keys = (
        "taxonid",
        "scientific_name",
        "common_name",
        "kingdom",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
        "authority",
        "infra_rank",
        "infra_name",
        "population",
        "category",
        "status_code",
        "status",
        "threat_rank",
    )

    result = {key: record.get(key, "") for key in keys}

    result["image_link"] = record.get("image_link", "")

    result["image_url"] = ""

    if record.get("common_name"):
        try:
            from data_loader import get_first_image_url

            result["image_url"] = get_first_image_url(
                common_name=record.get("common_name", ""),
                scientific_name=record.get("scientific_name", ""),
                image_link=record.get("image_link", ""),
            ) or ""
        except Exception as exc:
            # An image lookup failure should not break species search.
            print(
                f"Image lookup failed for "
                f"{record.get('common_name', 'unknown species')}: {exc}",
                flush=True,
            )

    return result


# ---------------------------------------------------------
# Search using the selected data structure
# ---------------------------------------------------------

def run_search(kind, query):
    """Search a common name and rank more threatened relatives."""

    names = TREES[kind]["names"]
    ranks = TREES[kind]["ranks"]

    key = query.strip().lower()
    start = time.perf_counter()

    # Count comparisons used by the name search.
    comparison_start = names.comparisons
    found = names.search(key)
    name_comparisons = names.comparisons - comparison_start

    matches = []
    rank_comparisons = 0

    for record in (found or [])[:25]:
        rank_start = ranks.comparisons

        top, note = more_endangered(ranks, record, 5)

        rank_comparisons += ranks.comparisons - rank_start

        item = public(record)
        item["more_endangered"] = [public(species) for species in top]
        item["note"] = note

        matches.append(item)

    suggestions = [] if found else prefix_suggest(names, key, 8)

    elapsed_us = (time.perf_counter() - start) * 1e6

    return {
        "found": bool(found),
        "total_matches": len(found or []),
        "matches": matches,
        "suggestions": suggestions,
        "metrics": {
            "name_comparisons": name_comparisons,
            "rank_comparisons": rank_comparisons,
            "time_us": round(elapsed_us, 1),
            "name_tree_height": names.height(),
            "rank_tree_height": ranks.height(),
            "tree_nodes": names.size,
        },
    }


# ---------------------------------------------------------
# Website route
# ---------------------------------------------------------

@app.get("/")
def index():
    """Serve the main website."""

    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------
# Search API
# ---------------------------------------------------------

@app.get("/api/search")
def api_search():
    """Search using BST, AVL, or compare both structures."""

    query = request.args.get("name", "").strip()
    mode = request.args.get("tree", "avl").strip().lower()

    if not query:
        return jsonify(error="Type a common name to search."), 400

    if mode not in ("bst", "avl", "both"):
        return jsonify(
            error="The tree option must be bst, avl or both."
        ), 400

    # Check initialization explicitly rather than returning misleading
    # errors when the application has not built its trees.
    if not all(kind in TREES for kind in ("bst", "avl")):
        app.logger.error(
            "Search requested before both trees were initialized."
        )
        return jsonify(
            error="The species search trees are not ready. Please try again."
        ), 503

    kinds = ["bst", "avl"] if mode == "both" else [mode]

    with lock:
        results = {
            kind: run_search(kind, query)
            for kind in kinds
        }

    # Compare mode returns both results under separate keys.
    return jsonify(results)


# ---------------------------------------------------------
# Autocomplete API
# ---------------------------------------------------------

@app.get("/api/suggest")
def api_suggest():
    """Return autocomplete suggestions from the AVL name tree."""

    query = request.args.get("q", "").strip().lower()

    if not query:
        return jsonify([])

    if "avl" not in TREES:
        app.logger.error(
            "Autocomplete requested before the AVL tree was initialized."
        )
        return jsonify(error="The species search tree is not ready."), 503

    with lock:
        suggestions = prefix_suggest(
            TREES["avl"]["names"],
            query,
            8,
        )

    return jsonify(suggestions)


# ---------------------------------------------------------
# Tree statistics API
# ---------------------------------------------------------

@app.get("/api/stats")
def api_stats():
    """Return the BST and AVL build statistics."""

    if not BUILD:
        return jsonify(error="Tree statistics are not ready."), 503

    return jsonify(BUILD)


# ---------------------------------------------------------
# Initialize the dataset and trees
# ---------------------------------------------------------

def initialize_app():
    """Load the dataset and build both trees exactly once."""

    if TREES and BUILD:
        return

    if not os.path.isfile(DATA_FILE):
        raise FileNotFoundError(
            f"Species dataset not found: {DATA_FILE}. "
            "Ensure data/species.csv is included in the repository "
            "or set the SPECIES_FILE environment variable."
        )

    print(f"Loading species dataset: {DATA_FILE}", flush=True)

    records = load_records(DATA_FILE)

    if not records:
        raise RuntimeError(
            "The species dataset loaded no records. "
            "Check data_loader.py and the CSV format."
        )

    print(f"Loaded {len(records):,} species records.", flush=True)

    build_trees(records)

    if not all(kind in TREES for kind in ("bst", "avl")):
        raise RuntimeError("Failed to initialize both search trees.")

    print("BST and AVL trees initialized successfully.", flush=True)


# IMPORTANT:
# Gunicorn imports app.py, so initialize the trees at module level.
# Do not put this call only inside the __main__ block.
initialize_app()


# ---------------------------------------------------------
# Run locally
# ---------------------------------------------------------

if __name__ == "__main__":
    print("Open http://127.0.0.1:5000", flush=True)

    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
    )
