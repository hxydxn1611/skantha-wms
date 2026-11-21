"""
Product photos from the internet, for registering products in AI Vision.

Sources (free to use, including commercially):
  * Pixabay   - needs PIXABAY_API_KEY in .env   (https://pixabay.com/api/docs/)
  * Pexels    - needs PEXELS_API_KEY in .env    (new keys paused by Pexels; used if a key is set)
  * Openverse - no key (https://api.openverse.org): openly licensed photos from Flickr,
                Wikimedia Commons, museums and more. Only licences that allow commercial
                use and changes (no "ND") are shown; each photo keeps its credit + licence.

search() returns small previews from all enabled sources, mixed together and never
repeating what the screen has already shown (`seen`). import_photo() downloads one chosen
photo - only from the sources' own image services (Openverse photos come through Openverse's
own image proxy, never straight from the original website) - checks it really is an image,
re-encodes it as a clean JPEG (no metadata, at most 1600 px) and returns the bytes.

Only the search words (the product name) are sent to these services.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 6
USER_AGENT = "WARLOG-WMS/1.0 (product photo picker; python-requests)"
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1600
PER_PAGE = 20

# photos may only be downloaded from these hosts (no other address can be fetched)
ALLOWED_IMAGE_HOSTS = ("pixabay.com", "cdn.pixabay.com", "images.pexels.com", "api.openverse.org")
OPENVERSE_LICENSES = {"cc0": "CC0", "pdm": "Public Domain", "by": "CC BY", "by-sa": "CC BY-SA",
                      "by-nc": None, "by-nd": None, "by-nc-sa": None, "by-nc-nd": None}   # None = not shown


class PhotoSearchError(Exception):
    pass


def _key(name: str) -> str:
    v = (os.environ.get(name) or "").strip()
    # an unfilled template value ("your-pexels-key", "<key>", "xxx") counts as no key
    if not v or v.lower().startswith(("your", "<", "xxx", "changeme", "replace")):
        return ""
    return v


def providers_status() -> Dict[str, bool]:
    return {"pixabay": bool(_key("PIXABAY_API_KEY")), "pexels": bool(_key("PEXELS_API_KEY")), "openverse": True}


def _get(url: str, **kw) -> requests.Response:
    headers = kw.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    return requests.get(url, headers=headers, timeout=TIMEOUT, **kw)


# ----------------------------------------------------------------------------- providers
def _pixabay(query: str, page: int) -> List[Dict]:
    key = _key("PIXABAY_API_KEY")
    if not key:
        return []
    r = _get("https://pixabay.com/api/", params={"key": key, "q": query[:100], "image_type": "photo",
                                                 "per_page": PER_PAGE, "page": page, "safesearch": "true"})
    if r.status_code != 200:
        logger.warning(f"[PhotoSearch] Pixabay answered {r.status_code}")
        return []
    out = []
    for h in r.json().get("hits", []):
        out.append({"id": f"pixabay:{h.get('id')}", "provider": "Pixabay",
                    "thumb": h.get("webformatURL") or h.get("previewURL"),
                    "url": h.get("largeImageURL") or h.get("webformatURL"),
                    "width": h.get("imageWidth"), "height": h.get("imageHeight"),
                    "author": h.get("user") or "", "page_url": h.get("pageURL") or "",
                    "license": "Pixabay Content License",
                    # Pixabay lists the most relevant tags first; later ones are loose associations
                    "words": ", ".join(str(h.get("tags") or "").split(",")[:10])})
    return out


def _pexels(query: str, page: int) -> List[Dict]:
    key = _key("PEXELS_API_KEY")
    if not key:
        return []
    r = _get("https://api.pexels.com/v1/search", params={"query": query[:100], "per_page": PER_PAGE, "page": page},
             headers={"Authorization": key})
    if r.status_code != 200:
        logger.warning(f"[PhotoSearch] Pexels answered {r.status_code}")
        return []
    out = []
    for p in r.json().get("photos", []):
        src = p.get("src") or {}
        out.append({"id": f"pexels:{p.get('id')}", "provider": "Pexels",
                    "thumb": src.get("medium") or src.get("small"),
                    "url": src.get("large2x") or src.get("large") or src.get("original"),
                    "width": p.get("width"), "height": p.get("height"),
                    "author": p.get("photographer") or "", "page_url": p.get("url") or "",
                    "license": "Pexels License", "words": str(p.get("alt") or "")})
    return out


def _openverse(query: str, page: int) -> List[Dict]:
    if page > 12:   # anonymous access reaches the first 240 results (12 pages of 20)
        return []
    r = _get("https://api.openverse.org/v1/images/", params={
        "q": query[:100], "page": page, "page_size": PER_PAGE, "license_type": "commercial", "mature": "false"})
    if r.status_code != 200:
        logger.warning(f"[PhotoSearch] Openverse answered {r.status_code}")
        return []
    out = []
    for it in r.json().get("results", []):
        lic = OPENVERSE_LICENSES.get(str(it.get("license") or "").lower())
        thumb = it.get("thumbnail") or ""
        if not lic or not thumb.startswith("https://api.openverse.org/"):
            continue   # licence without commercial use + changes, or no proxied copy
        version = it.get("license_version") or ""
        source = str(it.get("source") or it.get("provider") or "").replace("_", " ").title()
        out.append({"id": f"openverse:{it.get('id')}", "provider": f"Openverse ({source})" if source else "Openverse",
                    "thumb": thumb, "url": thumb.split("?")[0] + "?full_size=true",
                    "width": it.get("width"), "height": it.get("height"),
                    "author": str(it.get("creator") or "")[:80], "page_url": it.get("foreign_landing_url") or "",
                    "license": f"{lic} {version}".strip() if lic.startswith("CC ") else lic,
                    "title": str(it.get("title") or "")[:120],
                    "words": " ".join([str(it.get("title") or "")] + [str(t.get("name") or "") for t in (it.get("tags") or [])[:10]])})
    return out


_ANSWERS: Dict[Tuple[str, str, int], Tuple[float, List[Dict]]] = {}
_ANSWER_TTL = {"pixabay": 24 * 3600, "pexels": 3600, "openverse": 3600}   # Pixabay's terms: cache 24 h


def _cached(name: str, fn):
    """Remembers a source's answer per (words, page), so repeated searches don't call it again."""
    import copy
    import time as _time

    def call(query: str, page: int) -> List[Dict]:
        key = (name, query.lower(), page)
        hit = _ANSWERS.get(key)
        if hit and _time.time() - hit[0] < _ANSWER_TTL.get(name, 3600):
            return copy.deepcopy(hit[1])
        res = fn(query, page)
        if res:
            if len(_ANSWERS) > 500:
                _ANSWERS.clear()
            _ANSWERS[key] = (_time.time(), copy.deepcopy(res))
        return res
    return call


PROVIDERS = (("pixabay", _cached("pixabay", _pixabay)), ("pexels", _cached("pexels", _pexels)),
             ("openverse", _cached("openverse", _openverse)))


# ----------------------------------------------------------------------------- relevance + search words
import re as _re

_STOP = {"a", "an", "the", "of", "and", "or", "for", "with", "on", "in", "to", "by", "at", "from", "photo", "picture",
         "image", "type", "grade", "standard", "rated", "clear", "new", "pcs", "unit", "units", "set"}
_UNITS = r"(?:mm|cm|m|km|kg|g|mg|t|l|ml|in|inch|inches|ft|feet|mil|gsm|mic|micron|v|w|kw|a|hp|psi|bar)"
# words that name what a product physically is (used to build a sensible search phrase)
_MATERIALS = ("glass", "steel", "iron", "aluminium", "aluminum", "copper", "brass", "metal", "timber", "wood", "wooden",
              "plywood", "mdf", "plastic", "pvc", "rubber", "concrete", "cement", "stone", "granite", "marble", "ceramic",
              "paper", "cardboard", "fabric", "cotton", "foam", "rope", "cable", "wire")
_FORMS = ("sheet", "panel", "plate", "pipe", "tube", "rod", "bar", "beam", "channel", "angle", "profile", "plank", "board",
          "log", "block", "brick", "tile", "slab", "coil", "roll", "drum", "barrel", "bag", "sack", "carton", "box", "crate",
          "pallet", "bundle", "bottle", "can", "jar", "frame", "door", "window", "mirror")
_UOM_FORM = {"SHEET": "sheet", "SHEETS": "sheet", "PIPE": "pipe", "PIPES": "pipe", "PLANK": "plank", "PLANKS": "plank",
             "BOX": "box", "BOXES": "box", "CARTON": "carton", "BAG": "bag", "ROLL": "roll", "COIL": "coil", "ROD": "rod",
             "RODS": "rod", "BAR": "bar", "BEAM": "beam", "BEAMS": "beam", "DRUM": "drum", "BUNDLE": "bundle", "BUNDLES": "bundle"}


def _norm(word: str) -> str:
    w = word.lower().strip(".,;:!?\"'()[]")
    for suf, rp in (("ies", "y"), ("ches", "ch"), ("shes", "sh"), ("xes", "x"), ("oes", "o")):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)] + rp
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def _terms(text: str) -> List[str]:
    out = []
    for w in _re.split(r"[^A-Za-z]+", text or ""):
        n = _norm(w)
        if len(n) >= 3 and n not in _STOP and n not in out:
            out.append(n)
    return out


def clean_product_name(name: str) -> str:
    """'6mm Fire-Rated Borosilicate Glass (E-120 Rated)' -> 'fire borosilicate glass'."""
    t = str(name or "")
    t = _re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)                                              # bracketed specs
    t = _re.sub(r"\b\d+(?:[.,]\d+)?\s*[x×*]\s*\d+(?:[.,]\d+)?(?:\s*[x×*]\s*\d+(?:[.,]\d+)?)?\s*" + _UNITS + r"?\b",
                " ", t, flags=_re.I)                                                          # 2440x1830mm
    t = _re.sub(r"\b\d+(?:[.,]\d+)?\s*" + _UNITS + r"\b", " ", t, flags=_re.I)              # 6mm, 24 kg
    t = _re.sub(r"\b[A-Za-z]*\d[\w+\-/]*", " ", t)                                           # codes / numbers: E-120, 8+12A+8
    t = _re.sub(r"[-_/+&,]", " ", t)
    return " ".join(w for w in t.lower().split() if w not in ("rated", "grade", "type"))[:80].strip()


def suggest_queries(name: str, category: str = "", uom: str = "") -> List[str]:
    """Search phrases that stock-photo sites understand, best first."""
    base = clean_product_name(name)
    norm = [_norm(w) for w in (base + " " + clean_product_name(category)).split()]
    material = next((w for w in norm if w in _MATERIALS), "")
    form = _UOM_FORM.get(str(uom or "").upper().strip()) or next((w for w in norm if w in _FORMS), "")
    if material and not form:   # the usual shape of that material on a warehouse shelf
        form = {"glass": "panel", "steel": "bar", "iron": "bar", "metal": "profile", "aluminium": "profile",
                "aluminum": "profile", "timber": "plank", "wood": "plank", "wooden": "plank", "plywood": "sheet",
                "mdf": "board", "paper": "roll", "cardboard": "box", "cement": "bag", "concrete": "block",
                "stone": "slab", "granite": "slab", "marble": "slab", "ceramic": "tile", "cable": "roll",
                "wire": "coil", "fabric": "roll", "plastic": "sheet", "pvc": "pipe"}.get(material, "")
    plural = (form + "es") if form.endswith(("x", "ch", "sh")) else (form + "s") if form else ""
    out = []
    if material and plural:
        out.append(f"{material} {plural}")
    elif plural:
        out.append(plural)
    if base:
        out += [" ".join(base.split()[-2:]), base]
    if material:
        out.append(material)
    cat = clean_product_name(category)
    if cat:
        out.append(cat)
    res = []
    for q in out:
        q = " ".join(q.split())
        if len(q) >= 3 and q not in res:
            res.append(q)
    return res[:6]


def relevance(photo: Dict, query_terms: List[str]) -> Tuple[bool, float]:
    """(good match?, score): the photo's own title / leading tags against the search words."""
    if not query_terms:
        return True, 1.0
    have = set(_terms(photo.get("words") or photo.get("title") or ""))
    hit = [t for t in query_terms if t in have]
    need = len(query_terms) if len(query_terms) <= 2 else max(2, -(-len(query_terms) * 6 // 10))
    return len(hit) >= need, len(hit) / len(query_terms)


# ----------------------------------------------------------------------------- previews (Openverse)
# Many Openverse entries point at photos that no longer exist at the source (its preview service
# answers 424), and it refuses preview requests that look like a web browser. So the server
# checks each Openverse preview while searching, drops dead ones, and serves the working ones
# itself from a small memory cache (/api/vision/photos/preview/<id>).
import threading as _threading
from collections import OrderedDict as _OrderedDict

_PREVIEWS: "_OrderedDict[str, Tuple[bytes, str]]" = _OrderedDict()
_PREVIEW_LOCK = _threading.Lock()
_PREVIEW_MAX = 400


def preview_path(photo_id: str) -> str:
    from urllib.parse import quote
    return "/api/vision/photos/preview/" + quote(photo_id, safe="")


def get_preview(photo_id: str) -> Optional[Tuple[bytes, str]]:
    with _PREVIEW_LOCK:
        hit = _PREVIEWS.get(photo_id)
        if hit:
            _PREVIEWS.move_to_end(photo_id)
        return hit


def _fetch_preview(item: Dict) -> bool:
    if get_preview(item["id"]):   # already checked in an earlier search
        item["thumb"] = preview_path(item["id"])
        return True
    url = item.get("thumb") or ""
    if not _allowed(url):
        return False
    import time as _time
    r = None
    for attempt in (1, 2):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=5)
        except requests.RequestException:
            return False
        if r.status_code != 429 or attempt == 2:
            break
        _time.sleep(1.2)   # the service asks us to slow down: one polite retry
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
    if r.status_code != 200 or not ctype.startswith("image/") or not r.content or len(r.content) > 3 * 1024 * 1024:
        return False
    with _PREVIEW_LOCK:
        _PREVIEWS[item["id"]] = (r.content, ctype)
        while len(_PREVIEWS) > _PREVIEW_MAX:
            _PREVIEWS.popitem(last=False)
    item["thumb"] = preview_path(item["id"])
    return True


def _keep_working(items: List[Dict]) -> List[Dict]:
    """Same order; photos whose preview can't be loaded are dropped (dead links at the source)."""
    check = [it for it in items if str(it.get("thumb", "")).startswith("https://")]   # every source: no hotlinking
    if check:
        from concurrent.futures import ThreadPoolExecutor
        gentle = [it for it in check if str(it["id"]).startswith("pixabay:")]   # Pixabay throttles bursts
        others = [it for it in check if not str(it["id"]).startswith("pixabay:")]
        ok: Dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=8) as ex, ThreadPoolExecutor(max_workers=2) as slow:
            fast_res = ex.map(_fetch_preview, others)
            slow_res = slow.map(_fetch_preview, gentle)
            ok.update(zip([it["id"] for it in others], fast_res))
            ok.update(zip([it["id"] for it in gentle], slow_res))
        items = [it for it in items if ok.get(it["id"], True)]
    return items


