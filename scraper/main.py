"""AO3 Fic Finder — scraper + ocena AI.

Użycie:
  python scraper/main.py scrape            # przejdź zapisane wyszukiwania
  python scraper/main.py rate              # oceń nowe fiki przez Claude'a
  python scraper/main.py all               # jedno i drugie (tak odpala GitHub Actions)
  python scraper/main.py queue             # wykonaj prośby ze strony + codzienny przebieg
                                           #   (Harmonogram zadań Windows, co 5 minut)
  python scraper/main.py parse plik.html   # test parsera na zapisanej stronie, bez bazy i sieci
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ao3 import AO3Blocked, AO3Client, build_search_url, parse_search_page, passes_prefilter  # noqa: E402


def load_dotenv():
    """Wczytuje .env przy uruchomieniu lokalnym (w GitHub Actions zmienne są z Secrets)."""
    env = Path(__file__).parent.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        sys.exit(f"Brak zmiennej środowiskowej {name} (ustaw w .env albo w GitHub Secrets)")
    return value


def get_db():
    from db import Supabase
    return Supabase(env("SUPABASE_URL"), env("SUPABASE_SERVICE_KEY"))


# ---------------------------------------------------------------- scrape

def _no_progress(_message: str, _percent: int | None = None):
    pass


# pasek postępu na stronie: start 0–5 %, wyszukiwanie 5–70 %, ocena AI 70–100 %
SCRAPE_FROM, SCRAPE_TO = 5, 70


def scrape(search_ids: list[int] | None = None, progress=_no_progress) -> dict:
    """Przechodzi aktywne wyszukiwania (albo tylko podane, także wyłączone).
    Zwraca {"new": liczba nowych fików, "errors": [opisy błędów]}."""
    from db import now_iso

    db = get_db()
    searches = db.searches_by_ids(search_ids) if search_ids else db.enabled_searches()
    print(f"Wyszukiwań do przejścia: {len(searches)}")
    # Chrome startuje dopiero przy pierwszej stronie i zamyka się po przebiegu
    with AO3Client(delay=float(env("AO3_DELAY_SECONDS", "6"))) as client:
        return _scrape_searches(db, client, searches, progress)


def _scrape_searches(db, client: AO3Client, searches: list[dict], progress) -> dict:
    from db import now_iso

    total_new = 0
    errors = []
    for si, s in enumerate(searches):
        print(f"\n== {s['name']} (od strony {s['last_page'] + 1}, max {s['max_pages_per_run']}) ==")
        page = s["last_page"]
        progress(f"{s['name']}: pobieram stronę {page + 1} z AO3…",
                 SCRAPE_FROM + (SCRAPE_TO - SCRAPE_FROM) * si // len(searches))
        try:
            for done_pages in range(1, s["max_pages_per_run"] + 1):
                page += 1
                result = parse_search_page(client.get(build_search_url(s["params"], page)))
                works = result["works"]

                kept, rejected = [], 0
                for w in works:
                    ok, _why = passes_prefilter(w, s["relationship_must"], s["exclude_tags"])
                    if ok:
                        w["search_id"] = s["id"]
                        w["last_seen_at"] = now_iso()
                        kept.append(w)
                    else:
                        rejected += 1

                known = db.existing_ids([w["work_id"] for w in kept])
                fresh = [w for w in kept if w["work_id"] not in known]
                seen = [w for w in kept if w["work_id"] in known]
                for w in seen:
                    w.pop("search_id")  # nie nadpisuj, które wyszukiwanie znalazło go pierwsze
                # osobno, bo PostgREST wymaga tych samych kluczy w jednej paczce
                db.upsert_works(fresh)
                db.upsert_works(seen)
                new = len(fresh)
                total_new += new
                print(f"  strona {page}: {len(works)} fików, {rejected} odrzuconych filtrem, {new} nowych")
                # ile stron obejmie ten przebieg: do końca wyników, ale nie więcej niż limit
                all_pages = math.ceil(result["total_found"] / 20) if result["total_found"] else page
                planned = max(1, min(s["max_pages_per_run"], all_pages - s["last_page"]))
                share = (si + min(1, done_pages / planned)) / len(searches)
                progress(f"{s['name']}: przejrzana strona {page} z {all_pages}, nowych fików dotąd: {total_new}",
                         round(SCRAPE_FROM + (SCRAPE_TO - SCRAPE_FROM) * share))

                done = not result["has_next"] or not works
                db.update_search(s["id"], last_page=0 if done else page,
                                 total_found=result["total_found"],
                                 last_run_at=now_iso(), last_error=None)
                if done:
                    print("  koniec wyników — następnym razem zaczynam od strony 1")
                    break
        except AO3Blocked as e:
            print(f"  STOP: {e}")
            db.update_search(s["id"], last_error=str(e), last_run_at=now_iso())
            errors.append(f"{s['name']}: {e}")
            break  # nie męczymy AO3 kolejnymi wyszukiwaniami
        except Exception as e:  # noqa: BLE001
            print(f"  BŁĄD: {e}")
            db.update_search(s["id"], last_error=str(e)[:500], last_run_at=now_iso())
            errors.append(f"{s['name']}: {e}")

    print(f"\nRazem nowych fików: {total_new}")
    return {"new": total_new, "errors": errors}


# ---------------------------------------------------------------- rate

def rate(progress=_no_progress) -> int:
    """Ocenia nieocenione fiki; zwraca, ile oceniono."""
    from rate import Rater

    db = get_db()
    rater = Rater(model=env("AI_MODEL", "claude-haiku-5-5"))
    batch_size = int(env("AI_BATCH_SIZE", "10"))
    max_per_run = int(env("AI_MAX_PER_RUN", "100"))  # limit kosztów na jeden przebieg

    taste = db.taste()
    examples = db.rated_examples()
    works = db.unrated_works(max_per_run)
    print(f"Do oceny: {len(works)}")

    rated = 0
    for i in range(0, len(works), batch_size):
        progress(f"Ocena AI: {i}/{len(works)} fików", SCRAPE_TO + (100 - SCRAPE_TO) * i // len(works))
        batch = works[i:i + batch_size]
        try:
            ratings = rater.rate_batch(batch, taste, examples)
        except Exception as e:  # noqa: BLE001
            print(f"  BŁĄD oceny paczki {i // batch_size + 1}: {e}")
            continue
        for r in ratings:
            db.save_rating(r["work_id"], r["score"], r["categories"], r["reason"])
            title = next(w["title"] for w in batch if w["work_id"] == r["work_id"])
            print(f"  {r['score']}/5  {title[:60]}")
            rated += 1
    return rated


# ---------------------------------------------------------------- queue (prośby ze strony)

def queue():
    """Jedno sprawdzenie kolejki. Odpalane co kilka minut przez Harmonogram zadań —
    gdy nic nie czeka i nie pora na codzienny przebieg, kończy się bez pytania AO3."""
    from db import now_iso

    db = get_db()
    db.update_runner(last_seen_at=now_iso())  # strona pokazuje, że komputer żyje
    db.fail_stale_requests((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())

    daily_hour = env("QUEUE_DAILY_HOUR", "8").strip()
    today = date.today().isoformat()
    daily_due = (daily_hour != "" and datetime.now().hour >= int(daily_hour)
                 and db.runner().get("last_daily_run_on") != today)
    requests_ = db.claim_requests()

    if not requests_ and not daily_due:
        print("Kolejka pusta.")
        return

    ids = [r["id"] for r in requests_]
    # prośba „wszystkie” (search_id = null) albo codzienny przebieg → wszystkie aktywne
    run_all = daily_due or any(r["search_id"] is None for r in requests_)
    search_ids = None if run_all else sorted({r["search_id"] for r in requests_})
    print(f"Prośby ze strony: {len(ids)}, codzienny przebieg: {'tak' if daily_due else 'nie'}")

    try:
        def progress(message: str, percent: int | None = None):
            try:
                db.progress_requests(ids, message, percent)
            except Exception:  # noqa: BLE001 — np. przed 06_run_progress.sql: sam tekst bez paska
                try:
                    db.progress_requests(ids, message)
                except Exception as e:  # noqa: BLE001 — postęp to tylko podgląd, nie przerywa przebiegu
                    print(f"  (nie zapisano postępu: {e})")

        progress("Uruchamiam przeglądarkę…", 2)
        result = scrape(search_ids, progress)
        progress(f"Wyszukiwanie skończone (nowych fików: {result['new']}), zaczynam ocenę AI…", SCRAPE_TO)
        rated = rate(progress)
    except Exception as e:  # noqa: BLE001
        db.finish_requests(ids, "error", str(e))
        raise
    if daily_due:
        db.update_runner(last_daily_run_on=today)

    message = f"Nowych fików: {result['new']}, ocenionych: {rated}"
    if result["errors"]:
        message += " · " + "; ".join(result["errors"])
    db.finish_requests(ids, "error" if result["errors"] else "done", message)


# ---------------------------------------------------------------- parse (test)

def parse_file(path: str):
    result = parse_search_page(Path(path).read_text(encoding="utf-8"))
    print(f"Fików: {len(result['works'])}, wszystkich wyników: {result['total_found']}, "
          f"jest następna strona: {result['has_next']}\n")
    for w in result["works"]:
        ok, why = passes_prefilter(w, ["draco", "herm"], [])
        mark = "✓" if ok else "✗"
        print(f"{mark} {w['work_id']:>10}  {w['words'] or 0:>7} słów  {w['title'][:55]}  {why}")
    print("\nPierwszy fik jako JSON:")
    print(json.dumps(result["works"][0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # konsola Windows domyślnie nie radzi sobie z polskimi znakami
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "scrape":
        scrape()
    elif cmd == "rate":
        rate()
    elif cmd == "all":
        scrape()
        rate()
    elif cmd == "queue":
        queue()
    elif cmd == "parse" and len(sys.argv) > 2:
        parse_file(sys.argv[2])
    else:
        print(__doc__)
