"""Minimalny klient Supabase (PostgREST) na samym requests — bez dodatkowych zależności."""
from __future__ import annotations

from datetime import datetime, timezone

import requests


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Supabase:
    def __init__(self, url: str, service_key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.session = requests.Session()
        self.session.headers.update({"apikey": service_key, "Content-Type": "application/json"})
        # stare klucze (JWT, zaczynają się od eyJ) trzeba też podać jako Bearer;
        # nowe sb_secret_... wystarczą w nagłówku apikey
        if service_key.startswith("eyJ"):
            self.session.headers["Authorization"] = f"Bearer {service_key}"

    def _req(self, method: str, table: str, params=None, json=None, prefer: str | None = None):
        headers = {"Prefer": prefer} if prefer else {}
        resp = self.session.request(method, f"{self.base}/{table}", params=params, json=json,
                                    headers=headers, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"Supabase {method} {table}: {resp.status_code} {resp.text}")
        return resp.json() if resp.text else None

    # ---------------------------------------------------------------- wyszukiwania
    def enabled_searches(self) -> list[dict]:
        return self._req("GET", "searches", params={"enabled": "eq.true", "order": "id"})

    def searches_by_ids(self, ids: list[int]) -> list[dict]:
        """Wyszukiwania zamówione ze strony — także wyłączone, skoro ktoś kliknął wprost."""
        return self._req("GET", "searches", params={
            "id": f"in.({','.join(map(str, ids))})", "order": "id"})

    def update_search(self, search_id: int, **fields):
        self._req("PATCH", "searches", params={"id": f"eq.{search_id}"}, json=fields)

    # ---------------------------------------------------------------- kolejka ze strony
    def claim_requests(self) -> list[dict]:
        """Przejmuje wszystkie oczekujące prośby (pending → running) i je zwraca."""
        return self._req("PATCH", "run_requests", params={"status": "eq.pending"},
                         json={"status": "running", "started_at": now_iso()},
                         prefer="return=representation")

    def progress_requests(self, ids: list[int], message: str, percent: int | None = None):
        """Postęp trwającego przebiegu — strona pokazuje go na żywo (tekst + pasek)."""
        if ids:
            fields = {"message": message[:500]}
            if percent is not None:
                fields["progress"] = max(0, min(100, percent))
            self._req("PATCH", "run_requests", params={"id": f"in.({','.join(map(str, ids))})"},
                      json=fields)

    def finish_requests(self, ids: list[int], status: str, message: str):
        if ids:
            self._req("PATCH", "run_requests", params={"id": f"in.({','.join(map(str, ids))})"},
                      json={"status": status, "message": message[:500], "finished_at": now_iso()})

    def fail_stale_requests(self, older_than_iso: str):
        """Prośby „running” po padniętym przebiegu blokowałyby kolejkę (unikalny indeks)."""
        self._req("PATCH", "run_requests",
                  params={"status": "eq.running", "started_at": f"lt.{older_than_iso}"},
                  json={"status": "error", "message": "Przebieg przerwany (komputer wyłączony?)",
                        "finished_at": now_iso()})

    def runner(self) -> dict:
        rows = self._req("GET", "runner", params={"id": "eq.1"})
        return rows[0] if rows else {}

    def update_runner(self, **fields):
        self._req("PATCH", "runner", params={"id": "eq.1"}, json=fields)

    # ---------------------------------------------------------------- fiki
    def existing_ids(self, ids: list[int]) -> set[int]:
        if not ids:
            return set()
        rows = self._req("GET", "works", params={
            "select": "work_id", "work_id": f"in.({','.join(map(str, ids))})"})
        return {r["work_id"] for r in rows}

    def upsert_works(self, works: list[dict]):
        """Nowe fiki dodaje, istniejącym odświeża statystyki.
        Nie dotyka statusu ani oceny AI, bo nie wysyłamy tych kolumn."""
        if works:
            self._req("POST", "works", params={"on_conflict": "work_id"}, json=works,
                      prefer="resolution=merge-duplicates,return=minimal")

    def unrated_works(self, limit: int) -> list[dict]:
        return self._req("GET", "works", params={
            "select": "work_id,title,summary,rating,warnings,categories,relationships,"
                      "characters,freeform_tags,words,chapters_current,chapters_total,complete,kudos,hits",
            "ai_score": "is.null", "order": "found_at.asc", "limit": str(limit)})

    def save_rating(self, work_id: int, score: int, categories: list[str], reason: str):
        self._req("PATCH", "works", params={"work_id": f"eq.{work_id}"}, json={
            "ai_score": score, "ai_categories": categories, "ai_reason": reason,
            "ai_rated_at": now_iso()})

    # ---------------------------------------------------------------- profil gustu
    def taste(self) -> str:
        """Profil gustu dla AI. Tagi wybrane na stronie są już dopisane w tekście
        (pod LUBI: / NIE LUBI:), więc liked_tags / disliked_tags służą tylko stronie."""
        rows = self._req("GET", "profile", params={"select": "taste", "id": "eq.1"})
        return rows[0]["taste"] if rows else ""

    def rated_examples(self, limit: int = 15) -> list[dict]:
        """Fiki, które żona już oznaczyła — AI uczy się z nich jej gustu."""
        return self._req("GET", "works", params={
            "select": "title,status,ai_score,freeform_tags",
            "status": "in.(read,skip)", "order": "status_changed_at.desc", "limit": str(limit)})
