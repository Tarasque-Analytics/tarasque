import { createClient } from "@supabase/supabase-js";

const supabaseKey =
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabase = createClient(import.meta.env.VITE_SUPABASE_URL, supabaseKey);
