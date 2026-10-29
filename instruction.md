# instruction.md — AO3 Fic Finder („Półka z fikami”)

Instrukcja dla Claude Code: czym jest projekt, jak działa każdy element, jaki jest stan prac
i jak wdrażać kolejne kroki. Czytaj ją w całości przed zmianami w kodzie.

---

## 1. Cel

Automatyczne wyszukiwanie fanfików na AO3 (archiveofourown.org) dla jednej czytelniczki (żony autora repo):

1. Zapisane wyszukiwania AO3 są przeglądane strona po stronie — **tylko na żądanie** (przycisk „Szukaj teraz”
   na stronie albo ręczne `main.py scrape/all`). Żadnego automatycznego przebiegu (decyzja użytkownika 2026-10-29).
2. Fiki niepasujące (np. inna relacja, wykluczone tagi) są odrzucane bez AI.
3. Nowe fiki trafiają do bazy (bez duplikatów, klucz = ID z AO3).
4. Claude ocenia każdy nowy fik w skali 1–5 pod jej gust i nadaje kategorie.
5. Prywatna strona pokazuje wyniki z linkami i oceną; czytelniczka oznacza status
   (do przeczytania / czytam / przeczytane / pomiń), edytuje wyszukiwania i swój profil gustu.

Główny przypadek: Dramione (Draco Malfoy / Hermiona Granger), fiki po polsku. System jest jednak ogólny.

Użytkownik (autor repo) pracuje na **Windowsie**, interfejs i komunikaty są **po polsku**.

---

## 2. Architektura

```
┌──────────────────────────┐      ┌──────────────────────────────┐      ┌────────────────────────┐
│ Komputer (Harmonogram,   │      │ Supabase (Postgres + Auth)   │      │ GitHub Pages (static)  │
│ co 5 min) main.py queue  │─────▶│ works / searches / profile   │◀─────│ docs/index.html        │
│ Chrome przez Playwright  │ REST │ run_requests / runner        │ JS   │ supabase-js + login    │
│  1. scrape (AO3, 6 s)    │ key: │ RLS: strona widzi dane tylko │ key: │ - lista fików          │
│  2. prefilter + dedupe   │secret│ po zalogowaniu               │publ. │ - edycja wyszukiwań    │
│  3. rate (Claude API)    │      │                              │      │ - edycja gustu         │
└──────────────────────────┘      └──────────────────────────────┘      └────────────────────────┘
             │
             ▼
   archiveofourown.org (HTML)          api.anthropic.com (Messages API, tool use)
```

Przepływ jednego przebiegu (`main.py all`):

1. Pobierz z `searches` wszystkie wyszukiwania z `enabled = true`.
2. Dla każdego: od `last_page + 1`, maks. `max_pages_per_run` stron:
   pobierz HTML → sparsuj blurby → filtr wstępny → sprawdź, które ID już są → upsert → zapisz stan.
3. Brak następnej strony → `last_page = 0` (kolejny przebieg zaczyna od początku; znane fiki
   są tylko odświeżane, nie duplikowane).
4. Pobierz fiki z `ai_score IS NULL` (maks. `AI_MAX_PER_RUN`), oceniaj paczkami po `AI_BATCH_SIZE`.

### Decyzje projektowe (i dlaczego)

| Decyzja | Powód |
|---|---|
| Python + GitHub Actions, nie n8n | Darmowy harmonogram bez włączonego komputera, kod w gicie, testowalny parser. n8n był rozważany i porzucony. |
| Supabase, nie pliki JSON w repo | Strona musi zapisywać statusy; GitHub Pages jest statyczny. Darmowy plan wystarcza (500 MB). Codzienne zapisy zapobiegają usypianiu projektu po 7 dniach bez aktywności. |
| Logowanie Supabase Auth + RLS | Kod strony jest publiczny (GitHub Pages), dane nie. Rejestracja wyłączona, dostęp tylko dla maili z `allowed_users`. |
| Klient REST na `requests`, bez `supabase-py` | Mniej zależności; potrzebne są tylko GET/POST/PATCH. |
| `tool_choice` wymuszający narzędzie `save_ratings` | Gwarantowany JSON w ustalonym kształcie, bez parsowania tekstu. |
| Strona = jeden plik HTML bez builda | Zero narzędzi, działa na GitHub Pages od ręki; supabase-js z CDN jako ES module. |
| Biblioteka `ao3_api` (wendytg) — nie używamy | Potrzebujemy tylko parsowania strony wyników; własny parser jest prostszy w utrzymaniu. Do pobierania też nie: chodzi przez `requests`, który AO3 odrzuca (525), a EPUB/PDF pobiera po prostu przeglądarka czytelniczki z linku na karcie. |

