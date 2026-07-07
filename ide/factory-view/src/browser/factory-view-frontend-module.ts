import { ContainerModule } from '@theia/core/shared/inversify';
import { bindViewContribution, FrontendApplicationContribution, WidgetFactory } from '@theia/core/lib/browser';
import { WebSocketConnectionProvider } from '@theia/core/lib/browser/messaging/ws-connection-provider';
import { FactoryService, FACTORY_SERVICE_PATH } from '../common/factory-protocol';
import { FactoryViewContribution } from './factory-view-contribution';
import { FactoryViewWidget } from './factory-view-widget';

export default new ContainerModule(bind => {
    // bindViewContribution already registers Command/Menu/Keybinding contributions —
    // re-binding them here double-registers the toggle command (a startup WARN).
    bindViewContribution(bind, FactoryViewContribution);
    bind(FrontendApplicationContribution).toService(FactoryViewContribution);

    bind(FactoryViewWidget).toSelf();
    bind(WidgetFactory).toDynamicValue(ctx => ({
        id: FactoryViewWidget.ID,
        createWidget: () => ctx.container.get(FactoryViewWidget)
    })).inSingletonScope();

    bind(FactoryService).toDynamicValue(ctx => {
        const provider = ctx.container.get(WebSocketConnectionProvider);
        return provider.createProxy<FactoryService>(FACTORY_SERVICE_PATH);
    }).inSingletonScope();
});
