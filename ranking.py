"""IUCN status ranking and the 'more endangered in the same class' query."""

# Higher number = more threatened. Extinct (7) is stored but never suggested.
STATUS = {
    7: ("EX", "Extinct"),
    6: ("EW", "Extinct in the Wild"),
    5: ("CR", "Critically Endangered"),
    4: ("EN", "Endangered"),
    3: ("VU", "Vulnerable"),
    2: ("NT", "Near Threatened"),
    1: ("LC", "Least Concern"),
    0: ("DD", "Data Deficient"),
}
_CODES = {code: rank for rank, (code, _) in STATUS.items()}


def threat_rank(category):
    """Turn the dataset's `category` text into a number 0..7."""
    c = (category or "").strip().lower()
    if not c:
        return 0
    if c.upper() in _CODES:
        return _CODES[c.upper()]
    if "extinct in the wild" in c:
        return 6
    if "extinct" in c and "possibly" not in c:
        return 7
    if "critically" in c or "possibly extinct" in c:
        return 5
    if "endangered" in c and "near" not in c:
        return 4
    if "vulnerable" in c:
        return 3
    if "near threatened" in c or "lower risk/near" in c:
        return 2
    if "least concern" in c or "lower risk" in c:
        return 1
    return 0


def rank_key(rec):
    """Sort key of the *rank tree*.

    Sorted by class, then most-threatened first, then species that have a
    common name, then name. So the species we want to suggest sit next to each
    other in an in-order walk.
    """
    return (
        rec["class"].lower(),
        -rec["threat_rank"],
        0 if rec["common_name"] else 1,
        (rec["common_name"] or rec["scientific_name"]).lower(),
        rec["taxonid"],
    )




def more_endangered(rank_tree, rec, limit=5):
    """
    Find more threatened species using the selected tree only.

    Search order:
    1. Same class
    2. Same phylum
    3. Same kingdom

    The ranking tree is supplied by app.py, so BST searches use
    the BST ranking tree and AVL searches use the AVL ranking tree.
    """

    if rec["threat_rank"] < 1:
        return [], "This species has no threat ranking, so it can't be compared."

    if rec["threat_rank"] >= 6:
        return [], "No more threatened species are available under the current ranking rules."

    if not rec.get("class"):
        return [], "This record has no class, so there is no group to compare with."

    searched_name = rec["scientific_name"].strip().lower()

    def qualifies(candidate):
        return (
            candidate["scientific_name"].strip().lower() != searched_name
            and candidate["threat_rank"] > rec["threat_rank"]
            and candidate["threat_rank"] < 7
        )

    def get_top(matches):
        matches.sort(
            key=lambda candidate: (
                -candidate["threat_rank"],
                0 if candidate["common_name"] else 1,
                (
                    candidate["common_name"]
                    or candidate["scientific_name"]
                ).lower(),
                candidate["taxonid"],
            )
        )
        return matches[:limit]

    # 1. Search the same class using the selected ranking tree.
    cls = rec["class"].strip().lower()
    class_matches = []

    for node in rank_tree.iter_from((cls, -6, 0, "", 0)):
        if node.key[0] != cls:
            break

        for candidate in node.values:
            if qualifies(candidate):
                class_matches.append(candidate)

    if class_matches:
        return get_top(class_matches), ""

    # Broader searches traverse the SAME selected tree.
    # No direct scan of the original dataset is performed.

    for field, label in (
        ("phylum", "phylum"),
        ("kingdom", "kingdom"),
    ):
        group = (rec.get(field) or "").strip().lower()

        if not group:
            continue

        matches = []

        for node in rank_tree.iter_from(("", -6, 0, "", 0)):
            for candidate in node.values:
                if (
                    qualifies(candidate)
                    and (candidate.get(field) or "").strip().lower() == group
                ):
                    matches.append(candidate)

        if matches:
            note = (
                f"No more threatened species were found in the same class "
                f"({rec['class']}). Showing results from the same "
                f"{label}: {rec[field]}."
            )
            return get_top(matches), note

    return [], (
        "No more threatened species were found in the same class, "
        "phylum, or kingdom."
    )