---

## 3. Struktura repo

```
ao3-fic-finder/
├── instruction.md                 ← ten plik
├── CLAUDE.md                      ← odsyła tutaj
├── README.md                      ← skrócona instrukcja dla człowieka
├── requirements.txt               ← requests, beautifulsoup4, anthropic, playwright
├── .env.example                   ← szablon zmiennych (lokalnie kopiowany jako .env)
├── .gitignore                     ← .env, __pycache__, .venv
├── .github/workflows/scrape.yml   ← cron + ręczne uruchomienie
├── sql/
│   ├── 01_schema.sql              ← works, allowed_users, is_allowed(), RLS   [URUCHOMIONE]
│   ├── 02_searches_profile.sql    ← searches, profile, drop search_state      [DO URUCHOMIENIA]
│   ├── 03_run_requests.sql        ← run_requests (kolejka ze strony), runner  [URUCHOMIONE]
│   ├── 04_clear_run_requests.sql  ← strona może usuwać prośby (nie „running”) [DO URUCHOMIENIA]
│   ├── 05_taste_tags.sql          ← profile.liked_tags / disliked_tags        [DO URUCHOMIENIA]
│   └── 06_run_progress.sql        ← run_requests.progress (pasek postępu)     [DO URUCHOMIENIA]
├── scraper/
│   ├── main.py                    ← CLI: scrape | rate | all | parse <plik>
│   ├── ao3.py                     ← URL, klient HTTP, parser, filtr wstępny
│   ├── db.py                      ← klient Supabase (PostgREST)
│   └── rate.py                    ← ocena przez Claude API
├── docs/
│   ├── index.html                 ← strona (GitHub Pages serwuje folder /docs)
│   └── config.js                  ← URL Supabase + klucz publishable (publiczne!)
└── tests/
    └── fixture_search.html        ← prawdziwa strona wyników AO3 (75 wyników, 20 na stronie)
```

---

## 4. Model danych (Supabase / Postgres)

Źródło prawdy: pliki w `sql/`. Każda zmiana schematu = **nowy** plik `sql/0N_opis.sql`
(nie edytuj już uruchomionych plików).

### `works` — fiki
| Kolumna | Typ | Uwagi |
|---|---|---|
| `work_id` | bigint PK | ID z AO3, gwarantuje brak duplikatów |
| `url`, `title`, `authors[]`, `summary`, `language` | | z blurba |
| `rating`, `warnings[]`, `categories[]`, `relationships[]`, `characters[]`, `freeform_tags[]`, `series` | | tagi AO3 |
| `words`, `chapters_current`, `chapters_total` (null = „?”), `complete`, `kudos`, `hits`, `comments`, `bookmarks`, `updated_on` | | statystyki |
| `ai_score` (1–5), `ai_categories[]`, `ai_reason`, `ai_rated_at` | | wypełnia `rate.py`; `ai_score IS NULL` = czeka na ocenę |
| `status` | text | `new` / `to_read` / `reading` / `read` / `skip` — ustawia strona |
| `status_changed_at` | | trigger `works_status_changed` |
| `search_id` | FK → searches | które wyszukiwanie znalazło fik pierwsze (z 02) |
| `found_at`, `last_seen_at` | | |

### `searches` — zapisane wyszukiwania (z 02)
| Kolumna | Uwagi |
|---|---|
| `name`, `enabled` | |
| `params` jsonb | pola formularza AO3 bez prefiksu, np. `{"query": "...", "language_id": "pl", "sort_column": "word_count"}` |
| `relationship_must[]` | wszystkie frazy muszą wystąpić w **jednym** tagu relacji (case-insensitive), np. `{draco,herm}`; puste = bez filtra |
| `exclude_tags[]` | fragment dowolnego tagu (ostrzeżenia, relacje, postacie, freeform) → odrzuć |
| `max_pages_per_run` (1–50) | |
| `last_page`, `total_found`, `last_run_at`, `last_error` | stan; `last_page = 0` → następny przebieg od strony 1 |

