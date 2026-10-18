// Te wartości SĄ publiczne — to normalne. Dane chroni logowanie + RLS w Supabase.
// NIGDY nie wpisuj tu klucza secret / service_role!
window.FICFINDER_CONFIG = {
    SUPABASE_URL: "https://agmmhvqddipwblcwpqhs.supabase.co",
    SUPABASE_PUBLISHABLE_KEY: "sb_publishable_uKVYOKxo4GluFJVH4gyyKQ_02FDLtig", // albo legacy "anon"
    // login bez "@" zostanie zamieniony na login@LOGIN_DOMAIN (np. kasia → kasia@fiki.local)
    LOGIN_DOMAIN: "fiki.local",
};
