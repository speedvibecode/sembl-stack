"use client";

import { createBrowserClient } from "@supabase/ssr";

import { getSupabaseEnv } from "@/lib/env";

type SupabaseBrowserClient = ReturnType<typeof createBrowserClient>;

let browserClient: SupabaseBrowserClient | null = null;

export function createSupabaseBrowserClient(): SupabaseBrowserClient | null {
  const env = getSupabaseEnv();

  if (!env) {
    return null;
  }

  browserClient ??= createBrowserClient(env.url, env.key);
  return browserClient;
}