### `profile` — gust (jeden wiersz, `id = 1`)
`taste` (tekst swobodny, edytowany na stronie — **jedyne, co czyta AI**), `liked_tags[]` / `disliked_tags[]`
(tagi wybrane na stronie, z 05 — tylko do wyświetlania chipów; ich treść jest już w `taste`), `updated_at` (trigger).

### `run_requests` — kolejka „Szukaj teraz” (z 03)
`search_id` (null = wszystkie aktywne; `on delete cascade`), `status` `pending` → `running` → `done`/`error`,
`message` (wynik albo błąd), `requested_by` (mail z JWT), `requested_at`, `started_at`, `finished_at`.
Unikalny indeks częściowy: najwyżej jedna prośba `pending`/`running` na wyszukiwanie (i jedna „wszystkie”) —
kolejne kliknięcie dostaje błąd `23505`, strona pokazuje „już czeka w kolejce”.

### `runner` — stan komputera obsługującego kolejkę (jeden wiersz, `id = 1`, z 03)
`last_seen_at` (każde `main.py queue`). Kolumna `last_daily_run_on` została po usuniętym codziennym przebiegu
— nieużywana.

### `allowed_users`
`email` PK. Funkcja `is_allowed()` (security definer) porównuje z `auth.jwt() ->> 'email'`.

### Uprawnienia (RLS + granty kolumnowe)
- `service_role` / klucz secret (scraper) omija RLS — pełny dostęp.
- `anon`: brak dostępu do czegokolwiek.
- `authenticated` + `is_allowed()`:
  - `works`: SELECT, UPDATE **tylko kolumny `status`**.
  - `searches`: SELECT, INSERT, DELETE, UPDATE tylko `name, enabled, params, relationship_must, exclude_tags, max_pages_per_run, last_page`.
  - `profile`: SELECT, UPDATE tylko `taste`.
  - `allowed_users`: brak.
- Dodając kolumnę, którą strona ma zmieniać, **trzeba dodać grant w nowej migracji**.

---

## 5. Komponenty — szczegóły działania

### 5.1 `scraper/ao3.py`

**URL wyszukiwania** — `build_search_url(params, page)`. AO3 oczekuje wszystkich pól formularza
(także pustych) w kolejności `SEARCH_FIELDS`, potem `commit=Search&page=N`.
Domyślne: `single_chapter=0`, `sort_column=_score`, `sort_direction=desc`.
Przetestowane: URL dla `{"query": "draco malfoy/Hermiona Granger", "language_id": "pl", "sort_column": "word_count", "sort_direction": "desc"}`
jest identyczny z linkiem użytkownika.

Pola `params` (= `work_search[...]` w AO3): `query, title, creators, revised_at, complete (T/F),
crossover, single_chapter, word_count (np. ">50000", "10000-80000"), language_id (np. "pl"),
fandom_names, rating_ids (9 Not Rated, 10 General, 11 Teen, 12 Mature, 13 Explicit),
character_names, relationship_names, freeform_names, hits, kudos_count, comments_count,
bookmarks_count, sort_column (_score, revised_at, created_at, word_count, kudos_count, hits),
sort_direction (asc/desc)`.

**Klient HTTP** — `AO3Client.get(url)`, **przez Playwright i zainstalowany Chrome** (`channel="chrome"`,
`headless=False`, okno poza ekranem `--window-position=-32000,-32000`, profil w `.ao3-profile/`, gitignored).
Powód (sprawdzone 2026-10-18): Cloudflare przed AO3 zwraca 525/503 dla `requests`, curl (HTTP/1.1 i 2, IPv4 i 6),
Node.js i Chrome headless — przepuszcza tylko Chrome z oknem. Chrome startuje przy pierwszym `get()`,
zamyka się po `scrape()` (`with AO3Client(...)`). Wymaga zalogowanego użytkownika Windows (okno).
Nie wracaj do `requests` / headless bez ponownego sprawdzenia, czy AO3 je wpuszcza.
GitHub Actions też odpadają (test 2026-10-18): z runnera (IP Azure, USA) nawet Chrome z oknem na `xvfb-run`
dostaje 525 — Cloudflare odcina adresy serwerowni. Scrapowanie działa tylko z domowego łącza.
- odstęp między zapytaniami `AO3_DELAY_SECONDS` (domyślnie 6 s, **nie schodzić poniżej 5**),
- 429 → czekaj `Retry-After` (maks. 300 s), do 3 prób,
- 403/503 lub „Just a moment” (Cloudflare) → wyjątek `AO3Blocked`; `main.py` przerywa cały przebieg
  scrapowania (nie męczymy AO3 kolejnymi wyszukiwaniami) i zapisuje błąd w `searches.last_error`;
  przy „Just a moment” najpierw czeka do 30 s, aż sprawdzenie Cloudflare przejdzie samo,
