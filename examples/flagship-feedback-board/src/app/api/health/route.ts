import { getSupabaseEnv } from "@/lib/env";

export function GET() {
  return Response.json({
    ok: true,
    app: "flagship-feedback-board",
    supabaseConfigured: Boolean(getSupabaseEnv()),
  });
}
