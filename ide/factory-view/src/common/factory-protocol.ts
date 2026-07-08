// The wire contract between the factory panel and its backend reader.
// Everything here mirrors what sembl_stack already persists (sembl.stack.yaml,
// .sembl/runs/<id>/run.json + verdict.json) — a thin renderer over the run store,
// per O1. No new logic, no writes.

export const FactoryService = Symbol('FactoryService');
export const FACTORY_SERVICE_PATH = '/services/sembl-factory';

export interface PipelineLayer {
    /** registry layer key: context | spec | execute | sandbox | verify | review | codegraph | merge | deploy | postdeploy */
    key: string;
    /** stage number label from the L0-L8 map, e.g. "L3" */
    stage: string;
    /** configured adapter name (from sembl.stack.yaml, or the documented default) */
    adapter: string;
    /** true when the value came from the repo's sembl.stack.yaml, false when it's the default */
    fromConfig: boolean;
}

export interface RunSummary {
    id: string;
    /** manifest status: started | failed | PASS | WARN | BLOCK */
    status?: string;
    created?: number;
    task?: string;
    verdictStatus?: string;
    reasons?: string[];
    attempts?: number;
    /** true while the run is still executing (design step 2: live-run stage lighting) —
     * manifest status is "started", or (fallback) no verdict.json yet and started recently. */
    running?: boolean;
    /** the registry layer key (context|spec|execute|sandbox|verify|review|merge|deploy|
     * postdeploy) of the stage currently in progress, from events.jsonl — only set when `running`. */
    currentStage?: string;
}

export interface FactoryState {
    /** absolute path of the sembl.stack.yaml that was read, if one exists */
    configPath?: string;
    layers: PipelineLayer[];
    /** newest first */
    runs: RunSummary[];
}

export interface FactoryService {
    /** Read `<repoPath>/sembl.stack.yaml` + `<repoPath>/.sembl/runs/` and return the rendered state. */
    getState(repoPath: string): Promise<FactoryState>;
}
