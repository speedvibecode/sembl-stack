import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { CommandService } from '@theia/core/lib/common';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { FactoryService, FactoryState } from '../common/factory-protocol';
import { SEMBL, ensureSemblDesign, gateChipStyle, verdictTone } from './sembl-design';

// The always-visible factory strip (top shell area, below the menu bar):
// mark + stage dots + latest gate verdict chip. Read-only, same FactoryService
// data as the panel (O1). Stage *lighting* during a live run is design step 2;
// in this slice dots render the pipeline shape, the chip renders the latest
// recorded verdict, and clicking the strip opens the Factory panel.
@injectable()
export class FactoryStripWidget extends ReactWidget {

    static readonly ID = 'sembl-factory-strip';

    @inject(FactoryService) protected readonly factoryService: FactoryService;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;
    @inject(CommandService) protected readonly commands: CommandService;

    protected state: FactoryState | undefined;

    // design labels for our layer keys (verify is the gate; postdeploy verifies in prod)
    protected static readonly STAGE_LABEL: { [key: string]: string } = {
        context: 'context', spec: 'spec', execute: 'execute', sandbox: 'sandbox',
        verify: 'gate', review: 'review', merge: 'merge', deploy: 'deploy', postdeploy: 'verify'
    };

    @postConstruct()
    protected init(): void {
        this.id = FactoryStripWidget.ID;
        this.addClass('sembl-factory-strip');
        ensureSemblDesign();
        this.refresh();
    }

    protected async refresh(): Promise<void> {
        try {
            const roots = await this.workspaceService.roots;
            if (roots.length > 0) {
                this.state = await this.factoryService.getState(roots[0].resource.path.toString());
            }
        } catch { /* strip is decoration — never break the shell */ }
        this.update();
    }

    protected render(): React.ReactNode {
        const latest = this.state?.runs[0];
        const tone = verdictTone(latest?.verdictStatus ?? latest?.status);
        const layers = this.state?.layers ?? [];
        return <div
            onClick={() => this.commands.executeCommand('sembl.factory.toggle')}
            title={latest ? `latest run ${latest.id} — click for the Factory panel` : 'no runs recorded — click for the Factory panel'}
            style={{
                height: '32px', display: 'flex', alignItems: 'center', cursor: 'pointer',
                background: SEMBL.strip, borderBottom: SEMBL.border,
                opacity: 0.82, fontFamily: SEMBL.sans
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingLeft: '14px', width: '180px', flex: 'none' }}>
                <div style={{ width: '9px', height: '9px', borderRadius: '2px', background: 'rgba(255,255,255,0.3)' }} />
                <span style={{ fontFamily: SEMBL.mono, fontSize: '11px', fontWeight: 600, letterSpacing: '0.06em', color: 'rgba(255,255,255,0.72)' }}>
                    SEMBL FACTORY
                </span>
            </div>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {layers.map((l, i) => {
                    const label = FactoryStripWidget.STAGE_LABEL[l.key] ?? l.key;
                    return <div key={l.key} style={{ display: 'flex', alignItems: 'center' }}
                        title={`${l.stage} ${l.key}: ${l.adapter}${l.fromConfig ? '' : ' (default)'}`}>
                        <div style={{ padding: '0 10px', display: 'flex', alignItems: 'center' }}>
                            <div style={{
                                width: '6px', height: '6px', borderRadius: '50%',
                                background: l.fromConfig ? 'rgba(124,212,223,0.55)' : 'rgba(255,255,255,0.16)'
                            }} />
                        </div>
                        <span style={{
                            fontFamily: SEMBL.mono, fontSize: '10px', letterSpacing: '0.04em',
                            color: l.fromConfig ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.28)'
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
                    {latest ? (latest.verdictStatus ?? latest.status ?? '—') : '—'}
                </div>
            </div>
        </div>;
    }
}
