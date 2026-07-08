import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { CommandService } from '@theia/core/lib/common';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { FactoryService, FactoryState } from '../common/factory-protocol';
import { SEMBL, ensureSemblDesign, gateChipStyle, verdictTone } from './sembl-design';

// The always-visible factory strip (top shell area, below the menu bar):
// mark + stage dots + latest gate verdict chip. Read-only, same FactoryService
// data as the panel (O1). Design step 2: while the latest run is live (RunSummary.running),
// dots before the current stage go "done" cyan, the current stage pulses, dots after stay
// pending, the mark square goes cyan, and the chip reads "running" — all driven by
// RunSummary.currentStage from the backend's events.jsonl read, nothing computed here.
// Idle (no live run) rendering is untouched: dots reflect config-set vs default adapters.
@injectable()
export class FactoryStripWidget extends ReactWidget {

    static readonly ID = 'sembl-factory-strip';

    @inject(FactoryService) protected readonly factoryService: FactoryService;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;
    @inject(CommandService) protected readonly commands: CommandService;

    protected state: FactoryState | undefined;
    protected pollTimer: ReturnType<typeof setTimeout> | undefined;

    // design labels for our layer keys (verify is the gate; postdeploy verifies in prod)
    protected static readonly STAGE_LABEL: { [key: string]: string } = {
        context: 'context', spec: 'spec', execute: 'execute', sandbox: 'sandbox',
        verify: 'gate', review: 'review', merge: 'merge', deploy: 'deploy', postdeploy: 'verify'
    };

    // poll fast while a run is live, slow otherwise — see DESIGN-sembl-ide.md §5 step 2.
    protected static readonly POLL_LIVE_MS = 2000;
    protected static readonly POLL_IDLE_MS = 15000;

    @postConstruct()
    protected init(): void {
        this.id = FactoryStripWidget.ID;
        this.addClass('sembl-factory-strip');
        ensureSemblDesign();
        this.refresh();
    }

    dispose(): void {
        if (this.pollTimer !== undefined) {
            clearTimeout(this.pollTimer);
            this.pollTimer = undefined;
        }
        super.dispose();
    }

    protected async refresh(): Promise<void> {
        try {
            const roots = await this.workspaceService.roots;
            if (roots.length > 0) {
                this.state = await this.factoryService.getState(roots[0].resource.path.toString());
            }
        } catch { /* strip is decoration — never break the shell */ }
        this.update();
        this.schedulePoll();
    }

    protected schedulePoll(): void {
        if (this.pollTimer !== undefined) {
            clearTimeout(this.pollTimer);
        }
        const anyRunning = (this.state?.runs ?? []).some(r => r.running);
        const delay = anyRunning ? FactoryStripWidget.POLL_LIVE_MS : FactoryStripWidget.POLL_IDLE_MS;
        this.pollTimer = setTimeout(() => { this.refresh(); }, delay);
    }

    protected render(): React.ReactNode {
        const latest = this.state?.runs[0];
        const running = latest?.running === true;
        const tone = running ? 'neutral' : verdictTone(latest?.verdictStatus ?? latest?.status);
        const layers = this.state?.layers ?? [];
        const currentIndex = running && latest?.currentStage
            ? layers.findIndex(l => l.key === latest.currentStage)
            : -1;
        return <div
            onClick={() => this.commands.executeCommand('sembl.factory.toggle')}
            title={latest ? `latest run ${latest.id} — click for the Factory panel` : 'no runs recorded — click for the Factory panel'}
            style={{
                height: '32px', display: 'flex', alignItems: 'center', cursor: 'pointer',
                background: SEMBL.strip, borderBottom: SEMBL.border,
                opacity: running ? 1 : 0.82, fontFamily: SEMBL.sans, transition: 'opacity 0.3s ease'
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingLeft: '14px', width: '180px', flex: 'none' }}>
                <div style={{ width: '9px', height: '9px', borderRadius: '2px', background: running ? SEMBL.cyan : 'rgba(255,255,255,0.3)' }} />
                <span style={{ fontFamily: SEMBL.mono, fontSize: '11px', fontWeight: 600, letterSpacing: '0.06em', color: 'rgba(255,255,255,0.72)' }}>
                    SEMBL FACTORY
                </span>
            </div>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {layers.map((l, i) => {
                    const label = FactoryStripWidget.STAGE_LABEL[l.key] ?? l.key;
                    let dotStyle: React.CSSProperties;
                    let labelColor: string;
                    if (currentIndex >= 0) {
                        // live-run lighting: before / current (pulsing) / after the run's stage.
                        if (i < currentIndex) {
                            dotStyle = { background: 'rgba(124,212,223,0.55)' };
                            labelColor = 'rgba(255,255,255,0.55)';
                        } else if (i === currentIndex) {
                            dotStyle = { background: SEMBL.cyan, animation: 'sembl-pulse-ring 1.4s ease-out infinite' };
                            labelColor = 'rgba(124,212,223,0.9)';
                        } else {
                            dotStyle = { background: 'rgba(255,255,255,0.16)' };
                            labelColor = 'rgba(255,255,255,0.28)';
                        }
                    } else {
                        // idle: unchanged — dots reflect config-set vs default adapters.
                        dotStyle = { background: l.fromConfig ? 'rgba(124,212,223,0.55)' : 'rgba(255,255,255,0.16)' };
                        labelColor = l.fromConfig ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.28)';
                    }
                    return <div key={l.key} style={{ display: 'flex', alignItems: 'center' }}
                        title={`${l.stage} ${l.key}: ${l.adapter}${l.fromConfig ? '' : ' (default)'}`}>
                        <div style={{ padding: '0 10px', display: 'flex', alignItems: 'center' }}>
                            <div style={{ width: '6px', height: '6px', borderRadius: '50%', ...dotStyle }} />
                        </div>
                        <span style={{
                            fontFamily: SEMBL.mono, fontSize: '10px', letterSpacing: '0.04em',
                            color: labelColor
                        }}>{label}</span>
                        {i < layers.length - 1 &&
                            <div style={{ width: '20px', height: '1px', background: 'rgba(255,255,255,0.08)', marginLeft: '10px' }} />}
                    </div>;
                })}
                {layers.length === 0 &&
                    <span style={{ fontFamily: SEMBL.mono, fontSize: '10px', color: 'rgba(255,255,255,0.28)' }}>
                        open a folder to see its pipeline
                    </span>}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px', paddingRight: '16px', flex: 'none' }}>
                <div style={gateChipStyle(tone)}>
                    {running ? 'running' : (latest ? (latest.verdictStatus ?? latest.status ?? '—') : '—')}
                </div>
            </div>
        </div>;
    }
}
