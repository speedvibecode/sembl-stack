import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { OpenerService, ReactWidget, open } from '@theia/core/lib/browser';
import { MessageService } from '@theia/core/lib/common/message-service';
import URI from '@theia/core/lib/common/uri';
import { URI as CodeUri } from '@theia/core/shared/vscode-uri';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { FileService } from '@theia/filesystem/lib/browser/file-service';
import { FactoryService, FactoryState, RunSummary } from '../common/factory-protocol';
import { SEMBL, ensureSemblDesign, gateChipStyle, runningTickStyle, tickColor, verdictTone } from './sembl-design';

export const FACTORY_VIEW_WIDGET_ID = 'sembl-factory-view';

// The factory cockpit panel (bottom area): the pipeline adapters (straight from
// sembl.stack.yaml) + the run-history ribbon over .sembl/runs/. Read-only in this
// slice — swapping still happens by editing the yaml (one click away in the
// editor); resolution/relaunch actions are later work. Styled per the locked
// design system (docs/DESIGN-sembl-ide.md).
@injectable()
export class FactoryViewWidget extends ReactWidget {

    static readonly ID = FACTORY_VIEW_WIDGET_ID;
    static readonly LABEL = 'Factory';

    @inject(FactoryService) protected readonly factoryService: FactoryService;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;
    @inject(OpenerService) protected readonly openerService: OpenerService;
    @inject(MessageService) protected readonly messageService: MessageService;
    @inject(FileService) protected readonly fileService: FileService;

    protected repoPath = '';
    protected state: FactoryState | undefined;
    protected selectedRun: RunSummary | undefined;
    protected loaded = false;
    protected pollTimer: ReturnType<typeof setTimeout> | undefined;
    // DESIGN-sembl-ide.md §2 "heavy override control" — unchecked by default, reset
    // whenever the selected run changes (see selectRun()). Never persisted.
    protected overrideChecked = false;
    protected rerunPending = false;

    // poll fast while a run is live, slow otherwise — see DESIGN-sembl-ide.md §5 step 2.
    protected static readonly POLL_LIVE_MS = 2000;
    protected static readonly POLL_IDLE_MS = 15000;

    @postConstruct()
    protected init(): void {
        this.id = FactoryViewWidget.ID;
        this.title.label = FactoryViewWidget.LABEL;
        this.title.caption = 'sembl-stack pipeline + run history';
        this.title.closable = true;
        this.title.iconClass = 'fa fa-industry';
        ensureSemblDesign();
        this.bootstrap();
    }

    dispose(): void {
        if (this.pollTimer !== undefined) {
            clearTimeout(this.pollTimer);
            this.pollTimer = undefined;
        }
        super.dispose();
    }

    protected async bootstrap(): Promise<void> {
        if (!this.repoPath) {
            const roots = await this.workspaceService.roots;
            if (roots.length > 0) {
                // URI path form is '/c:/Users/…' on Windows — display it drive-first.
                const p = roots[0].resource.path.toString();
                const m = /^\/([a-zA-Z]:\/.*)$/.exec(p);
                this.repoPath = m ? m[1] : p;
            }
        }
        await this.refresh();
    }

    protected async refresh(): Promise<void> {
        if (this.repoPath) {
            this.state = await this.factoryService.getState(this.repoPath);
            if (this.selectedRun) {
                this.selectedRun = this.state.runs.find(r => r.id === this.selectedRun!.id);
            }
            if (!this.selectedRun && this.state.runs.length > 0) {
                this.selectedRun = this.state.runs[0];
            }
        }
        this.loaded = true;
        this.update();
        this.schedulePoll();
    }

    protected schedulePoll(): void {
        if (this.pollTimer !== undefined) {
            clearTimeout(this.pollTimer);
        }
        const anyRunning = (this.state?.runs ?? []).some(r => r.running);
        const delay = anyRunning ? FactoryViewWidget.POLL_LIVE_MS : FactoryViewWidget.POLL_IDLE_MS;
        this.pollTimer = setTimeout(() => { this.refresh(); }, delay);
    }

    protected selectRun(r: RunSummary): void {
        this.selectedRun = r;
        // DESIGN-sembl-ide.md §2: the override checkbox resets to unchecked whenever the
        // selected run changes — it must never silently carry "I accept responsibility"
        // over to a different run's BLOCK.
        this.overrideChecked = false;
        this.update();
    }

    // --- BLOCK-panel actions (DESIGN-sembl-ide.md §2 "heavy override control") ----------

