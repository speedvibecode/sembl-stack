import { ContainerModule } from '@theia/core/shared/inversify';
import { bindViewContribution, FrontendApplicationContribution, WidgetFactory } from '@theia/core/lib/browser';
import { WebSocketConnectionProvider } from '@theia/core/lib/browser/messaging/ws-connection-provider';
import { DriftService, DRIFT_SERVICE_PATH } from '../common/drift-protocol';
import { DriftViewContribution } from './drift-view-contribution';
import { DriftViewWidget } from './drift-view-widget';
import { SpecGraphContribution } from './spec-graph-contribution';
import { SpecGraphWidget } from './spec-graph-widget';

export default new ContainerModule(bind => {
    // bindViewContribution already registers Command/Menu/Keybinding contributions —
    // re-binding them here double-registers the toggle command (a startup WARN).
    bindViewContribution(bind, DriftViewContribution);
    bind(FrontendApplicationContribution).toService(DriftViewContribution);

    bind(DriftViewWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({
        id: DriftViewWidget.ID,
        createWidget: () => ctx.container.get(DriftViewWidget)
    })).inSingletonScope();

    // Design step 5: the spec graph is a second, independent widget in this extension
    // (drift domain owns spec↔code reconciliation) — its own contribution class, same
    // bindViewContribution pattern, so its command isn't double-registered either.
    bindViewContribution(bind, SpecGraphContribution);
    bind(FrontendApplicationContribution).toService(SpecGraphContribution);

    bind(SpecGraphWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({
        id: SpecGraphWidget.ID,
        createWidget: () => ctx.container.get(SpecGraphWidget)
    })).inSingletonScope();

    bind(DriftService).toDynamicValue(ctx => {
        const provider = ctx.container.get(WebSocketConnectionProvider);
        return provider.createProxy<DriftService>(DRIFT_SERVICE_PATH);
    }).inSingletonScope();
});
