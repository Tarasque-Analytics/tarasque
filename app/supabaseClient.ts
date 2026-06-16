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
    console.warn('Supabase environment variables are not set. Auth features may not work.');
}

export const supabase = createClient(supabaseUrl, supabaseKey)