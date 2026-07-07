import { injectable } from '@theia/core/shared/inversify';
import { AbstractViewContribution } from '@theia/core/lib/browser';
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
}
