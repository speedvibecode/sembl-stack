import { inject, injectable } from '@theia/core/shared/inversify';
import { AbstractViewContribution, FrontendApplication, StatusBar, StatusBarAlignment } from '@theia/core/lib/browser';
import { Command } from '@theia/core/lib/common';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { FactoryService } from '../common/factory-protocol';
import { FactoryViewWidget } from './factory-view-widget';

export const FactoryViewCommand: Command = {
    id: 'sembl.factory.toggle',
    label: 'Toggle Factory View'
};

@injectable()
export class FactoryViewContribution extends AbstractViewContribution<FactoryViewWidget> {

    @inject(StatusBar) protected readonly statusBar: StatusBar;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;
    @inject(FactoryService) protected readonly factoryService: FactoryService;

    constructor() {
        super({
            widgetId: FactoryViewWidget.ID,
            widgetName: FactoryViewWidget.LABEL,
            defaultWidgetOptions: { area: 'bottom', rank: 200 },
            toggleCommandId: FactoryViewCommand.id
        });
    }

    /** Only runs when there is no restored layout — opens the panel on a fresh workspace. */
    async initializeLayout(app: FrontendApplication): Promise<void> {
        await this.openView({ activate: false, reveal: true });
    }

    async onStart(app: FrontendApplication): Promise<void> {
        this.updateStatusBar();
    }

    protected async updateStatusBar(): Promise<void> {
        try {
            const roots = await this.workspaceService.roots;
            if (roots.length === 0) { return; }
            const state = await this.factoryService.getState(roots[0].resource.path.toString());
            const latest = state.runs[0];
            const verdict = latest ? (latest.verdictStatus ?? latest.status ?? '?') : 'no runs';
            const color = verdict === 'PASS' ? 'var(--theia-editorGutter-addedBackground)'
                : verdict === 'BLOCK' || verdict === 'failed' ? 'var(--theia-editorError-foreground)'
                    : undefined;
            this.statusBar.setElement('sembl-factory-verdict', {
                text: `$(shield) sembl: ${verdict}`,
                alignment: StatusBarAlignment.LEFT,
                priority: 150,
                tooltip: latest ? `latest run ${latest.id}` : 'no runs recorded in .sembl/runs',
                command: FactoryViewCommand.id,
                color
            });
        } catch {
            // status chip is decoration — never let it break startup
        }
    }
}
