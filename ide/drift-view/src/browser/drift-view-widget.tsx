import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { MessageService } from '@theia/core/lib/common/message-service';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { DriftPendingEntry, DriftResolveMode, DriftService } from '../common/drift-protocol';
import { SEMBL, ensureSemblDesign, gateChipStyle } from 'sembl-factory-view/lib/browser/sembl-design';

export const DRIFT_VIEW_WIDGET_ID = 'sembl-drift-view';

const DRIFT_STYLE_ID = 'sembl-drift';

/** Inject the drift-panel-only hover rules once per window (per the spec: the cyan/amber
 * hover states are NOT part of sembl-design.ts — that file belongs to factory-view). */
function ensureDriftStyle(): void {
    if (document.getElementById(DRIFT_STYLE_ID)) { return; }
    const style = document.createElement('style');
    style.id = DRIFT_STYLE_ID;
    style.textContent = `
.sembl-drift-btn { transition: color 0.15s ease, border-color 0.15s ease; }
.sembl-drift-btn-primary:hover { border-color: ${SEMBL.cyan} !important; color: ${SEMBL.cyan} !important; }
.sembl-drift-btn-exception:hover { border-color: ${SEMBL.amber} !important; color: ${SEMBL.amber} !important; }
`;
    document.head.appendChild(style);
}

// Track 5 item 4 (IDE side): tri-state drift resolution over the headless
// `sembl-stack drift-resolve` CLI (sembl_stack/cli.py / drift.py). This widget invokes
// that CLI via DriftService.resolve — no resolution logic lives here (O1).
@injectable()
export class DriftViewWidget extends ReactWidget {

    static readonly ID = DRIFT_VIEW_WIDGET_ID;
    static readonly LABEL = 'Drift';

    @inject(DriftService) protected readonly driftService: DriftService;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;
    @inject(MessageService) protected readonly messageService: MessageService;

    protected repoPath = '';
    protected entries: DriftPendingEntry[] = [];
    protected loaded = false;

    // The one card currently expanded into the "mark exception" reason-input state.
    protected exceptionKey: string | undefined;
    protected exceptionReason = '';
    protected pendingKey: string | undefined;   // key currently mid-resolve (disables its buttons)
    protected lastOutput: { [key: string]: { ok: boolean; text: string } } = {};

    @postConstruct()
    protected init(): void {
        this.id = DriftViewWidget.ID;
        this.title.label = DriftViewWidget.LABEL;
        this.title.caption = DriftViewWidget.LABEL;
        this.title.closable = true;
        this.title.iconClass = 'fa fa-code-fork';
        ensureSemblDesign();
        ensureDriftStyle();
        this.bootstrap();
    }

    /** Default the repo to the opened workspace root; the input stays editable. */
    protected async bootstrap(): Promise<void> {
        if (!this.repoPath) {
            const roots = await this.workspaceService.roots;
            if (roots.length > 0) {
                const p = roots[0].resource.path.toString();
                const m = /^\/([a-zA-Z]:\/.*)$/.exec(p);
                this.repoPath = m ? m[1] : p;
            }
        }
        await this.refresh();
    }

    protected async refresh(): Promise<void> {
        this.entries = this.repoPath ? await this.driftService.getPending(this.repoPath) : [];
        this.loaded = true;
        this.update();
    }

    protected openException(key: string): void {
        this.exceptionKey = key;
        this.exceptionReason = '';
        this.update();
    }

    protected closeException(): void {
        this.exceptionKey = undefined;
        this.exceptionReason = '';
        this.update();
    }

    protected async doResolve(key: string, mode: DriftResolveMode, reason?: string): Promise<void> {
        if (this.pendingKey) { return; }
        this.pendingKey = key;
        this.update();
        try {
            const result = await this.driftService.resolve(this.repoPath, key, mode, reason);
            if (!result.ok) {
                this.messageService.warn(result.output || `drift-resolve (${mode}) failed`);
            }
            if (mode === 'mark-exception') {
                this.exceptionKey = undefined;
                this.exceptionReason = '';
                await this.refresh();   // the card leaves pending; its output naturally disappears too
            } else {
                this.lastOutput[key] = { ok: result.ok, text: result.output };
                this.update();
            }
        } finally {
            this.pendingKey = undefined;
            this.update();
        }
    }