- User-Agent wysyła sam Chrome (zmienna `AO3_USER_AGENT` nie jest już używana).

**Parser** — `parse_search_page(html)` → `{works, total_found, has_next}`. Selektory (stabilne w AO3 od lat):

| Pole | Selektor / źródło |
|---|---|
| blurby | `ol.work.index > li.work.blurb`, `id="work_<ID>"` |
| tytuł | `h4.heading a[href^="/works/"]` |
| autorzy | `h4.heading a[rel="author"]` |
| opis | `blockquote.summary` (tekst, akapity przez `\n`) |
| rating / kategorie / ukończony | atrybut `title` w `ul.required-tags span.rating` / `span.category` (przecinki) / `span.iswip` (`"Complete Work"`) |
| ostrzeżenia, relacje, postacie, freeform | `ul.tags li.warnings a`, `li.relationships a`, `li.characters a`, `li.freeforms a` |
| seria | `ul.series li` |
| statystyki | `dl.stats dd.words / chapters / kudos / hits / comments / bookmarks / language`; liczby z przecinkami → int, brak → 0; `chapters` „37/70” lub „16/?” |
| data | `p.datetime`, format `%d %b %Y` → ISO |
| łączna liczba | `#main h3.heading` z „N Found” |
| następna strona | `ol.pagination li.next a` (na ostatniej stronie jest `span.disabled`) |

**Filtr wstępny** — `passes_prefilter(work, relationship_must, exclude_tags)` → `(bool, powód)`.
Na fixture z `{draco, herm}` odrzuca 4 z 20 (Draco/Harry + Connor/Parvati, James/Lily + Narcyza/Lucjusz, Harriet Potter bez relacji, Albus Potter).

### 5.2 `scraper/db.py`
- Nagłówek `apikey` zawsze; `Authorization: Bearer` tylko dla kluczy legacy (JWT, `eyJ...`).
  Nowe klucze `sb_secret_...` działają w samym `apikey`.
- `upsert_works`: `POST /works?on_conflict=work_id` z `Prefer: resolution=merge-duplicates`.
  Aktualizuje tylko przesłane kolumny, więc **nigdy nie wysyłaj `status` ani `ai_*` ze scrapera**.
- **PostgREST wymaga identycznych kluczy we wszystkich obiektach jednej paczki** — dlatego
  `main.py` wysyła nowe fiki (z `search_id`) i znane (bez `search_id`) w osobnych upsertach.
- `rated_examples()`: ostatnie fiki ze statusem `read`/`skip` — podawane modelowi jako wskazówka gustu.

### 5.3 `scraper/rate.py`
- `anthropic.Anthropic()` czyta `ANTHROPIC_API_KEY`. Model z `AI_MODEL` (domyślnie `claude-haiku-5-5`;
  alternatywa `claude-sonnet-5-5`).
- Narzędzie `save_ratings` + `tool_choice={"type": "tool", "name": "save_ratings"}` → odpowiedź zawsze
  w kształcie `{"ratings": [{work_id, score, categories[2-4], reason}]}`.
- System prompt: profil gustu z `profile.taste` + ostatnie decyzje czytelniczki + zasady
  (ocena dopasowania do gustu, nie jakości; tag z „nie lubi” → 1–2; spójne etykiety; każdy fik raz).
- `_compact()` skraca dane (opis do 1500 znaków, do 40 tagów, 10 postaci) — mniej tokenów.
- Walidacja: ignoruj `work_id` spoza paczki, `score` przycinany do 1–5.
- Błąd jednej paczki nie przerywa reszty (fiki zostają z `ai_score = null` i wrócą przy następnym przebiegu).

