-- =============================================================
-- AO3 Fic Finder — etap 6: pasek postępu przebiegu
-- Uruchom PO 05_taste_tags.sql (Supabase → SQL Editor → Run)
-- =============================================================

-- 0–100 %, ustawia scraper (klucz secret) w trakcie przebiegu; strona tylko czyta
alter table public.run_requests
  add column progress smallint check (progress between 0 and 100);
