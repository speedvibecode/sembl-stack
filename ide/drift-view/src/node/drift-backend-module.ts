import { ContainerModule } from '@theia/core/shared/inversify';
import { ConnectionHandler, JsonRpcConnectionHandler } from '@theia/core/lib/common/messaging';
import { DriftService, DRIFT_SERVICE_PATH } from '../common/drift-protocol';
import { DriftServiceImpl } from './drift-service-impl';

export default new ContainerModule(bind => {
    bind(DriftServiceImpl).toSelf().inSingletonScope();
    bind(DriftService).toService(DriftServiceImpl);
    bind(ConnectionHandler).toDynamicValue(ctx =>
        new JsonRpcConnectionHandler(DRIFT_SERVICE_PATH, () => ctx.container.get(DriftServiceImpl))
    ).inSingletonScope();
});
