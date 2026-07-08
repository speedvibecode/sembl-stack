// The wire contract between the Theia frontend widget and the backend service.
// Mirrors sembl_stack/drift.py's finding shape 1:1 — this is a thin renderer over
// that persisted state, per O1 (headless engine, thin surfaces). No new logic here.

export const DriftService = Symbol('DriftService');
export const DRIFT_SERVICE_PATH = '/services/sembl-drift';

export interface DriftFinding {
    kind?: string;
    message?: string;
    spec_node?: string;
    concept_type?: string;
    severity?: string;
}

export interface DriftPendingEntry {
    /** The stable `finding_key()` string, as persisted as a dict key in drift-state.json. */
    key: string;
    finding: DriftFinding;
    firstDetected?: string;
}

export type DriftResolveMode = 'update-spec' | 'update-code' | 'mark-exception';

export interface DriftService {
    /** Read `<repoPath>/.sembl/drift-state.json` and return every unacknowledged finding,
     * paired with its stable state key. */
    getPending(repoPath: string): Promise<DriftPendingEntry[]>;

    /** Track 5 item 4: resolve one pending drift finding via `sembl-stack drift-resolve`
     * (the headless CLI is the single source of truth for what each mode does — this is a
     * thin invoker, per O1). `reason` is required when `mode` is 'mark-exception'. */
    resolve(repoPath: string, key: string, mode: DriftResolveMode, reason?: string): Promise<{ ok: boolean; output: string }>;
}