    protected render(): React.ReactNode {
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
                }}>load</button>
            </div>

            {!this.loaded && <p style={{ color: 'rgba(255,255,255,0.4)' }}>loading…</p>}
            {this.loaded && this.entries.length === 0 &&
                <p style={{ color: 'rgba(255,255,255,0.4)' }}>no pending drift</p>}
            {this.loaded && this.entries.length > 0 &&
                <div>{this.entries.map(e => this.renderCard(e))}</div>}
        </div>;
    }

    protected renderCard(entry: DriftPendingEntry): React.ReactNode {
        const { key, finding, firstDetected } = entry;
        const busy = this.pendingKey === key;
        const expanded = this.exceptionKey === key;
        const out = this.lastOutput[key];

        return <div key={key} style={{
            marginBottom: '10px', padding: '12px', borderRadius: '6px',
            background: SEMBL.card, border: SEMBL.border,
            borderLeft: `2px solid ${SEMBL.amber}`
        }}>
            <div style={{
                fontFamily: SEMBL.mono, fontSize: '10px', color: SEMBL.amber, opacity: 0.9,
                textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '4px'
            }}>{finding.kind}{finding.spec_node ? `  ${finding.spec_node}` : ''}</div>
            <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.85)', marginBottom: firstDetected ? '4px' : '10px' }}>
                {finding.message}
            </div>
            {firstDetected &&
                <div style={{ fontFamily: SEMBL.mono, fontSize: '10px', color: 'rgba(255,255,255,0.35)', marginBottom: '10px' }}>
                    first detected {firstDetected}
                </div>}

            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                <button
                    className="sembl-drift-btn sembl-drift-btn-primary"
                    disabled={busy}
                    onClick={() => this.doResolve(key, 'update-spec')}
                    style={this.actionButtonStyle(false)}
                >update spec</button>
                <button
                    className="sembl-drift-btn sembl-drift-btn-primary"
                    disabled={busy}
                    onClick={() => this.doResolve(key, 'update-code')}
                    style={this.actionButtonStyle(false)}
                >update code</button>
                <button
                    className="sembl-drift-btn sembl-drift-btn-exception"
                    disabled={busy}
                    onClick={() => expanded ? this.closeException() : this.openException(key)}
                    style={this.actionButtonStyle(true)}
                >mark exception</button>
            </div>

            {expanded && <div style={{ marginTop: '10px', display: 'flex', gap: '6px', alignItems: 'center' }}>
                <input
                    autoFocus
                    placeholder="why is this drift intentional?"
                    value={this.exceptionReason}
                    onChange={ev => { this.exceptionReason = ev.target.value; this.update(); }}
                    style={{
                        flex: 1, fontFamily: SEMBL.mono, fontSize: '11px',
                        background: SEMBL.editor, color: 'rgba(255,255,255,0.72)',
                        border: SEMBL.border, borderRadius: '4px', padding: '4px 8px', outline: 'none'
                    }}
                />
                <button
                    disabled={busy || this.exceptionReason.trim().length === 0}
                    onClick={() => this.doResolve(key, 'mark-exception', this.exceptionReason.trim())}
                    style={{
                        ...gateChipStyle('warn'),
                        cursor: (busy || this.exceptionReason.trim().length === 0) ? 'default' : 'pointer',
                        opacity: (busy || this.exceptionReason.trim().length === 0) ? 0.5 : 1,
                        border: 'none'
                    }}
                >record exception</button>
                <button
                    disabled={busy}
                    onClick={() => this.closeException()}
                    style={{
                        fontFamily: SEMBL.sans, fontSize: '11px', padding: '5px 10px', borderRadius: '4px',
                        border: '1px solid rgba(255,255,255,0.14)', background: 'transparent',
                        color: 'rgba(255,255,255,0.5)', cursor: busy ? 'default' : 'pointer'
                    }}
                >cancel</button>
            </div>}

            {out && <pre style={{
                marginTop: '10px', marginBottom: 0, padding: '8px',
                fontFamily: SEMBL.mono, fontSize: '10px', whiteSpace: 'pre-wrap',
                color: 'rgba(255,255,255,0.45)', background: SEMBL.editor,
                border: SEMBL.border, borderRadius: '4px'
            }}>{out.text}</pre>}
        </div>;
    }

    protected actionButtonStyle(dim: boolean): React.CSSProperties {
        return {
            fontFamily: SEMBL.mono, fontSize: '11px', padding: '5px 10px', borderRadius: '4px',
            background: 'transparent',
            border: `1px solid ${dim ? 'rgba(255,255,255,0.09)' : 'rgba(255,255,255,0.14)'}`,
            color: dim ? 'rgba(255,255,255,0.38)' : 'rgba(255,255,255,0.65)',
            cursor: 'pointer'
        };
    }
}
