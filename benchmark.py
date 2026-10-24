"""Shows why AVL exists: insert the same names sorted vs shuffled.

    python benchmark.py            # 3000 names
    python benchmark.py 8000
"""
import os
import random
import sys
import time

from avl import AVLTree
from bst import BST
from data_loader import load_records

BASE = os.path.dirname(os.path.abspath(__file__))
path = os.environ.get("SPECIES_FILE", os.path.join(BASE, "data", "species.xlsx"))
n = int(sys.argv[1]) if len(sys.argv) > 1 else 3000

names = sorted({r["common_name"].lower() for r in load_records(path) if r["common_name"]})
names = names[:n]
shuffled = names[:]
random.Random(1).shuffle(shuffled)

print(f"\n{len(names)} distinct common names")
print(f"{'order':10}{'tree':6}{'height':>8}{'comparisons':>14}{'build s':>10}")
for label, data in (("sorted", names), ("shuffled", shuffled)):
    for cls in (BST, AVLTree):
        tree = cls()
        t = time.perf_counter()
        for x in data:
            tree.insert(x, x)
        dt = time.perf_counter() - t
        print(f"{label:10}{cls.name:6}{tree.height():>8}{tree.comparisons:>14,}{dt:>10.2f}")