### 5.4 `scraper/main.py`
- `load_dotenv()` — prosty parser `.env` (bez zależności); w Actions zmienne idą z Secrets.
- Na starcie `stdout.reconfigure(encoding="utf-8")` — konsola Windows i polskie znaki.
- `parse <plik>` — test parsera bez sieci i bazy.
- `queue` — jedno sprawdzenie kolejki, odpalane przez Harmonogram zadań Windows co 5 min
  (ustawienie „nie uruchamiaj nowego wystąpienia”, więc przebiegi się nie nakładają):
  1. `runner.last_seen_at = now` (strona pokazuje, czy komputer żyje), prośby `running` starsze niż 2 h → `error`.
  2. Przejmuje wszystkie `pending` (PATCH → `running`).
  3. Brak próśb → koniec bez zapytań do AO3 (**nie ma automatycznego codziennego przebiegu** — scraper
     rusza AO3 tylko na prośbę). Prośba „wszystkie” → wszystkie aktywne; inaczej tylko zamówione
     wyszukiwania (także wyłączone). Potem `rate()`.
  4. Prośby → `done` z „Nowych fików: N, ocenionych: M” albo `error` z błędami wyszukiwań.
  W trakcie `progress(message, percent)` → `db.progress_requests()` zapisuje w prośbach `message` (co się dzieje)
  i `progress` 0–100 (start 0–5, wyszukiwanie 5–70 proporcjonalnie do stron, ocena AI 70–100). Bez kolumny
  `progress` (przed 06) zapisuje sam tekst; błąd zapisu postępu nigdy nie przerywa przebiegu.
- `scrape(search_ids=None)` zwraca `{"new", "errors"}`, `rate()` zwraca liczbę ocenionych.

### 5.5 `.github/workflows/scrape.yml`
- Tylko `workflow_dispatch` → `main.py rate` (ręczne przeliczenie ocen bez włączonego komputera).
  Bez crona i bez scrapowania: na serwerach GitHuba nie ma ekranu dla Chrome'a, a AO3 nie wpuszcza headless.
- Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`. Opcjonalna Variable: `AI_MODEL`.

### 5.6 `docs/index.html` (+ `config.js`)
- **Logowanie**: pole „login lub e-mail” + hasło.
  - Login bez `@` → `login@LOGIN_DOMAIN` (np. `kasia@fiki.local`) + `signInWithPassword`.
    Konto tworzy się ręcznie w Supabase z „Auto Confirm User”.
  - Prawdziwy mail bez hasła → magic link (`signInWithOtp`, `shouldCreateUser: false`);
    wymaga ustawienia Site URL w Supabase na adres strony.
- **Zakładka Fiki**: chipy statusów z licznikami, wyszukiwanie tekstowe, min. ocena (domyślnie ≥4),
  kategoria AI, sortowanie, „tylko ukończone”, „pokaż nieocenione”. Karta: ocena, tytuł (link do AO3),
  meta, uzasadnienie AI, kategorie, rozwijany opis i tagi (ostrzeżenia na czerwono), przyciski statusu
  (ponowne kliknięcie cofa do `new`). Ładuje do 2000 fików, filtruje po stronie klienta.
- **Zakładka Wyszukiwania**: wklejenie linku z AO3 → `parseAo3Url()` zamienia go na `params`
  (round-trip przetestowany 1:1); formularz każdego wyszukiwania; „Podgląd na AO3”; „Zacznij od strony 1”
  (`last_page = 0`); usuwanie; stan ostatniego przebiegu i błąd.
  Panel „Szukaj teraz”: przycisk „Przeszukaj wszystkie aktywne” (insert `search_id = null`), przy każdym
  wyszukiwaniu „Szukaj teraz” (używa **zapisanych** ustawień, nie przeładowuje formularza), stan komputera
  z `runner.last_seen_at` (> 15 min = „nie odpowiada”), 5 ostatnich próśb; dopóki coś czeka lub trwa,
  odświeżanie co 15 s (co 5 s, gdy coś trwa), po zakończeniu przeładowanie fików i wyszukiwań.
  Trwająca prośba ma animowany pasek postępu (`run_requests.progress`). Kliknięcie prośby rozwija szczegóły
  (`runDetails`): zakres, kto i kiedy zlecił, przy „czeka” przewidywany start (`last_seen_at` + 5 min) albo
  ostrzeżenie, że kolejka nie jest sprawdzana; przy „trwa” czas i bieżący krok; po końcu czas trwania i wynik.
  „Wyczyść kolejkę” usuwa wszystkie
  prośby poza `running` (polityka DELETE z 04).
- **Pobieranie fika**: na karcie linki EPUB / PDF → `https://archiveofourown.org/downloads/<id>/<id>.<format>`.
  AO3 ignoruje nazwę pliku i sam podaje tytuł (sprawdzone 2026-10-18). Pobiera przeglądarka czytelniczki,
  więc Cloudflare jej nie blokuje; scraper niczego nie pobiera (`/downloads/` jest też w `robots.txt`).
