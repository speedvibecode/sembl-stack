# Flagship feedback board

This is the depth-1 Sembl Stack target from `docs/BUILD-PLAN.md`: a small
Next.js app with Supabase auth, database reads, database writes, list views,
and a deterministic health endpoint for post-deploy verification.

## Local app

```bash
cd examples/flagship-feedback-board
npm install
cp .env.example .env.local
npm run dev
```

The page renders a local preview data set when Supabase environment variables
are absent. Real auth and writes require:

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`

## Supabase

Apply the migration in `supabase/migrations/202606200001_feedback_board.sql`.
It creates `public.feedback_items`, enables RLS, grants Data API access to the
authenticated role, and restricts reads/writes to the signed-in owner.

The Supabase CLI config lives in `supabase/config.toml`. For a remote project:

```bash
npm run supabase:link
npm run supabase:push
```

Use publishable browser keys only. This app does not need a service-role key.

## Deploy spine

The deploy path is local-creds-first: `.env.local` and `.vercel/project.json`
stay local and ignored, while scripts fail closed when required state is absent.

```bash
npm run deploy:check
npm run deploy:preview
npm run postdeploy -- https://your-deployment.vercel.app
```

`deploy:check` verifies:

- Vercel CLI is available
- Supabase CLI is available through `npx supabase`
- `.vercel/project.json` exists
- `.env.local` or process env provides `NEXT_PUBLIC_SUPABASE_URL`
- `.env.local` or process env provides `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
  or legacy `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- no service-role style key is present in `.env.local`

`postdeploy` calls `/api/health` and requires `supabaseConfigured: true` unless
`--allow-unconfigured` is passed for local dry runs.

## Sembl Stack entrypoints

From this directory:

```bash
sembl-stack specgraph --task task.yaml --out specgraph.json
sembl-stack reconcile --specgraph specgraph.json --codegraph codegraph.json --out reconcile.json
sembl-stack deploy --verdict verdict.json --repo . --out delivery.json
sembl-stack postdeploy --delivery delivery.json --health-path /api/health --out postdeploy.json
```

For the full loop from the repo root, use:

```bash
sembl-stack loop examples/flagship-feedback-board/task.yaml
```
