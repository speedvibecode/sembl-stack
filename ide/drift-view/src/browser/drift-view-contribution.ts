import { injectable } from '@theia/core/shared/inversify';
import { AbstractViewContribution, FrontendApplication } from '@theia/core/lib/browser';
import { Command } from '@theia/core/lib/common';
import { DriftViewWidget } from './drift-view-widget';

export const DriftViewCommand: Command = {
    id: 'sembl.drift.toggle',
    label: 'Toggle Drift View'
};

@injectable()
export class DriftViewContribution extends AbstractViewContribution<DriftViewWidget> {
    constructor() {
        super({
            widgetId: DriftViewWidget.ID,
            widgetName: DriftViewWidget.LABEL,
            defaultWidgetOptions: { area: 'right', rank: 100 },
            toggleCommandId: DriftViewCommand.id
        });
    }

    /**
     * Fresh layouts get the drift view parked in the right rail (icon visible,
     * panel collapsed) — otherwise it only exists behind the command palette and
     * is undiscoverable.
     */
    async initializeLayout(app: FrontendApplication): Promise<void> {
        await this.openView({ activate: false, reveal: false });
    }
}
