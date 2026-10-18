-- =============================================================
-- AO3 Fic Finder — etap 5: tagi w profilu gustu
-- Uruchom PO 04_clear_run_requests.sql (Supabase → SQL Editor → Run)
-- =============================================================

-- tagi AO3 wybierane na stronie; AI dostaje je razem z opisem gustu (taste)
alter table public.profile
  add column liked_tags    text[] not null default '{}',
  add column disliked_tags text[] not null default '{}';

grant update (liked_tags, disliked_tags) on public.profile to authenticated;