def search(query: str, count: int = 10, page: int = 1, seen: Optional[List[str]] = None) -> Tuple[List[Dict], int]:
    """Up to `count` photos not in `seen`, mixed across sources. Returns (photos, next_page)."""
    query = " ".join(str(query or "").split())[:100]
    if len(query) < 2:
        raise PhotoSearchError("Type at least two letters to search.")
    count = max(1, min(int(count or 10), 30))
    seen_set = set(seen or [])
    status = providers_status()
    # every enabled source, mixed: Pixabay / Pexels (when their keys are set) and Openverse
    active = [(n, fn) for n, fn in PROVIDERS if status.get(n)]
    qterms = _terms(query)
    pool: List[Dict] = []
    errors = 0
    page = max(1, int(page or 1))
    last, exhausted = page, False
    from concurrent.futures import ThreadPoolExecutor

    def ask(src):
        name, fn = src
        try:
            return name, fn(query, p), None
        except requests.RequestException as e:
            return name, [], e

    for p in range(page, page + 3):
        last = p
        if not active:
            break
        batches = []
        with ThreadPoolExecutor(max_workers=len(active)) as ex:   # all sources at the same time
            answers = list(ex.map(ask, active))
        for name, batch, err in answers:
            if err is not None:
                errors += 1
                logger.warning(f"[PhotoSearch] {name} unreachable: {err}")
                active = [a for a in active if a[0] != name]   # slow / down: skip it for this search
            else:
                batches.append(batch)
        # interleave the sources so one doesn't fill the whole grid
        for i in range(max((len(b) for b in batches), default=0)):
            for b in batches:
                if i < len(b) and b[i]["id"] not in seen_set and b[i].get("thumb") and b[i].get("url"):
                    good, score = relevance(b[i], qterms)
                    b[i]["match"], b[i]["score"] = ("good" if good else "loose"), round(score, 2)
                    pool.append(b[i])
                    seen_set.add(b[i]["id"])
        if not any(batches):
            exhausted = True
            break
        if sum(1 for x in pool if x["match"] == "good") >= count:
            break
    if not pool and errors:
        raise PhotoSearchError("Couldn't reach the photo services. Check the internet connection and try again.")
    # good matches first (in the services' own order), then the closest loose ones; photos that share
    # no word with the search (sheet music for "glass sheet") are used only if nothing else is left
    ranked = [x for _, x in sorted(enumerate(pool), key=lambda t: (t[1]["match"] != "good", -t[1]["score"], t[0]))]
    usable = [x for x in ranked if x["match"] == "good" or x["score"] > 0] or ranked
    picked: List[Dict] = []
    i = 0
    while len(picked) < count and i < len(usable):   # check previews a dozen at a time until enough work
        chunk = usable[i:i + max(12, count - len(picked) + 4)]
        i += len(chunk)
        picked += _keep_working(chunk)[: count - len(picked)]
    leftovers = i < len(usable)
    return picked, (last if leftovers and not exhausted else last + 1)


