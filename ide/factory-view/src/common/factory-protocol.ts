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

export interface RerunResult {
    ok: boolean;
    message: string;
}

// The discuss panel's O8 use #2 (bounded-LLM-into-fixed-schema): a plain-English
// request -> this fixed proposal shape, reviewed/edited by a human, then confirmed
// through `discussConfirm` — never the gate, never a second LLM call to extend it.
export interface DiscussProposal {
    taskText: string;
    editablePaths: string[];
    forbiddenAreas: string[];
    clarifyingQuestions: string[];
    /** true when the engine call failed/timed out/came back empty — the panel must
     * show "fill it in manually" rather than pretend a real proposal arrived. */
    fallback: boolean;
    /** raw stdout of the `discuss` CLI call, only set on fallback, for debugging. */
    raw?: string;
}

export interface DiscussConfirmResult {
    ok: boolean;
    message: string;
}

// The guide panel's O9 use (bounded-LLM-into-fixed-schema, the operating-advisor
// pattern — distinct from discuss's O8 use #2): a plain-English question about
// factory state -> this fixed {answer, suggestions, fallback} shape. Strictly
// read-only — a suggestion is a command string the human may copy, never
// something this panel (or anything behind it) executes.
export interface GuideSuggestion {
    command: string;
    why: string;
}

export interface GuideReply {
    answer: string;
    suggestions: GuideSuggestion[];
    /** true when the engine call failed/timed out/came back unparseable — the
     * panel must show the "guide unavailable" fallback rather than a real answer. */
    fallback: boolean;
}

export interface FactoryService {
    /** Read `<repoPath>/sembl.stack.yaml` + `<repoPath>/.sembl/runs/` and return the rendered state. */
    getState(repoPath: string): Promise<FactoryState>;

    /**
     * BLOCK-panel "re-run": spawn a fresh `sembl-stack loop <taskfile>` against the repo
     * (fire-and-forget — this RPC does not await the child). Thin wrapper per O1: no loop
     * logic here, only process spawn + taskfile resolution. See factory-service-impl.ts for
     * the taskfile/python resolution rules.
     */
    rerunTask(repoPath: string): Promise<RerunResult>;

    /**
     * Discuss panel — propose step: `sembl_stack.cli discuss <userText>` (O8 use #2),
     * a bounded, read-only LLM call that never touches the gate. Always resolves a
     * DiscussProposal, even on failure/timeout (fallback: true) — never rejects.
     */
    discussPropose(repoPath: string, userText: string, executor: string, model?: string): Promise<DiscussProposal>;

    /**
     * Discuss panel — confirm step: `sembl_stack.cli discuss-confirm`, purely
     * deterministic (no LLM), writes task.yaml + bounds.json through the same
     * tool-owned writer every other entry point uses.
     */
    discussConfirm(repoPath: string, proposal: DiscussProposal): Promise<DiscussConfirmResult>;

    /**
     * Guide panel — ask step: `sembl_stack.cli explain <question> --json` (O9), a
     * bounded, read-only LLM call that never writes anything and never touches the
     * gate. Always resolves a GuideReply, even on failure/timeout (fallback: true) —
     * never rejects.
     */
    guideAsk(repoPath: string, question: string, executor: string, model?: string): Promise<GuideReply>;
}
