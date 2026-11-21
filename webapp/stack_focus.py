"""
"Count the stack in front, not the whole yard" (2026-11-21).

A photo of a pallet or stack often shows OTHER stacks of the same goods behind or beside it (a
steel yard, a timber shed). The piece detector finds those too, so a 28-piece stack came back
as 47. This keeps only the main stack:

  * pieces of one stack touch their neighbours and are about the same size on screen; stacks
    further away look smaller and stand apart -> keep the largest group of touching,
    similar-sized pieces (scored by total area, so the big front stack wins)
  * a small box whose centre sits inside a bigger kept box is the same piece found twice -> dropped

Pure geometry on the detector's boxes: no model, no camera loop, no database. The operator can
still add a missed piece or remove one by tapping markers, and can count the whole photo instead.
"""
from typing import Any, Dict, List, Sequence, Tuple

GAP_FACTOR = 0.45      # neighbours: gap at most this x the shortest box side
SIZE_RATIO = 2.6       # neighbours: areas differ by at most this factor
MIN_PIECES = 4         # don't second-guess very small counts


def _box(p: Dict[str, Any]) -> Tuple[float, float, float, float]:
    b = p.get("bbox")
    if b and len(b) >= 4:
        return float(b[0]), float(b[1]), float(b[2]), float(b[3])
    x, y, w, h = (float(p.get(k, 0) or 0) for k in ("x", "y", "w", "h"))
    return x - w / 2, y - h / 2, x + w / 2, y + h / 2


def _area(b) -> float:
    return max(1.0, (b[2] - b[0]) * (b[3] - b[1]))


def _touch(a, b) -> bool:
    """Close enough to be neighbours in one stack, and about the same size."""
    ra, rb = _area(a), _area(b)
    if max(ra, rb) / min(ra, rb) > SIZE_RATIO:
        return False
    gap_x = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    gap_y = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    short = min(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1])
    return gap_x <= GAP_FACTOR * short and gap_y <= GAP_FACTOR * short


def _inside(pt, b) -> bool:
    return b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3]


def main_stack(pieces: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Returns (pieces of the main stack, {"kept", "background", "duplicates"})."""
    pieces = list(pieces or [])
    n = len(pieces)
    if n < MIN_PIECES:
        return pieces, {"kept": n, "background": 0, "duplicates": 0}
    boxes = [_box(p) for p in pieces]

    # groups of touching, similar-sized pieces (union-find)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _touch(boxes[i], boxes[j]):
                parent[find(i)] = find(j)
    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    best = max(groups.values(), key=lambda g: sum(_area(boxes[i]) for i in g))
    if len(best) < MIN_PIECES:            # no clear stack: leave the count alone
        return pieces, {"kept": n, "background": 0, "duplicates": 0}
    keep = set(best)

    # small boxes inside the stack whose centre lies in a bigger kept box: same piece twice
    dup = set()
    for i in range(n):
        if i in keep:
            continue
        c = ((boxes[i][0] + boxes[i][2]) / 2, (boxes[i][1] + boxes[i][3]) / 2)
        if any(_inside(c, boxes[k]) and _area(boxes[k]) > _area(boxes[i]) for k in keep):
            dup.add(i)
    for i in list(keep):
        c = ((boxes[i][0] + boxes[i][2]) / 2, (boxes[i][1] + boxes[i][3]) / 2)
        if any(k != i and _inside(c, boxes[k]) and _area(boxes[k]) > 1.6 * _area(boxes[i]) for k in keep):
            keep.discard(i)
            dup.add(i)

    kept = [pieces[i] for i in range(n) if i in keep]
    return kept, {"kept": len(kept), "background": n - len(kept) - len(dup), "duplicates": len(dup)}