# ----------------------------------------------------------------------------- download
def _allowed(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_IMAGE_HOSTS)


def import_photo(url: str, _hops: int = 0, _retry: bool = True) -> bytes:
    """Downloads one chosen photo from an allowed host and returns clean JPEG bytes."""
    if not _allowed(url):
        raise PhotoSearchError("That photo address is not from Pixabay, Pexels or Openverse.")
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, stream=True, allow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                nxt = r.headers.get("Location") or ""
                if _hops >= 3 or not _allowed(nxt):
                    raise PhotoSearchError("The photo moved to an address that isn't allowed.")
                return import_photo(nxt, _hops + 1, _retry)
            if r.status_code == 429 and _retry:   # the service asks us to slow down: one polite retry
                import time
                time.sleep(1.5)
                return import_photo(url, _hops, False)
            if r.status_code != 200:
                raise PhotoSearchError(f"The photo service answered {r.status_code}.")
            buf = io.BytesIO()
            for chunk in r.iter_content(64 * 1024):
                buf.write(chunk)
                if buf.tell() > MAX_DOWNLOAD_BYTES:
                    raise PhotoSearchError("That photo is too large.")
    except requests.RequestException:
        raise PhotoSearchError("Couldn't download that photo. Try another one.")
    from PIL import Image, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(buf.getvalue()))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise PhotoSearchError("That file isn't a readable photo.")
    if img.width * img.height > 60_000_000:
        raise PhotoSearchError("That photo is too large.")
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()