- **Zakładka Gust**: dwie listy tagów „Lubię” / „Nie lubię” (pole z podpowiedziami `<datalist>` z tagów fików
  w bazie, Enter dodaje, także własne tagi; × usuwa), pod spodem do 80 najczęstszych tagów z liczbą fików
  i przyciskami ♥ / ✕ (z filtrem tekstowym), na dole textarea → `profile.taste`. Tag może być tylko na jednej
  liście (porównanie bez wielkości liter). Jeden przycisk „Zapisz gust” zapisuje tagi i tekst razem.
  Synchronizacja z tekstem (`syncTasteText`): dodanie tagu dopisuje „- tag” na końcu sekcji `LUBI:` / `NIE LUBI:`
  (sekcja = linie do następnego nagłówka WIELKIMI LITERAMI z dwukropkiem; brak nagłówka → dopisany na końcu),
  usuwa szablonowe „- (…)”; usunięcie / przeniesienie tagu kasuje jego linię. Placeholder textarea = szablon
  z 02, żeby było widać format.
- **Bezpieczeństwo**: wszystkie dane z AO3 (tytuły, opisy, tagi) to treść użytkowników —
  **zawsze przez `esc()`** przed wstawieniem do HTML. `<meta name="robots" content="noindex">`.
- Styl: CSS w pliku, tokeny kolorów w `:root`, tryb ciemny przez `prefers-color-scheme`,
  układ mobilny poniżej 680 px. Fonty: Fraunces (nagłówki) + Inter.

---

## 6. Zmienne środowiskowe

| Zmienna | Gdzie | Wymagana | Domyślnie |
|---|---|---|---|
| `SUPABASE_URL` | .env / Secret | tak | |
| `SUPABASE_SERVICE_KEY` | .env / Secret | tak | `sb_secret_...` lub legacy `service_role` |
| `ANTHROPIC_API_KEY` | .env / Secret | tak (dla `rate`) | |
| `AO3_DELAY_SECONDS` | .env | nie | `6` |
| `AI_MODEL` | .env / Variable | nie | `claude-haiku-5-5` |
| `AI_BATCH_SIZE` | .env | nie | `10` |
| `AI_MAX_PER_RUN` | .env | nie | `100` |

`docs/config.js`: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` (publishable/anon — **nigdy secret**), `LOGIN_DOMAIN`.

---

## 7. Kroki implementacji i wdrożenia

Status na 2026-10-18. Przy każdym kroku: wykonaj, sprawdź kryterium, dopiero potem następny.

### Etap 1 — Supabase ✅ ZROBIONE
- [x] Projekt w regionie Frankfurt, `sql/01_schema.sql` uruchomione.
- [x] Konta użytkowników dodane ręcznie, rejestracja wyłączona.
- [x] Klucze zapisane (URL, publishable, secret).
- Do potwierdzenia: czy w `allowed_users` są te same maile co w Authentication → Users
  (prawdziwe czy `@fiki.local`).

### Etap 2 — migracja 02 ⏳ DO ZROBIENIA
- [ ] Uruchomić `sql/02_searches_profile.sql` w SQL Editor.
- Kryterium: `select id, name, params from searches;` zwraca „Dramione PL”;
  `select taste from profile;` zwraca szablon; tabela `search_state` nie istnieje.

### Etap 3 — kod lokalnie ⏳
- [ ] `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`.
- [ ] `python scraper/main.py parse tests/fixture_search.html`
  - Kryterium: „Fików: 20, wszystkich wyników: 75, jest następna strona: True”, 16 ✓ i 4 ✗.
- [ ] Skopiować `.env.example` → `.env`, uzupełnić klucze.
- [ ] `python scraper/main.py scrape`
  - Kryterium: log „strona N: 20 fików, X odrzuconych, Y nowych”; w Table Editor są wiersze w `works`;
    `searches.last_page` / `last_run_at` zaktualizowane, `last_error` puste.
  - Jeśli `Supabase ... 401`: zły klucz; z `sb_secret_` spróbować legacy `service_role`.
  - Jeśli `AO3Blocked`: AO3 odrzuca zapytania — zwiększyć `AO3_DELAY_SECONDS`, spróbować później.
- [ ] Uzupełnić gust (na razie w SQL Editor: `update profile set taste = '...' where id = 1;`).
- [ ] `python scraper/main.py rate`
  - Kryterium: linie „N/5 tytuł”; w `works` wypełnione `ai_score`, `ai_categories`, `ai_reason`.

### Etap 4 — GitHub + Actions ⏳
- [ ] Repo (`git init`, commit, push). Sprawdzić, że `.env` NIE jest w repo.
- [ ] Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`.
- [ ] Actions → „AO3 rate” → Run workflow (tylko ocena AI).
  - Kryterium: zielony przebieg.
  - Scrapowanie robi wyłącznie komputer: Harmonogram zadań → `main.py queue` co 5 minut (Etap 5b),
    tylko na prośby ze strony.

