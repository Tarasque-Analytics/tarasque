import { createClient } from '@supabase/supabase-js';

// Get environment variables from both client (import.meta.env) and server (process.env)
const getEnvVar = (clientVar: string | undefined, serverVar: string | undefined): string => {
    return clientVar || serverVar || '';
};

const supabaseUrl = getEnvVar(
    import.meta.env?.VITE_SUPABASE_URL,
    typeof process !== 'undefined' ? process.env.VITE_SUPABASE_URL : undefined
);

const supabaseKey = getEnvVar(
    import.meta.env?.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env?.VITE_SUPABASE_ANON_KEY,
    typeof process !== 'undefined' ? (process.env.VITE_SUPABASE_PUBLISHABLE_KEY || process.env.VITE_SUPABASE_ANON_KEY) : undefined
);

if (!supabaseUrl || !supabaseKey) {
    // Fail fast: createClient('', '') succeeds but defers an opaque error to the first auth
    // call. Surface the misconfiguration at startup instead.
    throw new Error(
        'Supabase credentials are missing. Set VITE_SUPABASE_URL and ' +
        'VITE_SUPABASE_PUBLISHABLE_KEY (or VITE_SUPABASE_ANON_KEY). For Docker builds these ' +
        'must be passed as build args so Vite can embed them at build time.'
    );
}

export const supabase = createClient(supabaseUrl, supabaseKey);