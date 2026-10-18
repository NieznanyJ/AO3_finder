-- =============================================================
-- AO3 Fic Finder — etap 4: czyszczenie kolejki ze strony
-- Uruchom PO 03_run_requests.sql (Supabase → SQL Editor → Run)
-- =============================================================

-- strona może usuwać prośby oczekujące i zakończone,
-- ale nie te w trakcie — tę obsługuje właśnie komputer
create policy "allowed users clear run requests"
  on public.run_requests for delete
  to authenticated
  using (public.is_allowed() and status <> 'running');

grant delete on public.run_requests to authenticated;