    protected async rerun(): Promise<void> {
        if (!this.repoPath || this.rerunPending) { return; }
        this.rerunPending = true;
        this.update();
        try {
            const result = await this.factoryService.rerunTask(this.repoPath);
            if (result.ok) {
                this.messageService.info(result.message);
            } else {
                this.messageService.warn(result.message);
            }
        } catch (e) {
            this.messageService.error(`re-run failed: ${e}`);
        } finally {
            this.rerunPending = false;
            await this.refresh();
        }
    }

    protected async reviseBounds(): Promise<void> {
        // Frontend-only (O1): the backend owns no editor state. This mirrors the same
        // taskfile convention the backend's re-run action resolves against
        // (factory-service-impl.ts resolveTaskFile) — task.yaml at the repo root.
        if (!this.repoPath) { return; }
        // CodeUri.file() is required: `new URI('C:/…')` would parse the drive letter as
        // the URI *scheme*, silently dropping both the drive and the file:// scheme.
        const uri = new URI(CodeUri.file(this.repoPath)).resolve('task.yaml');
        const exists = await this.fileService.exists(uri).catch(() => false);
        if (!exists) {
            this.messageService.warn(`no task file to revise — expected ${uri.path.fsPath()}`);
            return;
        }
        await open(this.openerService, uri);
    }

    protected async overrideApply(): Promise<void> {
        // No headless override path exists engine-side (sembl_stack/cli.py `apply` refuses
        // any BLOCK verdict outright, and `merge` refuses to merge one — there is no CLI
        // flag or function anywhere in sembl_stack/ or ../sembl that applies a BLOCKed
        // change). Per O1/BLOCK-means-blocked this button must not invent that logic in
        // TypeScript — it can only ever call through to real engine machinery, which does
        // not exist yet. Surface that honestly instead of pretending to act.
        this.messageService.warn(
            'no headless override path exists yet — overrides must be built engine-side '
            + 'first (Track: BLOCK-means-blocked)'
        );
    }

