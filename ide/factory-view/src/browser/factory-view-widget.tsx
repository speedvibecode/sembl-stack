import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { FactoryService, FactoryState, RunSummary } from '../common/factory-protocol';

export const FACTORY_VIEW_WIDGET_ID = 'sembl-factory-view';

// The factory cockpit panel (bottom area): the pipeline strip (which adapter each
// L1-L8 layer runs, straight from sembl.stack.yaml) + the run-history ribbon over
// .sembl/runs/. Read-only in this slice — swapping still happens by editing the
// yaml (one click away in the editor); resolution/relaunch actions are later work.
@injectable()
export class FactoryViewWidget extends ReactWidget {

    static readonly ID = FACTORY_VIEW_WIDGET_ID;
    static readonly LABEL = 'Factory';

    @inject(FactoryService) protected readonly factoryService: FactoryService;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;

    protected repoPath = '';
    protected state: FactoryState | undefined;
    protected selectedRun: RunSummary | undefined;
    protected loaded = false;

    @postConstruct()
    protected init(): void {
        this.id = FactoryViewWidget.ID;
        this.title.label = FactoryViewWidget.LABEL;
        this.title.caption = 'sembl-stack pipeline + run history';
        this.title.closable = true;
        this.title.iconClass = 'fa fa-industry';
        this.bootstrap();
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
    }

    protected verdictColor(status?: string): string {
        switch (status) {
            case 'PASS': return 'var(--theia-editorGutter-addedBackground)';
            case 'WARN': return 'var(--theia-editorWarning-foreground)';
            case 'BLOCK':
            case 'failed': return 'var(--theia-editorError-foreground)';
            default: return 'var(--theia-descriptionForeground)';
        }
    }

    protected render(): React.ReactNode {
        const s = this.state;
        const latest = s?.runs[0];
        return <div style={{
            padding: '8px 12px', fontFamily: 'var(--theia-ui-font-family)',
            fontSize: '12px', height: '100%', overflow: 'auto'
        }}>
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ opacity: 0.7 }}>repo</span>
                <input
                    style={{ flex: 1, fontSize: '12px' }}
                    value={this.repoPath}
                    onChange={e => { this.repoPath = e.target.value; this.update(); }}
                />
                <button className="theia-button" onClick={() => this.refresh()}>refresh</button>
            </div>

            {!this.loaded && <p>loading…</p>}
            {this.loaded && !s && <p style={{ opacity: 0.7 }}>open a folder (or enter a repo path) to see its factory state</p>}

            {s && <div>
                {/* pipeline strip */}
                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginBottom: '10px' }}>
                    {s.layers.map(l => {
                        const isGate = l.key === 'verify' || l.key === 'postdeploy';
                        const gateColor = l.key === 'verify' ? this.verdictColor(latest?.verdictStatus) : undefined;
                        return <div key={l.key} title={l.fromConfig
                            ? `${l.key}: ${l.adapter} (from sembl.stack.yaml)`
                            : `${l.key}: ${l.adapter} (default — not set in sembl.stack.yaml)`}
                            style={{
                                padding: '3px 8px',
                                background: 'var(--theia-editorWidget-background)',
                                border: '1px solid var(--theia-editorWidget-border, transparent)',
                                borderBottom: gateColor ? `2px solid ${gateColor}` : undefined,
                                opacity: l.fromConfig ? 1 : 0.55,
                                whiteSpace: 'nowrap'
                            }}>
                            <span style={{ opacity: 0.6, marginRight: '5px' }}>{l.stage}</span>
                            <span>{l.key}: <b>{l.adapter}</b></span>
                            {isGate && <span style={{ opacity: 0.6, marginLeft: '5px' }}>⛨</span>}
                        </div>;
                    })}
                </div>

                {/* run-history ribbon */}
                <div style={{ display: 'flex', gap: '3px', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' }}>
                    <span style={{ opacity: 0.7, marginRight: '4px' }}>
                        runs ({s.runs.length})
                    </span>
                    {s.runs.length === 0 &&
                        <span style={{ opacity: 0.6 }}>none yet — run `sembl-stack loop task.yaml` in the terminal below</span>}
                    {s.runs.map(r =>
                        <div key={r.id}
                            title={`${r.id} — ${r.verdictStatus ?? r.status ?? '?'}`}
                            onClick={() => { this.selectedRun = r; this.update(); }}
                            style={{
                                width: '14px', height: '14px', cursor: 'pointer',
                                background: this.verdictColor(r.verdictStatus ?? r.status),
                                outline: this.selectedRun?.id === r.id
                                    ? '2px solid var(--theia-focusBorder)' : 'none'
                            }} />
                    )}
                </div>

                {/* selected run detail */}
                {this.selectedRun && <div style={{
                    padding: '6px 8px',
                    background: 'var(--theia-editorWidget-background)',
                    borderLeft: `2px solid ${this.verdictColor(this.selectedRun.verdictStatus ?? this.selectedRun.status)}`
                }}>
                    <div>
                        <b>{this.selectedRun.verdictStatus ?? this.selectedRun.status ?? '?'}</b>
                        <span style={{ opacity: 0.7, marginLeft: '8px' }}>{this.selectedRun.id}</span>
                        {this.selectedRun.attempts !== undefined &&
                            <span style={{ opacity: 0.7, marginLeft: '8px' }}>
                                {this.selectedRun.attempts} attempt{this.selectedRun.attempts === 1 ? '' : 's'}
                            </span>}
                        {this.selectedRun.created &&
                            <span style={{ opacity: 0.7, marginLeft: '8px' }}>
                                {new Date(this.selectedRun.created * 1000).toLocaleString()}
                            </span>}
                    </div>
                    {this.selectedRun.task &&
                        <div style={{ marginTop: '4px', opacity: 0.85 }}>{this.selectedRun.task}</div>}
                    {this.selectedRun.reasons && this.selectedRun.reasons.length > 0 &&
                        <ul style={{ margin: '4px 0 0 0', paddingLeft: '16px' }}>
                            {this.selectedRun.reasons.map((reason, i) => <li key={i}>{reason}</li>)}
                        </ul>}
                </div>}
            </div>}
        </div>;
    }
}
