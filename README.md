# Półka z fikami — AO3 Fic Finder

Na żądanie (przycisk „Szukaj teraz” albo ręczne odpalenie) przeszukuje AO3 według zapisanych wyszukiwań, odrzuca niepasujące fiki,
ocenia nowe przez Claude'a (1–5) pod gust czytelniczki i pokazuje wszystko na prywatnej stronie.

```
Komputer (Harmonogram, co 5 min)     Supabase (baza + logowanie)          GitHub Pages
scraper/main.py queue ──────────────▶  works, searches, profile  ◀────────  docs/index.html
  ├─ pobiera strony AO3 przez Chrome (co 6 s)                              ├─ lista fików + statusy
  ├─ filtr wstępny + deduplikacja                                          ├─ edycja wyszukiwań
  └─ ocena AI nowych fików                                                 └─ edycja gustu
```

## Struktura

| Plik | Co robi |
|---|---|
| `sql/02_searches_profile.sql` | Druga migracja (po `01_schema.sql`): tabele wyszukiwań i gustu |
| `scraper/ao3.py` | Budowa URL-a, pobieranie z przerwami i obsługą 429, parsowanie, filtr wstępny |
| `scraper/db.py` | Zapis do Supabase (REST, bez dodatkowych bibliotek) |
| `scraper/rate.py` | Ocena paczek po 10 fików przez Claude API |
| `scraper/main.py` | Punkt wejścia: `scrape`, `rate`, `all`, `queue`, `parse plik.html` |
| `.github/workflows/scrape.yml` | Ręczne przeliczenie ocen AI (bez scrapowania) |
| `docs/index.html`, `docs/config.js` | Strona na GitHub Pages |
| `tests/fixture_search.html` | Zapisana strona wyników AO3 do testów parsera |

## Wdrożenie krok po kroku

### 1. Baza
W Supabase → SQL Editor uruchom `sql/02_searches_profile.sql` (`01_schema.sql` już masz).

### 2. Test lokalny
```
python -m venv .venv
.venv\Scripts\activate          (Windows)   |   source .venv/bin/activate   (Mac/Linux)
pip install -r requirements.txt

python scraper/main.py parse tests/fixture_search.html   # test parsera, bez sieci i bazy
```
Skopiuj `.env.example` jako `.env`, uzupełnij klucze i odpal:
```
python scraper/main.py scrape   # pobierze do 5 stron, zapisze fiki do bazy
python scraper/main.py rate     # oceni je przez Claude'a
```

### 3. GitHub
1. Załóż repo i wypchnij ten folder (`.env` jest w `.gitignore` — nie trafi do repo).
2. **Settings → Secrets and variables → Actions → New repository secret**, dodaj trzy:
   `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`.
3. **Actions → AO3 rate → Run workflow**, żeby sprawdzić ocenę AI z serwerów GitHuba.

### 4. Strona
1. Uzupełnij `docs/config.js`: Project URL i klucz **publishable/anon** (nie secret!).
2. **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`**.
3. W Supabase **Authentication → URL Configuration → Site URL** wpisz adres strony
   (`https://twoj-login.github.io/nazwa-repo/`) — potrzebne do logowania linkiem z maila.

### 5. „Szukaj teraz” ze strony
1. W Supabase → SQL Editor uruchom `sql/03_run_requests.sql`.
2. Harmonogram zadań Windows: co 5 minut `.venv\Scripts\python.exe scraper\main.py queue`
   (katalog startowy = folder repo, „nie uruchamiaj nowego wystąpienia”).
   Komenda wykonuje tylko prośby kliknięte na stronie — sama z siebie AO3 nie przeszukuje.

## Uwagi

- **AO3 i Cloudflare:** AO3 wpuszcza tylko prawdziwą przeglądarkę, więc scraper otwiera Twojego Chrome'a
  przez Playwright (okno poza ekranem, osobny profil w `.ao3-profile/`). Dlatego pobieranie działa tylko na
  komputerze z zalogowanym użytkownikiem, a GitHub Actions służą już tylko do ręcznego przeliczenia ocen AI.
  Zapytania idą co 6 s, przy 429 skrypt czeka.
- **Koszty AI:** maks. 100 fików na przebieg (`AI_MAX_PER_RUN`). Model zmienisz zmienną `AI_MODEL`
  (repo → Settings → Variables), np. na `claude-sonnet-5-5`.
- **Paginacja:** każde wyszukiwanie pamięta stronę. Po dojściu do końca wyników wraca na stronę 1,
  a znane fiki są pomijane (odświeżane są tylko ich statystyki).
- **Zmiana gustu** działa na nowe fiki. Żeby przeliczyć stare, w SQL Editor:
  `update works set ai_score = null;` — następny przebieg oceni je ponownie (max 100 na raz).
