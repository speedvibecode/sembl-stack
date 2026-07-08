import { injectable } from '@theia/core/shared/inversify';
import { AbstractViewContribution } from '@theia/core/lib/browser';
import { Command } from '@theia/core/lib/common';
import { SpecGraphWidget } from './spec-graph-widget';

export const SpecGraphCommand: Command = {
    id: 'sembl.graph.toggle',
    label: 'Toggle Spec Graph'
};

@injectable()
export class SpecGraphContribution extends AbstractViewContribution<SpecGraphWidget> {
    constructor() {
        super({
            widgetId: SpecGraphWidget.ID,
            widgetName: SpecGraphWidget.LABEL,
            defaultWidgetOptions: { area: 'main' },
            toggleCommandId: SpecGraphCommand.id
        });
    }
}
