-- =============================================================
-- AO3 Fic Finder — etap 3: uruchamianie wyszukiwań ze strony
-- Uruchom PO 02_searches_profile.sql (Supabase → SQL Editor → Run)
--
-- Strona dopisuje prośbę do kolejki, a komputer z Harmonogramem zadań
-- (python scraper/main.py queue, co kilka minut) ją wykonuje.
-- =============================================================

-- -------------------------------------------------------------
-- 1. Kolejka próśb o przebieg
-- -------------------------------------------------------------
create table public.run_requests (
  id            bigint generated always as identity primary key,
  search_id     bigint references public.searches(id) on delete cascade,  -- null = wszystkie aktywne
  status        text not null default 'pending'
                check (status in ('pending', 'running', 'done', 'error')),
  message       text,                              -- wynik albo błąd, wpisuje scraper
  requested_by  text default (auth.jwt() ->> 'email'),
  requested_at  timestamptz not null default now(),
  started_at    timestamptz,
  finished_at   timestamptz
);

-- najwyżej jedna oczekująca/trwająca prośba na wyszukiwanie (i jedna „wszystkie”) —
-- wielokrotne klikanie nie zasypie AO3 zapytaniami
create unique index run_requests_one_open
  on public.run_requests (coalesce(search_id, 0))
  where status in ('pending', 'running');

create index run_requests_recent_idx on public.run_requests (requested_at desc);

-- -------------------------------------------------------------
-- 2. Stan komputera, który obsługuje kolejkę (jeden wiersz)
-- -------------------------------------------------------------
create table public.runner (
  id                 integer primary key default 1 check (id = 1),
  last_seen_at       timestamptz,                  -- ostatnie sprawdzenie kolejki
  last_daily_run_on  date                          -- dzień ostatniego automatycznego pełnego przebiegu
);

insert into public.runner default values;

-- -------------------------------------------------------------
-- 3. Uprawnienia: strona może dodać prośbę i czytać stan, nic więcej
-- -------------------------------------------------------------
alter table public.run_requests enable row level security;
alter table public.runner       enable row level security;

create policy "allowed users read run requests"
  on public.run_requests for select
  to authenticated
  using (public.is_allowed());

create policy "allowed users add run requests"
  on public.run_requests for insert
  to authenticated
  with check (public.is_allowed() and status = 'pending');

create policy "allowed users read runner"
  on public.runner for select
  to authenticated
  using (public.is_allowed());

revoke all on public.run_requests from anon, authenticated;
grant select on public.run_requests to authenticated;
grant insert (search_id) on public.run_requests to authenticated;

revoke all on public.runner from anon, authenticated;
grant select on public.runner to authenticated;
