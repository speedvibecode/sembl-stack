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

export interface DriftService {
    /** Read `<repoPath>/.sembl/drift-state.json` and return every unacknowledged finding. */
    getPending(repoPath: string): Promise<DriftFinding[]>;
}
