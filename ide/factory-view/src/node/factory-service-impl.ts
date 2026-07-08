import { injectable } from '@theia/core/shared/inversify';
import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';
import {
    DiscussConfirmResult, DiscussProposal, FactoryService, FactoryState, PipelineLayer,
    RerunResult, RunSummary
} from '../common/factory-protocol';

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

// Dev-machine fallback only — tried last, after the target repo's own venv and this
// sembl-stack checkout's venv (found by walking up from __dirname, below). Keeps the
// resolution from being pinned to this machine as the *only* option.
const KNOWN_DEV_SEMBL_STACK_VENV_PYTHON =
    'C:/Users/totla/Desktop/projects/sembl-stack/.venv/Scripts/python.exe';

/**
 * Resolve a python executable to invoke `sembl_stack.cli` with, for the BLOCK-panel
 * "re-run" action. Preference order: the target repo's own venv (it may vendor its own
 * sembl-stack install) > this sembl-stack checkout's venv (walk up from this module's own
 * location so it isn't hardcoded to one machine) > a known dev-machine fallback > `python`
 * on PATH. First that exists wins.
 */
function resolvePythonExecutable(repoPath: string): string {
    const repoVenv = path.join(repoPath, '.venv', 'Scripts', 'python.exe');
    if (fs.existsSync(repoVenv)) {
        return repoVenv;
    }
    let dir = __dirname;
    for (let i = 0; i < 12; i++) {
        const candidate = path.join(dir, '.venv', 'Scripts', 'python.exe');
        if (fs.existsSync(candidate) && fs.existsSync(path.join(dir, 'sembl_stack'))) {
            return candidate;
        }
        const parent = path.dirname(dir);
        if (parent === dir) { break; }
        dir = parent;
    }
    if (fs.existsSync(KNOWN_DEV_SEMBL_STACK_VENV_PYTHON)) {
        return KNOWN_DEV_SEMBL_STACK_VENV_PYTHON;
    }
    return 'python';
}

/**
 * Resolve the taskfile for a re-run of `<repoPath>`. `run.json` (sembl_stack/store.py
 * RunStore.new_run) only ever records task.text/task.repo, never the file the task was
 * loaded from — there is nothing to read back per-run. The one convention every task file
 * actually follows is a `task.yaml` at the repo root; use it if present, else refuse
 * rather than guess at a path.
 */
function resolveTaskFile(repoPath: string): string | undefined {
    const candidate = path.join(repoPath, 'task.yaml');
    return fs.existsSync(candidate) ? candidate : undefined;
}

const DISCUSS_FALLBACK: Omit<DiscussProposal, 'raw'> = {
    taskText: '', editablePaths: [], forbiddenAreas: [], clarifyingQuestions: [], fallback: true
};

/**
 * `sembl_stack.cli discuss` prints `json.dumps(proposal, indent=2)` as the FIRST thing
 * on stdout, followed by either a "wrote ..." line (--yes) or a "(review/edit...)" note —
 * never JSON-only. Extract the first balanced {...} object rather than assuming the
 * whole stream parses, so those trailing lines don't break the parse.
 */
function firstBalancedJsonObject(text: string): string | undefined {
    const start = text.indexOf('{');
    if (start === -1) { return undefined; }
    let depth = 0;
    for (let i = start; i < text.length; i++) {
        const c = text[i];
        if (c === '{') { depth++; }
        else if (c === '}') {
            depth--;
            if (depth === 0) { return text.slice(start, i + 1); }
        }
    }
    return undefined;
}

/** snake_case (engine schema) -> camelCase (protocol) DiscussProposal, or undefined if
 * the parsed object isn't shaped like a proposal at all. */
