import { injectable } from '@theia/core/shared/inversify';
import { AbstractViewContribution, FrontendApplication } from '@theia/core/lib/browser';
import { Command } from '@theia/core/lib/common';
import { GuideWidget } from './guide-widget';

export const GuideCommand: Command = {
    id: 'sembl.guide.toggle',
    label: 'Toggle Guide'
};

@injectable()
export class GuideContribution extends AbstractViewContribution<GuideWidget> {
    constructor() {
        super({
            widgetId: GuideWidget.ID,
            widgetName: GuideWidget.LABEL,
            defaultWidgetOptions: { area: 'right', rank: 80 },
            toggleCommandId: GuideCommand.id
        });
    }

    /**
     * Fresh layouts get the guide panel parked in the right rail (icon visible,
     * panel collapsed) — otherwise it only exists behind the command palette and
     * is undiscoverable, same as discuss/drift/spec-graph.
     */
    async initializeLayout(app: FrontendApplication): Promise<void> {
        await this.openView({ activate: false, reveal: false });
    }
}
