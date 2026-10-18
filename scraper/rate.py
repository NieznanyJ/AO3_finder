"""Ocena fików przez Claude'a na podstawie profilu gustu."""
from __future__ import annotations

import json

import anthropic

RATING_TOOL = {
    "name": "save_ratings",
    "description": "Zapisz ocenę każdego fika z listy.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ratings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "work_id": {"type": "integer"},
                        "score": {"type": "integer", "minimum": 1, "maximum": 5,
                                  "description": "1 = na pewno jej się nie spodoba, 5 = idealny strzał"},
                        "categories": {"type": "array", "items": {"type": "string"},
                                       "description": "2-4 krótkie etykiety po polsku, np. 'slow burn', 'komedia', 'mroczne', 'małżeństwo z przymusu'"},
                        "reason": {"type": "string",
                                   "description": "1-2 zdania po polsku: dlaczego taka ocena"},
                    },
                    "required": ["work_id", "score", "categories", "reason"],
                },
            }
        },
        "required": ["ratings"],
    },
}

SYSTEM = """Jesteś doradcą lekturowym. Oceniasz fanfiki z AO3 pod gust konkretnej czytelniczki,
na podstawie tytułu, opisu, tagów i statystyk.

PROFIL GUSTU CZYTELNICZKI:
{taste}
{examples}
Zasady:
- Oceniaj dopasowanie do JEJ gustu, nie obiektywną jakość.
- Tag z listy "nie lubi" to zwykle ocena 1-2, chyba że opis wyraźnie temu przeczy.
- Wysokie kudos/hits w stosunku do wieku fika to sygnał jakości, ale gust jest ważniejszy.
- Używaj spójnych etykiet kategorii między fikami.
- Oceń KAŻDY fik z listy dokładnie raz."""


def _compact(work: dict) -> dict:
    """Skraca dane wysyłane do modelu (mniej tokenów = taniej)."""
    return {
        "work_id": work["work_id"],
        "tytul": work["title"],
        "opis": (work.get("summary") or "")[:1500],
        "rating": work.get("rating"),
        "ostrzezenia": work.get("warnings"),
        "relacje": work.get("relationships"),
        "postacie": (work.get("characters") or [])[:10],
        "tagi": (work.get("freeform_tags") or [])[:40],
        "slowa": work.get("words"),
        "rozdzialy": f"{work.get('chapters_current')}/{work.get('chapters_total') or '?'}",
        "ukonczony": work.get("complete"),
        "kudos": work.get("kudos"),
        "hits": work.get("hits"),
    }


def _examples_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = []
    for e in examples:
        verdict = "przeczytała" if e["status"] == "read" else "odrzuciła"
        tags = ", ".join((e.get("freeform_tags") or [])[:8])
        lines.append(f"- {verdict}: „{e['title']}” (tagi: {tags})")
    return "\nOSTATNIE DECYZJE CZYTELNICZKI (wskazówka, czego szuka):\n" + "\n".join(lines) + "\n"


class Rater:
    def __init__(self, model: str):
        self.client = anthropic.Anthropic()  # czyta ANTHROPIC_API_KEY ze zmiennej środowiskowej
        self.model = model

    def rate_batch(self, works: list[dict], taste: str, examples: list[dict]) -> list[dict]:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM.format(taste=taste.strip() or "(brak — oceniaj neutralnie)",
                                 examples=_examples_block(examples)),
            tools=[RATING_TOOL],
            tool_choice={"type": "tool", "name": "save_ratings"},
            messages=[{"role": "user",
                       "content": json.dumps([_compact(w) for w in works], ensure_ascii=False)}],
        )
        block = next(b for b in resp.content if b.type == "tool_use")
        ratings = block.input["ratings"]

        valid_ids = {w["work_id"] for w in works}
        result = []
        for r in ratings:
            if r["work_id"] in valid_ids:
                r["score"] = max(1, min(5, int(r["score"])))
                result.append(r)
        return result
