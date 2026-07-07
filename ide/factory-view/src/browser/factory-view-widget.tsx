import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { FactoryService, FactoryState, RunSummary } from '../common/factory-protocol';
import { SEMBL, ensureSemblDesign, gateChipStyle, tickColor, verdictTone } from './sembl-design';

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
        ensureSemblDesign();
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
                            title={`${r.id} — ${r.verdictStatus ?? r.status ?? '?'}`}
                            onClick={() => { this.selectedRun = r; this.update(); }}
                            style={{
                                width: '6px', height: '16px', borderRadius: '1px', cursor: 'pointer',
                                background: tickColor(r.verdictStatus ?? r.status),
                                border: this.selectedRun?.id === r.id
                                    ? '1.5px solid rgba(255,255,255,0.65)' : '1.5px solid transparent'
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
                </div>}
            </div>}
        </div>;
    }
}