### Etap 5b — „Szukaj teraz” ze strony ⏳
- [ ] Uruchomić `sql/03_run_requests.sql` w SQL Editor.
- [ ] `python scraper/main.py queue` ręcznie → „Kolejka pusta.” (albo wykonanie czekających próśb); w `runner` jest `last_seen_at`.
- [ ] Harmonogram zadań → Utwórz zadanie: wyzwalacz codziennie, powtarzaj co 5 min przez 1 dzień;
  akcja `<repo>\.venv\Scripts\python.exe` z argumentem `scraper\main.py queue`, „Rozpocznij w” = `<repo>`;
  ustawienia: „uruchom jak najszybciej po pominięciu”, „nie uruchamiaj nowego wystąpienia”;
  „uruchom niezależnie od tego, czy użytkownik jest zalogowany” (żeby nie migało okno konsoli).
- Kryterium: na stronie „Komputer sprawdził kolejkę X min temu”; „Szukaj teraz” → w ciągu ~5 min
  status `trwa`, potem `gotowe` z liczbą nowych fików; drugie kliknięcie w trakcie → „To już czeka w kolejce”.

### Etap 5 — strona ⏳
- [ ] Uzupełnić `docs/config.js` (URL + publishable key), commit.
- [ ] Settings → Pages → Deploy from a branch → `main` → `/docs`.
- [ ] Supabase → Authentication → URL Configuration → Site URL = adres strony (dla magic linka).
- Kryterium: niezalogowany widzi tylko formularz; po zalogowaniu widać fiki; zmiana statusu działa
  i jest widoczna na drugim urządzeniu; dodanie wyszukiwania z linku AO3 tworzy wiersz w `searches`.
- Test bezpieczeństwa: w konsoli przeglądarki bez logowania
  `sb.from('works').select('*')` → pusta lista; po zalogowaniu
  `sb.from('works').update({ai_score: 1}).eq('work_id', X)` → błąd uprawnień.

### Etap 6 — dopracowanie gustu
- [ ] Żona uzupełnia zakładkę Gust; przeliczenie starych ocen: `update works set ai_score = null;`
  (następny przebieg oceni maks. 100).
- [ ] Po tygodniu ocenić trafność; ewentualnie `AI_MODEL=claude-sonnet-5-5`.

---

## 8. Testowanie

- **Parser**: `python scraper/main.py parse tests/fixture_search.html`. Przy zmianie selektorów
  zapisz nową stronę AO3 jako fixture (Ctrl+S w przeglądarce) i porównaj wynik.
- **Przebieg bez sieci**: podmień `main.AO3Client` na atrapę zwracającą fixture (dla `page == N`
  usuń link `li.next`), `main.get_db` na atrapę z dict-em, a `rate.anthropic.Anthropic` na obiekt,
  którego `messages.create()` zwraca `SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={...})])`.
  Sprawdzane zachowania: start od `last_page + 1`, `last_page = 0` po ostatniej stronie,
  0 nowych przy powtórce, jednolite klucze w każdej paczce upsertu, przycięcie `score` do 1–5.
- **Strona**: podmień import supabase-js na moduł-atrapę z danymi z fixture, otwórz przez
  `python -m http.server` i sprawdź na szerokości 1200 px i 390 px, w trybie jasnym i ciemnym.
- **Nie** odpalaj testów na żywym AO3 w pętli — pojedyncze ręczne przebiegi.

---

## 9. Zasady dla Claude Code

