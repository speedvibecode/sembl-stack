import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { ReactFlow, Background, Node, Edge, Position } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { DriftService, SpecEdge, SpecNode } from '../common/drift-protocol';
import { SEMBL, ensureSemblDesign } from 'sembl-factory-view/lib/browser/sembl-design';

export const SPEC_GRAPH_WIDGET_ID = 'sembl-spec-graph';

// Design step 5: renders a run's SpecGraph (sembl_stack/specgraph.py) drift-tinted, per
// docs/DESIGN-sembl-ide.md §3 "Graph view". Thin renderer over persisted state (O1) — no
// layout/graph logic beyond a deterministic column layout lives here; drift tinting is
// read off drift-state.json via DriftService, not recomputed.

// Column-by-type layered left-to-right layout (locked in the spec — no layout lib).
const COLUMN_BY_TYPE: { [type: string]: number } = {
    task: 0,
    source: 1,
    route: 2,
    entity: 2,
    data_rule: 2,
    editable_path: 3,
    forbidden_area: 3
};

function columnFor(type: string): number {
    return type in COLUMN_BY_TYPE ? COLUMN_BY_TYPE[type] : 2;
}

@injectable()
export class SpecGraphWidget extends ReactWidget {

    static readonly ID = SPEC_GRAPH_WIDGET_ID;
    static readonly LABEL = 'Spec Graph';

    @inject(DriftService) protected readonly driftService: DriftService;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;

    protected repoPath = '';
    protected runId: string | undefined;
    protected specNodes: SpecNode[] = [];
    protected specEdges: SpecEdge[] = [];
    protected driftNodeIds: Set<string> = new Set();
    protected exceptedNodeIds: Set<string> = new Set();
    protected loaded = false;

    @postConstruct()
    protected init(): void {
        this.id = SpecGraphWidget.ID;
        this.title.label = SpecGraphWidget.LABEL;
        this.title.caption = SpecGraphWidget.LABEL;
        this.title.closable = true;
        this.title.iconClass = 'fa fa-sitemap';
        this.node.style.height = '100%';
        ensureSemblDesign();
        this.bootstrap();
    }

    protected async bootstrap(): Promise<void> {
        if (!this.repoPath) {
            const roots = await this.workspaceService.roots;
            if (roots.length > 0) {
                const p = roots[0].resource.path.toString();
                const m = /^\/([a-zA-Z]:\/.*)$/.exec(p);
                this.repoPath = m ? m[1] : p;
            }
        }
        await this.refresh();
    }

    protected async refresh(): Promise<void> {
        this.loaded = false;
        this.update();

        if (!this.repoPath) {
            this.loaded = true;
            this.update();
            return;
        }

        const [graph, pending, excepted] = await Promise.all([
            this.driftService.getSpecGraph(this.repoPath),
            this.driftService.getPending(this.repoPath),
            this.driftService.getExceptedNodes(this.repoPath)
        ]);

        this.runId = graph?.runId;
        this.specNodes = graph?.nodes ?? [];
        this.specEdges = graph?.edges ?? [];
        this.driftNodeIds = new Set(pending.map(e => e.finding.spec_node).filter((id): id is string => !!id));
        this.exceptedNodeIds = new Set(excepted);
        this.loaded = true;
        this.update();
    }

    protected buildFlowNodes(): Node[] {
        const columnCounts: { [col: number]: number } = {};
        return this.specNodes.map(n => {
            const col = columnFor(n.type);
            const idx = columnCounts[col] ?? 0;
            columnCounts[col] = idx + 1;

            const isDrift = this.driftNodeIds.has(n.id);
            const isExcepted = !isDrift && this.exceptedNodeIds.has(n.id);
            const isForbidden = n.type === 'forbidden_area';
            const isEditable = n.type === 'editable_path';

            let borderColor = 'rgba(255,255,255,0.07)';
            if (isDrift) {
                borderColor = SEMBL.amber;
            } else if (isForbidden) {
                borderColor = 'rgba(193,104,92,0.4)';
            } else if (isEditable) {
                borderColor = 'rgba(124,212,223,0.35)';
            }

            let typeColor = 'rgba(255,255,255,0.3)';
            if (isDrift) {
                typeColor = SEMBL.amber;
            } else if (isExcepted) {
                typeColor = 'rgba(201,161,90,0.5)';
            }

            return {
                id: n.id,
                position: { x: col * 260, y: idx * 70 + 40 },
                sourcePosition: Position.Right,
                targetPosition: Position.Left,
                data: {
                    label: (
                        <div style={{ fontFamily: SEMBL.mono, fontSize: '11px', color: 'rgba(255,255,255,0.8)' }}>
                            <div style={{
                                fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.05em',
                                color: typeColor, marginBottom: '2px', display: 'flex', gap: '6px', alignItems: 'center'
                            }}>
                                <span>{n.type}</span>
                                {isDrift && <span style={{ color: SEMBL.amber }}>drift</span>}
                                {isExcepted && <span style={{ color: 'rgba(201,161,90,0.5)' }}>exception</span>}
                            </div>
                            <div>{n.name}</div>
                        </div>
                    )
                },
                style: {
                    background: SEMBL.card,
                    border: `1px solid ${borderColor}`,
                    borderRadius: '5px',
                    padding: '6px 10px',
                    width: 220
                }
            };
        });
    }

    protected buildFlowEdges(): Edge[] {
        return this.specEdges.map((e, i) => {
            const forbids = e.type === 'forbids';
            return {
                id: `e${i}:${e.from}->${e.to}`,
                source: e.from,
                target: e.to,
                animated: false,
                label: e.type,
                labelStyle: { fontFamily: SEMBL.mono, fontSize: '9px', fill: 'rgba(255,255,255,0.35)' },
                style: {
                    stroke: forbids ? 'rgba(193,104,92,0.45)' : 'rgba(255,255,255,0.18)'
                }
            };
        });
    }

    protected render(): React.ReactNode {
        return <div style={{
            display: 'flex', flexDirection: 'column', height: '100%',
            background: SEMBL.editor, color: 'rgba(255,255,255,0.72)'
        }}>
            <div style={{
                display: 'flex', gap: '10px', alignItems: 'center',
                padding: '8px 12px', borderBottom: SEMBL.border, background: SEMBL.panel
            }}>
                <span style={{ fontFamily: SEMBL.mono, fontSize: '10px', color: 'rgba(255,255,255,0.4)' }}>
                    run {this.runId ?? '—'}
                </span>
                <button onClick={() => this.refresh()} style={{
                    fontFamily: SEMBL.sans, fontSize: '11px', padding: '4px 10px', borderRadius: '4px',
                    border: '1px solid rgba(255,255,255,0.14)', background: 'transparent',
                    color: 'rgba(255,255,255,0.65)', cursor: 'pointer'
                }}>reload</button>
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
                {this.loaded && this.specNodes.length === 0 &&
                    <p style={{ fontFamily: SEMBL.mono, fontSize: '12px', color: 'rgba(255,255,255,0.4)', padding: '16px' }}>
                        no specgraph found — run the loop once
                    </p>}
                {this.loaded && this.specNodes.length > 0 &&
                    <ReactFlow
                        nodes={this.buildFlowNodes()}
                        edges={this.buildFlowEdges()}
                        fitView
                        proOptions={{ hideAttribution: true }}
                        colorMode="dark"
                    >
                        <Background color="rgba(255,255,255,0.06)" gap={20} />
                    </ReactFlow>}
            </div>
        </div>;
    }
}
