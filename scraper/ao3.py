"""Pobieranie i parsowanie stron wyszukiwania AO3."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

BASE = "https://archiveofourown.org"

# wszystkie pola formularza wyszukiwania AO3 — puste też muszą być wysłane
SEARCH_FIELDS = [
    "query", "title", "creators", "revised_at", "complete", "crossover",
    "single_chapter", "word_count", "language_id", "fandom_names", "rating_ids",
    "character_names", "relationship_names", "freeform_names", "hits",
    "kudos_count", "comments_count", "bookmarks_count", "sort_column",
    "sort_direction",
]
DEFAULTS = {"single_chapter": "0", "sort_column": "_score", "sort_direction": "desc"}


class AO3Blocked(Exception):
    """AO3/Cloudflare nie wpuszcza (captcha, 403, 503)."""


def build_search_url(params: dict, page: int = 1) -> str:
    query = []
    for field in SEARCH_FIELDS:
        value = params.get(field, DEFAULTS.get(field, ""))
        query.append((f"work_search[{field}]", "" if value is None else str(value)))
    query += [("commit", "Search"), ("page", str(page))]
    return f"{BASE}/works/search?{urlencode(query)}"


# przeciążenie / timeout po stronie AO3 lub Cloudflare (520–526) — warto spróbować ponownie
TRANSIENT_STATUSES = {500, 502, 504, 520, 521, 522, 523, 524, 525, 526}


class AO3Client:
    """Pobiera strony AO3 przez prawdziwego Chrome'a (Playwright).

    Cloudflare przed AO3 odrzuca zwykłe klienty HTTP (requests, curl, Chrome headless)
    błędem 525/503 — przepuszcza tylko przeglądarkę z oknem. Okno otwieramy poza ekranem,
    z osobnym profilem w .ao3-profile/, żeby nie ruszać codziennego Chrome'a.
    """

    PROFILE_DIR = Path(__file__).parent.parent / ".ao3-profile"

    def __init__(self, delay: float = 6.0, max_retries: int = 3):
        self.delay = delay
        self.max_retries = max_retries
        self._last_request = 0.0
        self._pw = self._ctx = self._page = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _start(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(self.PROFILE_DIR), channel="chrome", headless=False,
            args=["--window-position=-32000,-32000"])  # okno poza ekranem
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def close(self):
        if self._ctx:
            self._ctx.close()
        if self._pw:
            self._pw.stop()
        self._pw = self._ctx = self._page = None

    def get(self, url: str) -> str:
        from playwright.sync_api import TimeoutError as PWTimeout

        if self._page is None:
            self._start()
        for attempt in range(1, self.max_retries + 1):
            # grzeczna przerwa między zapytaniami
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

            # wyszukiwarka AO3 bywa bardzo wolna — odpowiedź potrafi przyjść po 2 minutach
            try:
                resp = self._page.goto(url, wait_until="domcontentloaded", timeout=180_000)
            except PWTimeout:
                resp = None
            status = resp.status if resp else None
            if status is None or status in TRANSIENT_STATUSES:
                if attempt == self.max_retries:
                    break
                pause = 60 * attempt
                code = "timeout" if status is None else f"HTTP {status}"
                print(f"  AO3 chwilowo nie odpowiada ({code}) — czekam {pause}s (próba {attempt})")
                time.sleep(pause)
                continue

            if status == 429:
                retry_after = min(int(resp.headers.get("retry-after", "60") or 60), 300)
                print(f"  429 rate limit — czekam {retry_after}s (próba {attempt})")
                time.sleep(retry_after)
                continue
            if "Just a moment" in self._page.title():
                # sprawdzenie Cloudflare zwykle przechodzi samo w kilka sekund
                try:
                    self._page.wait_for_function("!document.title.includes('Just a moment')", timeout=30_000)
                    self._page.wait_for_load_state("domcontentloaded")
                    return self._page.content()
                except PWTimeout:
                    raise AO3Blocked("Cloudflare nie przepuścił przeglądarki (captcha?)") from None
            if status in (403, 503):
                raise AO3Blocked(f"AO3 zablokował zapytanie (HTTP {status})")
            if status >= 400:
                raise RuntimeError(f"AO3 HTTP {status} dla {url}")
            return self._page.content()
        raise AO3Blocked("AO3 nie odpowiada albo ogranicza zapytania (429/5xx), spróbuj później")


# ---------------------------------------------------------------- parsowanie

def _int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _texts(blurb: Tag, selector: str) -> list[str]:
    return [a.get_text(strip=True) for a in blurb.select(selector)]


def _stat(blurb: Tag, name: str) -> str | None:
    dd = blurb.select_one(f"dl.stats dd.{name}")
    return dd.get_text(strip=True) if dd else None


def parse_blurb(blurb: Tag) -> dict:
    work_id = int(blurb["id"].removeprefix("work_"))
    title_a = blurb.select_one('h4.heading a[href^="/works/"]')

    summary_el = blurb.select_one("blockquote.summary")
    summary = summary_el.get_text("\n", strip=True) if summary_el else None

    rating_el = blurb.select_one("ul.required-tags span.rating")
    category_el = blurb.select_one("ul.required-tags span.category")
    wip_el = blurb.select_one("ul.required-tags span.iswip")

    chapters = _stat(blurb, "chapters") or ""
    current, _, total = chapters.partition("/")

    date_el = blurb.select_one("p.datetime")
    updated_on = None
    if date_el:
        try:
            updated_on = datetime.strptime(date_el.get_text(strip=True), "%d %b %Y").date().isoformat()
        except ValueError:
            pass

    series_el = blurb.select_one("ul.series li")
    series = " ".join(series_el.get_text(" ", strip=True).split()) if series_el else None

    lang_el = blurb.select_one("dl.stats dd.language")

    return {
        "work_id": work_id,
        "url": f"{BASE}/works/{work_id}",
        "title": title_a.get_text(strip=True) if title_a else f"Work {work_id}",
        "authors": _texts(blurb, 'h4.heading a[rel="author"]'),
        "summary": summary,
        "language": lang_el.get_text(strip=True) if lang_el else None,
        "rating": rating_el.get("title") if rating_el else None,
        "warnings": _texts(blurb, "ul.tags li.warnings a"),
        "categories": [c.strip() for c in category_el.get("title", "").split(",") if c.strip()] if category_el else [],
        "relationships": _texts(blurb, "ul.tags li.relationships a"),
        "characters": _texts(blurb, "ul.tags li.characters a"),
        "freeform_tags": _texts(blurb, "ul.tags li.freeforms a"),
        "series": series,
        "words": _int(_stat(blurb, "words")),
        "chapters_current": _int(current),
        "chapters_total": _int(total),  # "?" → None
        "complete": (wip_el.get("title") == "Complete Work") if wip_el else None,
        "kudos": _int(_stat(blurb, "kudos")) or 0,
        "hits": _int(_stat(blurb, "hits")) or 0,
        "comments": _int(_stat(blurb, "comments")) or 0,
        "bookmarks": _int(_stat(blurb, "bookmarks")) or 0,
        "updated_on": updated_on,
    }


def parse_search_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    works = [parse_blurb(li) for li in soup.select("ol.work.index > li.work.blurb")]

    total = None
    for h3 in soup.select("#main h3.heading"):
        m = re.search(r"([\d,]+)\s+Found", h3.get_text())
        if m:
            total = _int(m.group(1))
            break

    return {
        "works": works,
        "total_found": total,
        "has_next": soup.select_one("ol.pagination li.next a") is not None,
    }


# ---------------------------------------------------------------- filtr wstępny

def passes_prefilter(work: dict, relationship_must: list[str], exclude_tags: list[str]) -> tuple[bool, str]:
    """Zwraca (czy_przechodzi, powód_odrzucenia)."""
    must = [m.lower() for m in relationship_must if m.strip()]
    if must:
        rels = [r.lower() for r in work["relationships"]]
        if not any(all(m in r for m in must) for r in rels):
            return False, "brak wymaganej relacji"

    excl = [e.lower() for e in exclude_tags if e.strip()]
    if excl:
        all_tags = work["warnings"] + work["relationships"] + work["characters"] + work["freeform_tags"]
        for tag in all_tags:
            low = tag.lower()
            for e in excl:
                if e in low:
                    return False, f"wykluczony tag: {tag}"
    return True, ""
