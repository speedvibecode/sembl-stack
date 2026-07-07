import { ContainerModule } from '@theia/core/shared/inversify';
import { bindViewContribution, FrontendApplicationContribution, WidgetFactory } from '@theia/core/lib/browser';
import { WebSocketConnectionProvider } from '@theia/core/lib/browser/messaging/ws-connection-provider';
import { SkillPromptCoordinator } from '@theia/ai-core/lib/browser/skill-prompt-coordinator';
import { FactoryService, FACTORY_SERVICE_PATH } from '../common/factory-protocol';
import { FactoryViewContribution } from './factory-view-contribution';
import { FactoryViewWidget } from './factory-view-widget';
import { FactoryStripWidget } from './factory-strip-widget';

// Upstream boot-deadlock workaround (Theia 1.73.1): @theia/ai-core ships (via
// plugin-ext, not by our choice) a SkillPromptCoordinator whose onStart awaits
// skillService.ready → workspaceService.ready. On a boot with no workspace to
// restore, that chain never resolves — and because Theia awaits every
// contribution's onStart BEFORE attaching the shell, the whole app hangs on the
// splash with zero errors, and no workspace can ever be opened to unwedge it.
// Make it fire-and-forget: skills still register when (if) they resolve, but
// startup never waits. Re-check on any Theia upgrade past 1.73.x.
const originalSkillOnStart = SkillPromptCoordinator.prototype.onStart;
SkillPromptCoordinator.prototype.onStart = function (this: SkillPromptCoordinator): Promise<void> {
    originalSkillOnStart.call(this).catch((e: unknown) =>
        console.warn('sembl: skill prompt coordinator did not settle', e));
    return Promise.resolve();
};

export default new ContainerModule(bind => {
    // bindViewContribution already registers Command/Menu/Keybinding contributions —
    // re-binding them here double-registers the toggle command (a startup WARN).
    bindViewContribution(bind, FactoryViewContribution);
    bind(FrontendApplicationContribution).toService(FactoryViewContribution);

    bind(FactoryViewWidget).toSelf();
    bind(FactoryStripWidget).toSelf().inSingletonScope();
    bind(WidgetFactory).toDynamicValue(ctx => ({
        id: FactoryViewWidget.ID,
        createWidget: () => ctx.container.get(FactoryViewWidget)
    })).inSingletonScope();

    bind(FactoryService).toDynamicValue(ctx => {
        const provider = ctx.container.get(WebSocketConnectionProvider);
        return provider.createProxy<FactoryService>(FACTORY_SERVICE_PATH);
    }).inSingletonScope();
});
