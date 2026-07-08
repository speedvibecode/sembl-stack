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

// SpecGraph mirrors sembl_stack/specgraph.py's node/edge shape 1:1 (design step 5 —
// the graph view). Nodes carry a `type` (task/source/route/entity/data_rule/
// editable_path/forbidden_area); edges carry a `type` rel string (declares/mentions/
// allows/forbids observed in real specgraph.json output).
export interface SpecNode {
    id: string;
    type: string;
    name: string;
    [key: string]: unknown;
}

export interface SpecEdge {
    from: string;
    to: string;
    type: string;
}

export interface SpecGraphResult {
    runId: string;
    nodes: SpecNode[];
    edges: SpecEdge[];
}

export interface DriftService {
    /** Read `<repoPath>/.sembl/drift-state.json` and return every unacknowledged finding,
     * paired with its stable state key. */
    getPending(repoPath: string): Promise<DriftPendingEntry[]>;

    /** Track 5 item 4: resolve one pending drift finding via `sembl-stack drift-resolve`
     * (the headless CLI is the single source of truth for what each mode does — this is a
     * thin invoker, per O1). `reason` is required when `mode` is 'mark-exception'. */
    resolve(repoPath: string, key: string, mode: DriftResolveMode, reason?: string): Promise<{ ok: boolean; output: string }>;

    /** Design step 5: scan `<repoPath>/.sembl/runs/*` for the lexicographically-last run
     * dir containing a `specgraph.json` and return its parsed nodes/edges. Undefined when
     * no run has ever persisted a specgraph. No caching — always reads fresh off disk. */
    getSpecGraph(repoPath: string): Promise<SpecGraphResult | undefined>;

    /** Node ids that carry a recorded, acknowledged exception (drift.py's
     * `resolve_exception` — `acknowledged: true` plus an `exception` record) — rendered
     * as "exception" (dim amber) rather than "drift" (amber) in the graph view. */
    getExceptedNodes(repoPath: string): Promise<string[]>;
}
