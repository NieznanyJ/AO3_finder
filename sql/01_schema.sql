-- =============================================================
-- AO3 Fic Finder — etap 1: schemat bazy + zabezpieczenia
-- Wklej całość w Supabase → SQL Editor → Run
-- =============================================================

-- -------------------------------------------------------------
-- 1. Fiki znalezione na AO3
-- -------------------------------------------------------------
create table public.works (
  work_id           bigint primary key,          -- ID z AO3 (gwarantuje brak duplikatów)
  url               text not null,
  title             text not null,
  authors           text[] not null default '{}',
  summary           text,
  language          text,

  -- tagi z AO3
  rating            text,                         -- General / Teen / Mature / Explicit
  warnings          text[] not null default '{}',
  categories        text[] not null default '{}', -- F/M, M/M, Gen...
  relationships     text[] not null default '{}',
  characters        text[] not null default '{}',
  freeform_tags     text[] not null default '{}',
  series            text,

  -- statystyki
  words             integer,
  chapters_current  integer,
  chapters_total    integer,                      -- null = "?" (nieznana liczba)
  complete          boolean,
  kudos             integer,
  hits              integer,
  comments          integer,
  bookmarks         integer,
  updated_on        date,                         -- data z blurba AO3

  -- ocena AI
  ai_score          smallint check (ai_score between 1 and 5),
  ai_categories     text[] not null default '{}',
  ai_reason         text,
  ai_rated_at       timestamptz,

  -- status ustawiany przez żonę na stronie
  status            text not null default 'new'
                    check (status in ('new', 'to_read', 'reading', 'read', 'skip')),
  status_changed_at timestamptz,

  -- techniczne
  found_at          timestamptz not null default now(),
  last_seen_at      timestamptz not null default now()
);

create index works_status_idx   on public.works (status);
create index works_score_idx    on public.works (ai_score desc nulls last);
create index works_unrated_idx  on public.works (work_id) where ai_score is null;

-- automatycznie ustaw datę zmiany statusu
create or replace function public.touch_status_changed()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.status is distinct from old.status then
    new.status_changed_at := now();
  end if;
  return new;
end;
$$;

create trigger works_status_changed
before update on public.works
for each row execute function public.touch_status_changed();

-- -------------------------------------------------------------
-- 2. Stan wyszukiwania (na której stronie jesteśmy)
-- -------------------------------------------------------------
create table public.search_state (
  search_key   text primary key,                  -- np. 'dramione_pl'
  query_url    text not null,
  last_page    integer not null default 0,
  total_pages  integer,
  last_run_at  timestamptz
);

-- -------------------------------------------------------------
-- 3. Lista osób, które mogą korzystać ze strony
-- -------------------------------------------------------------
create table public.allowed_users (
  email text primary key
);

-- >>> WPISZ TU PRAWDZIWE ADRESY <<<
insert into public.allowed_users (email) values
  ('mail.zony@example.com'),
  ('twoj.mail@example.com');

create or replace function public.is_allowed()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.allowed_users
    where email = (auth.jwt() ->> 'email')
  );
$$;

-- -------------------------------------------------------------
-- 4. Row Level Security
--    n8n używa klucza service_role, który omija RLS.
--    Strona używa klucza anon/publishable + logowania.
-- -------------------------------------------------------------
alter table public.works         enable row level security;
alter table public.search_state  enable row level security;
alter table public.allowed_users enable row level security;
-- search_state i allowed_users: brak polityk = brak dostępu ze strony

create policy "allowed users can read works"
  on public.works for select
  to authenticated
  using (public.is_allowed());

create policy "allowed users can update works"
  on public.works for update
  to authenticated
  using (public.is_allowed())
  with check (public.is_allowed());

-- strona może zmieniać WYŁĄCZNIE status (nie ocenę, nie tagi)
revoke all on public.works from anon, authenticated;
grant select on public.works to authenticated;
grant update (status) on public.works to authenticated;

revoke all on public.search_state  from anon, authenticated;
revoke all on public.allowed_users from anon, authenticated;