function toDiscussProposal(data: any): Omit<DiscussProposal, 'fallback' | 'raw'> | undefined {
    if (!data || typeof data !== 'object') { return undefined; }
    const asStrArr = (v: any): string[] => Array.isArray(v) ? v.map(x => String(x)) : [];
    return {
        taskText: typeof data.task_text === 'string' ? data.task_text : '',
        editablePaths: asStrArr(data.editable_paths),
        forbiddenAreas: asStrArr(data.forbidden_areas),
        clarifyingQuestions: asStrArr(data.clarifying_questions)
    };
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

    async rerunTask(repoPath: string): Promise<RerunResult> {
        const repo = normalizeRepoPath(repoPath);
        const taskFile = resolveTaskFile(repo);
        if (!taskFile) {
            return {
                ok: false,
                message: `no taskfile to re-run — expected ${path.join(repo, 'task.yaml')}`
            };
        }

        const python = resolvePythonExecutable(repo);
        const logPath = path.join(repo, '.sembl', 'ide-rerun.log');
        let logFd: number | undefined;
        try {
            fs.mkdirSync(path.dirname(logPath), { recursive: true });
            logFd = fs.openSync(logPath, 'a');
        } catch {
            // .sembl not creatable (not a sembl repo, or a permissions issue) — spawn still
            // proceeds with stdio ignored below; the child's own error, if any, is lost, but
            // that's no worse than not spawning at all.
        }

        try {
            // Fire-and-forget by design (per the spec): this RPC must not block on the
            // child. detached + unref lets the loop outlive this backend request/response.
            const child = spawn(python, ['-m', 'sembl_stack.cli', 'loop', taskFile], {
                cwd: repo,
                detached: true,
                stdio: ['ignore', logFd ?? 'ignore', logFd ?? 'ignore']
            });
            child.unref();
        } catch (e) {
            return { ok: false, message: `failed to spawn re-run: ${e}` };
        }

        return {
            ok: true,
            message: `re-run spawned: ${python} -m sembl_stack.cli loop ${taskFile}`
                + (logFd !== undefined ? ` (log: ${logPath})` : '')
        };
    }

    async discussPropose(repoPath: string, userText: string, executor: string, model?: string): Promise<DiscussProposal> {
        const repo = normalizeRepoPath(repoPath);
        const python = resolvePythonExecutable(repo);
        const args = ['-m', 'sembl_stack.cli', 'discuss', userText, '--repo', repo, '--executor', executor];
        if (model) { args.push('--model', model); }

        let stdout = '';
        let stderr = '';
        let settled = false;
        return new Promise<DiscussProposal>(resolve => {
            const finish = (proposal: DiscussProposal) => {
                if (settled) { return; }
                settled = true;
                resolve(proposal);
            };
            let child;
            try {
                // async spawn — NOT spawnSync: the LLM call this shells out to can take
                // tens of seconds, and spawnSync would block the whole backend process.
                child = spawn(python, args, { cwd: repo, stdio: ['ignore', 'pipe', 'pipe'] });
            } catch (e) {
                finish({ ...DISCUSS_FALLBACK, raw: String(e) });
                return;
            }
            const timer = setTimeout(() => {
                try { child.kill(); } catch { /* already dead */ }
                finish({ ...DISCUSS_FALLBACK, raw: stdout || stderr });
            }, 120000);
            child.stdout?.on('data', d => { stdout += d.toString(); });
            child.stderr?.on('data', d => { stderr += d.toString(); });
            child.on('error', e => {
                clearTimeout(timer);
                finish({ ...DISCUSS_FALLBACK, raw: String(e) });
            });
            child.on('close', code => {
                clearTimeout(timer);
                if (code !== 0) {
                    finish({ ...DISCUSS_FALLBACK, raw: stderr || stdout });
                    return;
                }
                const jsonText = firstBalancedJsonObject(stdout);
                let parsed: any;
                try {
                    parsed = jsonText ? JSON.parse(jsonText) : undefined;
                } catch {
                    parsed = undefined;
                }
                const proposal = toDiscussProposal(parsed);
                if (!proposal || (!proposal.taskText && proposal.editablePaths.length === 0
                    && proposal.forbiddenAreas.length === 0 && proposal.clarifyingQuestions.length === 0)) {
                    finish({ ...DISCUSS_FALLBACK, raw: stdout });
                    return;
                }
                finish({ ...proposal, fallback: false });
            });
        });
    }

    async discussConfirm(repoPath: string, proposal: DiscussProposal): Promise<DiscussConfirmResult> {
        const repo = normalizeRepoPath(repoPath);
        const python = resolvePythonExecutable(repo);
        const args = ['-m', 'sembl_stack.cli', 'discuss-confirm', '--repo', repo];
        const payload = JSON.stringify({
            task_text: proposal.taskText,
            editable_paths: proposal.editablePaths,
            forbidden_areas: proposal.forbiddenAreas,
            clarifying_questions: proposal.clarifyingQuestions
        });

        let stdout = '';
        let stderr = '';
        let settled = false;
        return new Promise<DiscussConfirmResult>(resolve => {
            const finish = (result: DiscussConfirmResult) => {
                if (settled) { return; }
                settled = true;
                resolve(result);
            };
            let child;
            try {
                child = spawn(python, args, { cwd: repo, stdio: ['pipe', 'pipe', 'pipe'] });
            } catch (e) {
                finish({ ok: false, message: `failed to spawn discuss-confirm: ${e}` });
                return;
            }
            const timer = setTimeout(() => {
                try { child.kill(); } catch { /* already dead */ }
                finish({ ok: false, message: 'discuss-confirm timed out' });
            }, 30000);
            child.stdout?.on('data', d => { stdout += d.toString(); });
            child.stderr?.on('data', d => { stderr += d.toString(); });
            child.on('error', e => {
                clearTimeout(timer);
                finish({ ok: false, message: `discuss-confirm failed to run: ${e}` });
            });
            child.on('close', code => {
                clearTimeout(timer);
                if (code === 0) {
                    finish({ ok: true, message: stdout.trim() });
                } else {
                    finish({ ok: false, message: (stderr || stdout).trim() || `discuss-confirm exited ${code}` });
                }
            });
            child.stdin?.write(payload);
            child.stdin?.end();
        });
    }
}
