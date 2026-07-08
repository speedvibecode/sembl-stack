import { injectable } from '@theia/core/shared/inversify';
import { AbstractViewContribution, FrontendApplication } from '@theia/core/lib/browser';
import { Command } from '@theia/core/lib/common';
import { DiscussWidget } from './discuss-widget';

export const DiscussCommand: Command = {
    id: 'sembl.discuss.toggle',
    label: 'Toggle Discuss'
};

@injectable()
export class DiscussContribution extends AbstractViewContribution<DiscussWidget> {
    constructor() {
        super({
            widgetId: DiscussWidget.ID,
            widgetName: DiscussWidget.LABEL,
            defaultWidgetOptions: { area: 'right', rank: 90 },
            toggleCommandId: DiscussCommand.id
        });
    }

    /**
     * Fresh layouts get the discuss panel parked in the right rail (icon visible,
     * panel collapsed) — otherwise it only exists behind the command palette and
     * is undiscoverable, same as drift/spec-graph.
     */
    async initializeLayout(app: FrontendApplication): Promise<void> {
        await this.openView({ activate: false, reveal: false });
    }
}
