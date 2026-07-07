import { ContainerModule } from '@theia/core/shared/inversify';
import { bindViewContribution, FrontendApplicationContribution, WidgetFactory } from '@theia/core/lib/browser';
import { CommandContribution, MenuContribution } from '@theia/core/lib/common';
import { WebSocketConnectionProvider } from '@theia/core/lib/browser/messaging/ws-connection-provider';
import { DriftService, DRIFT_SERVICE_PATH } from '../common/drift-protocol';
import { DriftViewContribution } from './drift-view-contribution';
import { DriftViewWidget } from './drift-view-widget';

export default new ContainerModule(bind => {
    bindViewContribution(bind, DriftViewContribution);
    bind(FrontendApplicationContribution).toService(DriftViewContribution);
    bind(CommandContribution).toService(DriftViewContribution);
    bind(MenuContribution).toService(DriftViewContribution);

    bind(DriftViewWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({
        id: DriftViewWidget.ID,
        createWidget: () => ctx.container.get(DriftViewWidget)
    })).inSingletonScope();

    bind(DriftService).toDynamicValue(ctx => {
        const provider = ctx.container.get(WebSocketConnectionProvider);
        return provider.createProxy<DriftService>(DRIFT_SERVICE_PATH);
    }).inSingletonScope();
});
