import { injectable } from '@theia/core/shared/inversify';
import * as fs from 'fs';
import * as path from 'path';
import { spawnSync } from 'child_process';
import { DriftPendingEntry, DriftResolveMode, DriftService, SpecEdge, SpecGraphResult, SpecNode } from '../common/drift-protocol';

interface DriftStateFile {
    findings?: {
        [key: string]: {
            finding: DriftPendingEntry['finding'];
            first_detected?: string;
            acknowledged?: boolean;
            exception?: unknown;
        };
    };
}

// Dev-machine fallback only — tried last, after the target repo's own venv and this
// sembl-stack checkout's venv (found by walking up from __dirname, below). Keeps the
// resolution from being pinned to this machine as the *only* option.
// keep in sync with factory-view/src/node/factory-service-impl.ts
const KNOWN_DEV_SEMBL_STACK_VENV_PYTHON =
    'C:/Users/totla/Desktop/projects/sembl-stack/.venv/Scripts/python.exe';

/**
 * Resolve a python executable to invoke `sembl_stack.cli` with. Preference order: the
 * target repo's own venv (it may vendor its own sembl-stack install) > this sembl-stack
 * checkout's venv (walk up from this module's own location so it isn't hardcoded to one
 * machine) > a known dev-machine fallback > `python` on PATH. First that exists wins.
 * keep in sync with factory-view/src/node/factory-service-impl.ts
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

@injectable()
export class DriftServiceImpl implements DriftService {

    async getPending(repoPath: string): Promise<DriftPendingEntry[]> {
        const statePath = path.join(repoPath, '.sembl', 'drift-state.json');
        let data: DriftStateFile;
        try {
            data = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
        } catch {
            return [];
        }
        const entries: DriftPendingEntry[] = [];
        for (const [key, entry] of Object.entries(data.findings || {})) {
            if (!entry.acknowledged) {
                entries.push({ key, finding: entry.finding, firstDetected: entry.first_detected });
            }
        }
        return entries;
    }

    async resolve(repoPath: string, key: string, mode: DriftResolveMode, reason?: string): Promise<{ ok: boolean; output: string }> {
        if (mode === 'mark-exception' && !reason) {
            return { ok: false, output: 'reason required' };
        }

        const python = resolvePythonExecutable(repoPath);
        const statePath = path.join(repoPath, '.sembl', 'drift-state.json');
        const args = ['-m', 'sembl_stack.cli', 'drift-resolve', key, '--state', statePath];
        if (mode === 'update-spec') {
            args.push('--update-spec');
        } else if (mode === 'update-code') {
            args.push('--update-code');
        } else {
            args.push('--mark-exception', '--reason', reason!);
        }

        const proc = spawnSync(python, args, { cwd: repoPath, encoding: 'utf-8' });
        const output = [proc.stdout, proc.stderr].filter(Boolean).join('').trim();
        const ok = proc.status === 0;
        return { ok, output };
    }

    async getSpecGraph(repoPath: string): Promise<SpecGraphResult | undefined> {
        const runsDir = path.join(repoPath, '.sembl', 'runs');
        let runIds: string[];
        try {
            runIds = fs.readdirSync(runsDir, { withFileTypes: true })
                .filter(d => d.isDirectory())
                .map(d => d.name)
                .sort();
        } catch {
            return undefined;
        }
        for (let i = runIds.length - 1; i >= 0; i--) {
            const runId = runIds[i];
            const graphPath = path.join(runsDir, runId, 'specgraph.json');
            if (!fs.existsSync(graphPath)) { continue; }
            try {
                const raw = JSON.parse(fs.readFileSync(graphPath, 'utf-8'));
                const nodes: SpecNode[] = Array.isArray(raw.nodes) ? raw.nodes : [];
                const edges: SpecEdge[] = Array.isArray(raw.edges) ? raw.edges : [];
                return { runId, nodes, edges };
            } catch {
                continue;
            }
        }
        return undefined;
    }

    async getExceptedNodes(repoPath: string): Promise<string[]> {
        const statePath = path.join(repoPath, '.sembl', 'drift-state.json');
        let data: DriftStateFile;
        try {
            data = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
        } catch {
            return [];
        }
        const nodeIds: string[] = [];
        for (const entry of Object.values(data.findings || {})) {
            if (entry.acknowledged && entry.exception && entry.finding?.spec_node) {
                nodeIds.push(entry.finding.spec_node);
            }
        }
        return nodeIds;
    }
}