1. **Sekrety**: nigdy nie commituj `.env`; nigdy nie wpisuj klucza secret/service_role do `docs/`
   ani do kodu. `docs/config.js` zawiera tylko klucz publishable.
2. **AO3**: odstęp ≥ 5 s, obsługa 429, jeden wątek, bez równoległych zapytań, bez logowania na konto AO3.
   AO3 to projekt non-profit — szanuj ich serwery.
3. **Schemat bazy**: zmiany tylko przez nowe pliki `sql/0N_*.sql`; pamiętaj o RLS i grantach kolumnowych.
   Po dodaniu migracji powiedz użytkownikowi, żeby ją uruchomił w SQL Editor.
4. **Scraper nie nadpisuje** `status` ani `ai_*` — nie dodawaj tych kolumn do danych upsertu.
5. **Strona**: jeden plik, bez frameworków i builda; każde pole z AO3 przez `esc()`;
   teksty interfejsu po polsku.
6. **Zależności**: trzymaj minimum (`requests`, `beautifulsoup4`, `anthropic`, `playwright` — tylko do AO3,
   patrz 5.1). Nowa paczka = uzasadnienie.
7. **Windows**: ścieżki i komendy w instrukcjach podawaj w wersji dla PowerShell (`.venv\Scripts\activate`).
8. **Koszty AI**: nie usuwaj limitu `AI_MAX_PER_RUN`; zmiany promptu testuj na kilku fikach.
9. **Współpraca**: użytkownik chce przechodzić kroki razem — przy wdrożeniu (Supabase, GitHub, Pages)
   podawaj instrukcje krok po kroku i czekaj na potwierdzenie, zamiast zakładać, że coś zostało zrobione.

---

## 10. Problemy i rozwiązania

| Objaw | Przyczyna | Rozwiązanie |
|---|---|---|
| `Supabase ... 401 / Invalid API key` | zły klucz albo nowy klucz z nagłówkiem Bearer | sprawdź `.env`; użyj legacy `service_role` |
| `Supabase ... 400 All object keys must match` | różne klucze w jednej paczce upsertu | rozdziel paczki (patrz 5.2) |
| `AO3 zablokował zapytanie (HTTP 403/503)` albo 525 | Cloudflare odrzuca klienta | upewnij się, że idzie przez Chrome z oknem (`AO3Client`); większy odstęp |
| `Cloudflare nie przepuścił przeglądarki (captcha?)` | wyzwanie nie przeszło samo | usuń `--window-position` w `AO3Client._start`, odpal `scrape`, przejdź captchę w oknie; profil `.ao3-profile/` ją zapamięta |
| Playwright: `Chromium distribution 'chrome' is not found` | brak Chrome'a | zainstaluj Google Chrome albo `playwright install chrome` |
| Na stronie pusta lista po zalogowaniu | mail z sesji nie ma w `allowed_users` | `insert into allowed_users values ('...')` |
| Magic link przenosi na localhost | brak Site URL | Authentication → URL Configuration |
| Projekt Supabase „paused” | 7 dni bez aktywności (np. padły Actions) | Dashboard → Resume project |
| Parser zwraca 0 fików | AO3 zmienił HTML albo zwrócił stronę błędu | zapisz stronę, porównaj selektory z tabelą w 5.1 |
| Krzaki zamiast polskich znaków w konsoli | kodowanie Windows | `main.py` już robi `reconfigure`; ewentualnie `chcp 65001` |

---

## 11. Pomysły na później (nie implementować bez prośby)

- Własna ocena czytelniczki (1–5) po przeczytaniu → lepsze przykłady dla AI.
- Tryb przyrostowy: sortowanie `revised_at desc` i zatrzymanie po trafieniu na znane ID
  (dziś przy sortowaniu po słowach nowe fiki wpadają w środek listy; deduplikacja to obsługuje,
  ale przyrostowy tryb byłby szybszy przy dużych wynikach).
- Wykonywanie kolejki `run_requests` także przez GitHub Actions (Edge Function z tokenem GitHuba po stronie
  serwera wyzwala `workflow_dispatch`, workflow odpala `main.py queue`; nigdy token w przeglądarce).
  Dziś kolejkę obsługuje tylko komputer z Harmonogramem zadań.
- Wysyłka EPUB na czytnik (np. Send to Kindle mailem) — dziś jest tylko link do pobrania na karcie.
- Powiadomienie (mail/Telegram) o nowych fikach z oceną 5.
