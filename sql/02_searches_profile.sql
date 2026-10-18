-- =============================================================
-- AO3 Fic Finder — etap 2: wyszukiwania edytowalne ze strony + profil gustu
-- Uruchom PO 01_schema.sql (Supabase → SQL Editor → Run)
-- =============================================================

-- stara tabela stanu nie jest już potrzebna — stan trzymamy przy wyszukiwaniu
drop table if exists public.search_state;

-- -------------------------------------------------------------
-- 1. Zapisane wyszukiwania (edytowane na stronie)
-- -------------------------------------------------------------
create table public.searches (
  id                  bigint generated always as identity primary key,
  name                text not null,
  enabled             boolean not null default true,

  -- parametry wyszukiwarki AO3, np. {"query": "...", "language_id": "pl", "sort_column": "revised_at"}
  params              jsonb not null default '{}'::jsonb,

  -- filtr wstępny (bez AI)
  -- każda fraza musi wystąpić w JEDNYM tagu relacji, np. {draco, herm}
  relationship_must   text[] not null default '{}',
  -- jeśli którykolwiek tag zawiera taką frazę → pomijamy fika
  exclude_tags        text[] not null default '{}',

  -- paginacja
  max_pages_per_run   integer not null default 5 check (max_pages_per_run between 1 and 50),
  last_page           integer not null default 0,
  total_found         integer,
  last_run_at         timestamptz,
  last_error          text,

  created_at          timestamptz not null default now()
);

-- przykładowe wyszukiwanie — to, od którego zaczęliśmy
insert into public.searches (name, params, relationship_must)
values (
  'Dramione PL',
  '{"query": "draco malfoy/Hermiona Granger", "language_id": "pl", "sort_column": "word_count", "sort_direction": "desc"}',
  '{draco,herm}'
);

-- powiązanie fika z wyszukiwaniem, które go znalazło
alter table public.works
  add column search_id bigint references public.searches(id) on delete set null;

-- -------------------------------------------------------------
-- 2. Profil gustu (jeden wiersz, edytowany na stronie, czytany przez AI)
-- -------------------------------------------------------------
create table public.profile (
  id          integer primary key default 1 check (id = 1),
  taste       text not null default '',
  updated_at  timestamptz not null default now()
);

insert into public.profile (taste) values (
'LUBI:
- slow burn, enemies to lovers
- humor i przekomarzanie się
- ukończone fiki

NIE LUBI:
- (uzupełnij)

INNE:
- (np. preferowana długość, rating)'
);

-- -------------------------------------------------------------
-- 3. Uprawnienia: strona (zalogowana żona) może zarządzać wyszukiwaniami i gustem
-- -------------------------------------------------------------
alter table public.searches enable row level security;
alter table public.profile  enable row level security;

create policy "allowed users manage searches"
  on public.searches for all
  to authenticated
  using (public.is_allowed())
  with check (public.is_allowed());

create policy "allowed users read profile"
  on public.profile for select
  to authenticated
  using (public.is_allowed());

create policy "allowed users update profile"
  on public.profile for update
  to authenticated
  using (public.is_allowed())
  with check (public.is_allowed());

revoke all on public.searches from anon, authenticated;
grant select, insert, delete on public.searches to authenticated;
-- strona zmienia ustawienia wyszukiwania i może zresetować stronę (last_page),
-- ale nie pola techniczne wypełniane przez scraper
grant update (name, enabled, params, relationship_must, exclude_tags, max_pages_per_run, last_page)
  on public.searches to authenticated;

revoke all on public.profile from anon, authenticated;
grant select on public.profile to authenticated;
grant update (taste) on public.profile to authenticated;

create or replace function public.touch_profile()
returns trigger language plpgsql set search_path = '' as $$
begin new.updated_at := now(); return new; end; $$;

create trigger profile_touch before update on public.profile
for each row execute function public.touch_profile();