    protected render(): React.ReactNode {
        const s = this.state;
        return <div style={{
            padding: '12px 16px', fontFamily: SEMBL.mono, fontSize: '12px',
            height: '100%', overflow: 'auto', background: SEMBL.panel,
            color: 'rgba(255,255,255,0.72)'
        }}>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '12px' }}>
                <span style={{ fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)' }}>repo</span>
                <input
                    style={{
                        flex: 1, fontFamily: SEMBL.mono, fontSize: '11px',
                        background: SEMBL.editor, color: 'rgba(255,255,255,0.72)',
                        border: SEMBL.border, borderRadius: '4px', padding: '4px 8px', outline: 'none'
                    }}
                    value={this.repoPath}
                    onChange={e => { this.repoPath = e.target.value; this.update(); }}
                />
                <button onClick={() => this.refresh()} style={{
                    fontFamily: SEMBL.sans, fontSize: '11px', padding: '5px 12px', borderRadius: '4px',
                    border: '1px solid rgba(255,255,255,0.14)', background: 'transparent',
                    color: 'rgba(255,255,255,0.65)', cursor: 'pointer'
                }}>refresh</button>
            </div>

            {!this.loaded && <p style={{ color: 'rgba(255,255,255,0.4)' }}>loading…</p>}
            {this.loaded && !s &&
                <p style={{ color: 'rgba(255,255,255,0.4)' }}>open a folder (or enter a repo path) to see its factory state</p>}

            {s && <div>
                {/* pipeline adapters */}
                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginBottom: '12px' }}>
                    {s.layers.map(l => {
                        const isGate = l.key === 'verify' || l.key === 'postdeploy';
                        return <div key={l.key} title={l.fromConfig
                            ? `${l.key}: ${l.adapter} (from sembl.stack.yaml)`
                            : `${l.key}: ${l.adapter} (default — not set in sembl.stack.yaml)`}
                            style={{
                                padding: '3px 9px', fontSize: '10px', letterSpacing: '0.04em',
                                background: SEMBL.editor, border: SEMBL.border, borderRadius: '4px',
                                opacity: l.fromConfig ? 1 : 0.5, whiteSpace: 'nowrap'
                            }}>
                            <span style={{ color: 'rgba(255,255,255,0.35)', marginRight: '6px' }}>{l.stage}</span>
                            <span style={{ color: 'rgba(255,255,255,0.6)' }}>{l.key}:</span>{' '}
                            <span style={{ color: 'rgba(255,255,255,0.85)' }}>{l.adapter}</span>
                            {isGate && <span style={{ color: SEMBL.cyan, opacity: 0.7, marginLeft: '6px' }}>⛨</span>}
                        </div>;
                    })}
                </div>

                {/* run-history ribbon */}
                <div style={{ display: 'flex', gap: '3px', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', marginRight: '8px' }}>
                        runs ({s.runs.length})
                    </span>
                    {s.runs.length === 0 &&
                        <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '11px' }}>none yet — run `sembl-stack loop task.yaml` in the terminal</span>}
                    {s.runs.map(r =>
                        <div key={r.id}
                            title={r.running ? `${r.id} — running (${r.currentStage ?? '…'})` : `${r.id} — ${r.verdictStatus ?? r.status ?? '?'}`}
                            onClick={() => this.selectRun(r)}
                            style={{
                                width: '6px', height: '16px', borderRadius: '1px', cursor: 'pointer',
                                ...(r.running ? runningTickStyle() : {
                                    background: tickColor(r.verdictStatus ?? r.status),
                                    border: this.selectedRun?.id === r.id
                                        ? '1.5px solid rgba(255,255,255,0.65)' : '1.5px solid transparent'
                                })
                            }} />
                    )}
                </div>

                {/* selected run detail */}
                {this.selectedRun && <div style={{
                    padding: '12px 14px', background: SEMBL.card,
                    border: SEMBL.borderStrong, borderRadius: '6px'
                }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '14px', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.85)' }}>{this.selectedRun.id}</span>
                        {this.selectedRun.task &&
                            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>{this.selectedRun.task}</span>}
                        {this.selectedRun.attempts !== undefined &&
                            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>
                                {this.selectedRun.attempts} attempt{this.selectedRun.attempts === 1 ? '' : 's'}
                            </span>}
                        {this.selectedRun.created &&
                            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)' }}>
                                {new Date(this.selectedRun.created * 1000).toLocaleString()}
                            </span>}
                        <div style={gateChipStyle(verdictTone(this.selectedRun.verdictStatus ?? this.selectedRun.status))}>
                            {this.selectedRun.verdictStatus ?? this.selectedRun.status ?? '?'}
                        </div>
                    </div>
                    {this.selectedRun.reasons && this.selectedRun.reasons.length > 0 &&
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '10px' }}>
                            {this.selectedRun.reasons.map((reason, i) =>
                                <div key={i} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', fontSize: '12px', lineHeight: 1.5 }}>
                                    <span style={{ color: SEMBL.red, flex: 'none' }}>·</span>
                                    <span style={{ color: 'rgba(255,255,255,0.75)' }}>{reason}</span>
                                </div>)}
                        </div>}

                    {/* heavy override control — BLOCK panel only, DESIGN-sembl-ide.md §2 */}
                    {(this.selectedRun.verdictStatus ?? this.selectedRun.status) === 'BLOCK' &&
                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '10px', marginTop: '16px',
                            paddingTop: '14px', borderTop: '1px solid rgba(255,255,255,0.07)'
                        }}>
                            <button onClick={() => this.rerun()} disabled={this.rerunPending} style={{
                                background: SEMBL.cyan, color: '#0d1114', border: 'none', borderRadius: '5px',
                                padding: '8px 16px', fontFamily: SEMBL.sans, fontSize: '12px', fontWeight: 600,
                                cursor: this.rerunPending ? 'not-allowed' : 'pointer',
                                opacity: this.rerunPending ? 0.6 : 1
                            }}>{this.rerunPending ? 're-running…' : 're-run'}</button>
                            <button onClick={() => this.reviseBounds()} style={{
                                background: 'none', color: 'rgba(255,255,255,0.7)',
                                border: '1px solid rgba(255,255,255,0.18)', borderRadius: '5px',
                                padding: '8px 16px', fontFamily: SEMBL.sans, fontSize: '12px', fontWeight: 500,
                                cursor: 'pointer'
                            }}>revise bounds</button>
                            <div style={{ flex: 1 }} />
                            <label style={{
                                display: 'flex', alignItems: 'center', gap: '7px', fontFamily: SEMBL.mono,
                                fontSize: '11px', color: 'rgba(255,255,255,0.45)', cursor: 'pointer'
                            }}>
                                <input type="checkbox" checked={this.overrideChecked} style={{ accentColor: SEMBL.red }}
                                    onChange={e => { this.overrideChecked = e.target.checked; this.update(); }} />
                                i accept responsibility for this bound violation
                            </label>
                            <button onClick={() => this.overrideApply()} disabled={!this.overrideChecked} style={{
                                fontFamily: SEMBL.mono, fontSize: '11px', letterSpacing: '0.04em',
                                textTransform: 'uppercase', padding: '9px 16px', background: 'transparent',
                                color: this.overrideChecked ? SEMBL.red : 'rgba(193,104,92,0.35)',
                                border: `1px solid ${this.overrideChecked ? 'rgba(193,104,92,0.55)' : 'rgba(193,104,92,0.2)'}`,
                                borderRadius: '4px',
                                cursor: this.overrideChecked ? 'pointer' : 'not-allowed'
                            }}>override — apply anyway</button>
                        </div>}
                </div>}
            </div>}
        </div>;
    }
}
