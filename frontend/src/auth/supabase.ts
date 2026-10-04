import { createClient } from '@supabase/supabase-js';

const env = (import.meta as ImportMeta & { env: Record<string, string | undefined> }).env;
const supabaseUrl = env.VITE_SUPABASE_URL?.trim();
const supabaseAnonKey = env.VITE_SUPABASE_ANON_KEY?.trim();

export const authProviderConfigured = Boolean(supabaseUrl && supabaseAnonKey);
export const accessSchemaReady = env.VITE_JQE_ACCESS_SCHEMA_READY === 'true';
export const authConfigured = authProviderConfigured && accessSchemaReady;
export const supabase = authProviderConfigured
  ? createClient(supabaseUrl!, supabaseAnonKey!, {
      auth: {
        persistSession: true,
        storage: window.sessionStorage,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;

export const weltradeReferralUrl = env.VITE_WELTRADE_REFERRAL_URL?.trim()
  || 'https://track.gowt.me/visit/?bta=44132&brand=weltrade';
