"""Flask server. Builds a BST set and an AVL set at startup, serves the UI."""
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

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.environ.get("SPECIES_FILE", os.path.join(BASE, "data", "species.csv"))

app = Flask(__name__, static_folder="static", static_url_path="/static")
lock = threading.Lock()  # tree counters are shared, so one query at a time

TREES = {}
BUILD = {}


def build_trees(records):
    for kind, cls in (("bst", BST), ("avl", AVLTree)):
        names, ranks = cls(), cls()
        t0 = time.perf_counter()
        for r in records:
            if r["common_name"]:
                names.insert(r["common_name"].lower(), r)
        t1 = time.perf_counter()
        for r in records:
            # only whole species that are threatened enough to be suggested
            if r["is_species"] and r["class"] and 2 <= r["threat_rank"] <= 6:
                ranks.insert(rank_key(r), r)
        t2 = time.perf_counter()
        TREES[kind] = {"names": names, "ranks": ranks}
        BUILD[kind] = {
            "label": cls.name,
            "name_nodes": names.size,
            "name_height": names.height(),
            "name_min_height": math.ceil(math.log2(names.size + 1)) if names.size else 0,
            "name_build_s": round(t1 - t0, 2),
            "name_build_comparisons": names.comparisons,
            "rank_nodes": ranks.size,
            "rank_height": ranks.height(),
            "rank_build_s": round(t2 - t1, 2),
            "rotations": getattr(names, "rotations", 0) + getattr(ranks, "rotations", 0),
        }
        print(f"{cls.name}: names h={names.height()} ({t1 - t0:.1f}s), "
              f"ranks h={ranks.height()} ({t2 - t1:.1f}s)")



def public(rec):
    keys = (
        "taxonid", "scientific_name", "common_name",
        "kingdom", "phylum", "class", "order", "family",
        "genus", "authority", "infra_rank", "infra_name",
        "population", "category", "status_code", "status",
        "threat_rank"
    )

    result = {k: rec.get(k, "") for k in keys}

    # Include the original image search link.
    result["image_link"] = rec.get("image_link", "")

    # Resolve one actual image URL for animals with a common name.
    if rec.get("common_name"):
        from data_loader import get_first_image_url

        result["image_url"] = get_first_image_url(
            common_name=rec.get("common_name", ""),
            scientific_name=rec.get("scientific_name", ""),
            image_link=rec.get("image_link", "")
        )
    else:
        result["image_url"] = ""

    return result



def run_search(kind, query):
    names, ranks = TREES[kind]["names"], TREES[kind]["ranks"]
    key = query.strip().lower()
    start = time.perf_counter()

    c0 = names.comparisons
    found = names.search(key)
    name_cmp = names.comparisons - c0

    matches, rank_cmp = [], 0
    for rec in (found or [])[:25]:
        r0 = ranks.comparisons
        top, note = more_endangered(ranks, rec, 5)
        rank_cmp += ranks.comparisons - r0
        item = public(rec)
        item["more_endangered"] = [public(t) for t in top]
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
            "name_comparisons": name_cmp,
            "rank_comparisons": rank_cmp,
            "time_us": round(elapsed_us, 1),
            "name_tree_height": names.height(),
            "rank_tree_height": ranks.height(),
            "tree_nodes": names.size,
        },
    }


def prefix_suggest(names, prefix, limit):
    if not prefix:
        return []
    out = []
    for node in names.iter_from(prefix):
        if not node.key.startswith(prefix):
            break
        out.append(node.values[0]["common_name"])
        if len(out) == limit:
            break
    return out


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/search")
def api_search():
    q = request.args.get("name", "").strip()
    mode = request.args.get("tree", "avl")
    if not q:
        return jsonify(error="Type a common name to search."), 400
    kinds = ["bst", "avl"] if mode == "both" else [mode]
    if any(k not in TREES for k in kinds):
        return jsonify(error="tree must be bst, avl or both"), 400
    with lock:
        return jsonify({k: run_search(k, q) for k in kinds})


@app.get("/api/suggest")
def api_suggest():
    q = request.args.get("q", "").strip().lower()
    with lock:
        return jsonify(prefix_suggest(TREES["avl"]["names"], q, 8))


@app.get("/api/stats")
def api_stats():
    return jsonify(BUILD)


if __name__ == "__main__":
    if not os.path.exists(DATA_FILE):
        sys.exit(f"Data file not found: {DATA_FILE}\n"
                 "Put your Excel file at data/species.xlsx or set SPECIES_FILE.")
    build_trees(load_records(DATA_FILE))
    print("Open http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)