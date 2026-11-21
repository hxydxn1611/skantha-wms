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

TIMEOUT = 8
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
                    "license": "Pixabay Content License"})
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
                    "license": "Pexels License"})
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
                    "title": str(it.get("title") or "")[:120]})
    return out


PROVIDERS = (("pixabay", _pixabay), ("pexels", _pexels), ("openverse", _openverse))


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
    found: List[Dict] = []
    errors = 0
    page = max(1, int(page or 1))
    for p in range(page, page + 3):
        batches = []
        for name, fn in active:
            try:
                batches.append(fn(query, p))
            except requests.RequestException as e:
                errors += 1
                logger.warning(f"[PhotoSearch] {name} unreachable: {e}")
        # interleave the sources so one doesn't fill the whole grid
        for i in range(max((len(b) for b in batches), default=0)):
            for b in batches:
                if i < len(b) and b[i]["id"] not in seen_set and b[i].get("thumb") and b[i].get("url"):
                    found.append(b[i])
                    seen_set.add(b[i]["id"])
        if len(found) >= count:
            return found[:count], p + (0 if len(found) > count else 1)
        if not any(batches):
            break
    if not found and errors:
        raise PhotoSearchError("Couldn't reach the photo services. Check the internet connection and try again.")
    return found[:count], page + 3


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
