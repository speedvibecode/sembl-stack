import { injectable } from '@theia/core/shared/inversify';
import * as fs from 'fs';
import * as path from 'path';
import { FactoryService, FactoryState, PipelineLayer, RunSummary } from '../common/factory-protocol';

// Mirrors sembl_stack/config.py DEFAULTS["layers"] — the resolution rule is
// defaults < sembl.stack.yaml, same as the CLI. Keep this table in sync with config.py.
const DEFAULT_LAYERS: { [key: string]: string } = {
    context: 'none',
    spec: 'sembl',
    execute: 'mock',
    sandbox: 'worktree',
    verify: 'sembl',
    review: 'mock',
    codegraph: 'cbm',
    merge: 'git',
    deploy: 'vercel',
    postdeploy: 'http'
};

// Display order + stage numbers from the L0-L8 map (PROCESS-ACTION-PLAN.md §3).
const LAYER_ORDER: Array<{ key: string; stage: string }> = [
    { key: 'context', stage: 'L1' },
    { key: 'spec', stage: 'L2' },
    { key: 'execute', stage: 'L3' },
    { key: 'sandbox', stage: 'L4' },
    { key: 'verify', stage: 'L5' },
    { key: 'review', stage: 'L5.5' },
    { key: 'merge', stage: 'L6.5' },
    { key: 'deploy', stage: 'L7' },
    { key: 'postdeploy', stage: 'L8' }
];

/** '/c:/Users/x' (Theia URI path form) → 'c:/Users/x'; everything else untouched. */
function normalizeRepoPath(p: string): string {
    const m = /^\/([a-zA-Z]:\/.*)$/.exec(p.replace(/\\/g, '/'));
    return m ? m[1] : p;
}

/**
 * Minimal reader for the `layers:` block of sembl.stack.yaml. The file is our own
 * flat two-level format (top-level key, indented `k: v` scalars, `#` comments) —
 * parsed line-wise here to avoid pulling a YAML dependency into the extension.
 */
function readConfiguredLayers(configPath: string): { [key: string]: string } {
    const out: { [key: string]: string } = {};
    let text: string;
    try {
        text = fs.readFileSync(configPath, 'utf-8');
    } catch {
        return out;
    }
    let inLayers = false;
    for (const rawLine of text.split(/\r?\n/)) {
        const noComment = rawLine.replace(/#.*$/, '');
        if (!noComment.trim()) { continue; }
        const topLevel = !/^\s/.test(noComment);
        if (topLevel) {
            inLayers = /^layers\s*:/.test(noComment.trim());
            continue;
        }
        if (!inLayers) { continue; }
        const m = /^\s+([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$/.exec(noComment);
        if (m) {
            out[m[1]] = m[2].replace(/^["']|["']$/g, '');
        }
    }
    return out;
}

function readJson(file: string): any | undefined {
    try {
        return JSON.parse(fs.readFileSync(file, 'utf-8'));
    } catch {
        return undefined;
    }
}

// A run with no verdict.json yet is presumed still executing for this long after it
// started, in case the manifest's own "started" status is ever missing/stale (defense in
// depth — the primary signal is manifest.status, per sembl_stack/store.py new_run/set_status).
const RUNNING_FALLBACK_WINDOW_MS = 30 * 60 * 1000;

/**
 * The registry layer key of the stage currently in progress, read from
 * `.sembl/runs/<id>/events.jsonl` (sembl_stack/store.py Run.append_event): the last "start"
 * event whose stage has no later matching "done"/"failed". loop.py emits stages strictly
 * sequentially (never two open at once), so tracking a single open stage is exact. Returns
 * undefined when the file is missing/empty/unparseable or every started stage has finished.
 */
function currentStageFromEvents(runDir: string): string | undefined {
    let text: string;
    try {
        text = fs.readFileSync(path.join(runDir, 'events.jsonl'), 'utf-8');
    } catch {
        return undefined;
    }
    let openStage: string | undefined;
    for (const line of text.split(/\r?\n/)) {
        if (!line.trim()) { continue; }
        let evt: { stage?: string; status?: string };
        try {
            evt = JSON.parse(line);
        } catch {
            continue;
        }
        if (!evt.stage || !evt.status) { continue; }
        if (evt.status === 'start') {
            openStage = evt.stage;
        } else if ((evt.status === 'done' || evt.status === 'failed') && evt.stage === openStage) {
            openStage = undefined;
        }
    }
    return openStage;
}

@injectable()
export class FactoryServiceImpl implements FactoryService {

    async getState(repoPath: string): Promise<FactoryState> {
        const repo = normalizeRepoPath(repoPath);
        const configPath = path.join(repo, 'sembl.stack.yaml');
        const configured = readConfiguredLayers(configPath);

        const layers: PipelineLayer[] = LAYER_ORDER.map(({ key, stage }) => ({
            key,
            stage,
            adapter: configured[key] ?? DEFAULT_LAYERS[key],
            fromConfig: key in configured
        }));

        const runsDir = path.join(repo, '.sembl', 'runs');
        const runs: RunSummary[] = [];
        let runIds: string[] = [];
        try {
            runIds = fs.readdirSync(runsDir)
                .filter(name => fs.statSync(path.join(runsDir, name)).isDirectory())
                .sort()
                .reverse();   // run ids are timestamp-prefixed → lexicographic desc = newest first
        } catch {
            runIds = [];
        }
        for (const id of runIds) {
            const dir = path.join(runsDir, id);
            const manifest = readJson(path.join(dir, 'run.json')) || {};
            const verdictPath = path.join(dir, 'verdict.json');
            const hasVerdict = fs.existsSync(verdictPath);
            const verdict = hasVerdict ? readJson(verdictPath) : undefined;
            const createdMs = typeof manifest.created === 'number' ? manifest.created * 1000 : undefined;
            const withinFallbackWindow = createdMs !== undefined
                && (Date.now() - createdMs) < RUNNING_FALLBACK_WINDOW_MS;
            const running = manifest.status === 'started' || (!hasVerdict && withinFallbackWindow);
            runs.push({
                id,
                status: manifest.status,
                created: manifest.created,
                task: manifest.task?.text,
                verdictStatus: verdict?.status,
                reasons: verdict?.reasons,
                attempts: Array.isArray(manifest.attempts_log) ? manifest.attempts_log.length : undefined,
                running,
                currentStage: running ? currentStageFromEvents(dir) : undefined
            });
        }

        return {
            configPath: fs.existsSync(configPath) ? configPath : undefined,
            layers,
            runs
        };
    }
}
