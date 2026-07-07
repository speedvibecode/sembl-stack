import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { DriftFinding, DriftService } from '../common/drift-protocol';

export const DRIFT_VIEW_WIDGET_ID = 'sembl-drift-view';

// The smallest possible Theia slice (SPEC-theia-factory-ide.md §5 step 2): render real,
// live drift data from sembl_stack/drift.py's persisted state. No graph rendering, no
// resolution commands (update spec / update code / mark exception) yet — those are
// Track 5 item 4, deliberately not built here. This widget's only job is proving the
// graph-first surface can show something real before anything else is layered on top.
@injectable()
export class DriftViewWidget extends ReactWidget {

    static readonly ID = DRIFT_VIEW_WIDGET_ID;
    static readonly LABEL = 'Drift';

    @inject(DriftService) protected readonly driftService: DriftService;

    protected repoPath = 'C:/Users/totla/Desktop/projects/sembl-stack/examples/flagship-feedback-board';
    protected findings: DriftFinding[] = [];
    protected loaded = false;

    @postConstruct()
    protected init(): void {
        this.id = DriftViewWidget.ID;
        this.title.label = DriftViewWidget.LABEL;
        this.title.caption = DriftViewWidget.LABEL;
        this.title.closable = true;
        this.title.iconClass = 'fa fa-code-fork';
        this.refresh();
    }

    protected async refresh(): Promise<void> {
        this.findings = await this.driftService.getPending(this.repoPath);
        this.loaded = true;
        this.update();
    }

    protected render(): React.ReactNode {
        return <div style={{ padding: '10px', fontFamily: 'var(--theia-ui-font-family)', fontSize: '13px' }}>
            <div style={{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
                <input
                    style={{ flex: 1, fontSize: '12px' }}
                    value={this.repoPath}
                    onChange={e => { this.repoPath = e.target.value; this.update(); }}
                />
                <button className="theia-button" onClick={() => this.refresh()}>load</button>
            </div>
            {!this.loaded && <p>loading…</p>}
            {this.loaded && this.findings.length === 0 &&
                <p style={{ opacity: 0.7 }}>no pending drift</p>}
            {this.loaded && this.findings.length > 0 &&
                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                    {this.findings.map((f, i) =>
                        <li key={i} style={{
                            marginBottom: '8px', padding: '6px 8px',
                            borderLeft: '2px solid var(--theia-editorWarning-foreground)',
                            background: 'var(--theia-editorWidget-background)'
                        }}>
                            <div style={{ opacity: 0.75, fontSize: '11px' }}>{f.kind}</div>
                            <div>{f.message}</div>
                        </li>
                    )}
                </ul>}
        </div>;
    }
}
