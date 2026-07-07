import { ContainerModule } from '@theia/core/shared/inversify';
import { ConnectionHandler, JsonRpcConnectionHandler } from '@theia/core/lib/common/messaging';
import { FactoryService, FACTORY_SERVICE_PATH } from '../common/factory-protocol';
import { FactoryServiceImpl } from './factory-service-impl';

export default new ContainerModule(bind => {
    bind(FactoryServiceImpl).toSelf().inSingletonScope();
    bind(FactoryService).toService(FactoryServiceImpl);
    bind(ConnectionHandler).toDynamicValue(ctx =>
        new JsonRpcConnectionHandler(FACTORY_SERVICE_PATH, () => ctx.container.get(FactoryServiceImpl))
    ).inSingletonScope();
});
