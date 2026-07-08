import * as React from 'react';
import { useState } from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { GuideSuggestion, FactoryService } from '../common/factory-protocol';
import { SEMBL, ensureSemblDesign } from './sembl-design';

export const GUIDE_WIDGET_ID = 'sembl-guide';

type Executor = 'claude' | 'opencode' | 'mock';

interface TranscriptEntry {
    role: 'user' | 'guide';
    text: string;
    suggestions?: GuideSuggestion[];
    /** plain guide lines render amber (fallback/error) unless marked ok. */
    tone?: 'ok';
    fallback?: boolean;
}

/** One suggestion row — its own function component so the "copy" -> "copied" flip
 * is local state and never forces the whole (transcript-holding) widget to re-render. */
function SuggestionRow({ suggestion }: { suggestion: GuideSuggestion }): React.ReactElement {
    const [copied, setCopied] = useState(false);
    return <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' }}>
        <span style={{
            fontFamily: SEMBL.mono, fontSize: '11px', color: 'rgba(255,255,255,0.85)',
            background: SEMBL.editor, padding: '1px 6px', borderRadius: '3px'
        }}>{suggestion.command}</span>
        <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.55)' }}>{suggestion.why}</span>
        <div style={{ flex: 1 }} />
        <button
            onClick={() => {
                navigator.clipboard.writeText(suggestion.command);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
            }}
            style={{
                fontFamily: SEMBL.sans, fontSize: '10px', padding: '2px 8px', borderRadius: '4px',
                border: '1px solid rgba(255,255,255,0.18)', background: 'transparent',
                color: 'rgba(255,255,255,0.65)', cursor: 'pointer'
            }}
        >{copied ? 'copied' : 'copy'}</button>
    </div>;
}

// The guide panel — a read-only advisor for OPERATING sembl-stack (design step 6d).
// THIN RENDERER per O1: the bounded LLM call (O9) lives in sembl_stack/factory_guide.py;
// this widget only spawns the existing `explain --json` CLI command (via FactoryService)
// and renders the fixed {answer, suggestions, fallback} reply. It writes nothing — a
// suggestion is a command string the human may copy, never something this panel executes.
@injectable()
export class GuideWidget extends ReactWidget {

    static readonly ID = GUIDE_WIDGET_ID;
    static readonly LABEL = 'Guide';

    @inject(FactoryService) protected readonly factoryService: FactoryService;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;

    protected repoPath = '';
    protected transcript: TranscriptEntry[] = [];
    protected input = '';
    protected executor: Executor = 'claude';
    protected busy = false;

    @postConstruct()
    protected init(): void {
        this.id = GuideWidget.ID;
        this.title.label = GuideWidget.LABEL;
        this.title.caption = 'ask about your factory';
        this.title.closable = true;
        this.title.iconClass = 'fa fa-question-circle';
        ensureSemblDesign();
        this.bootstrap();
    }

    protected async bootstrap(): Promise<void> {
        if (!this.repoPath) {
            const roots = await this.workspaceService.roots;
            if (roots.length > 0) {
                // URI path form is '/c:/Users/…' on Windows — display it drive-first.
                const p = roots[0].resource.path.toString();
                const m = /^\/([a-zA-Z]:\/.*)$/.exec(p);
                this.repoPath = m ? m[1] : p;
            }
        }
        this.update();
    }

    protected async ask(): Promise<void> {
        const question = this.input.trim();
        if (!question || this.busy) { return; }
        this.transcript.push({ role: 'user', text: question });
        this.input = '';
        this.busy = true;
        this.update();
        try {
            const reply = await this.factoryService.guideAsk(this.repoPath, question, this.executor);
            this.transcript.push({
                role: 'guide', text: reply.answer, suggestions: reply.suggestions, fallback: reply.fallback
            });
        } catch (e) {
            this.transcript.push({ role: 'guide', text: `error: ${e}` });
        } finally {
            this.busy = false;
            this.update();
        }
    }

    protected textAreaStyle(): React.CSSProperties {
        return {
            width: '100%', fontFamily: SEMBL.mono, fontSize: '11px', resize: 'vertical',
            background: SEMBL.editor, color: 'rgba(255,255,255,0.8)',
            border: SEMBL.border, borderRadius: '4px', padding: '6px 8px', outline: 'none',
            boxSizing: 'border-box'
        };
    }

    protected render(): React.ReactNode {
        return <div style={{
            display: 'flex', flexDirection: 'column', height: '100%',
            background: SEMBL.panel, color: 'rgba(255,255,255,0.75)',
            fontFamily: SEMBL.mono, fontSize: '12px'
        }}>
            <div style={{
                display: 'flex', flexDirection: 'column', gap: '2px', padding: '10px 12px',
                borderBottom: SEMBL.border, flex: 'none'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{
                        fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase',
                        color: 'rgba(255,255,255,0.4)'
                    }}>guide — ask about your factory</span>
                    <div style={{ flex: 1 }} />
                    <select
                        value={this.executor}
                        onChange={e => { this.executor = e.target.value as Executor; this.update(); }}
                        style={{
                            fontFamily: SEMBL.mono, fontSize: '11px', background: SEMBL.editor,
                            color: 'rgba(255,255,255,0.75)', border: SEMBL.border, borderRadius: '4px',
                            padding: '3px 6px'
                        }}
                    >
                        <option value="claude">claude</option>
                        <option value="opencode">opencode</option>
                        <option value="mock">mock</option>
                    </select>
                </div>
                <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>
                    read-only advisor — it can explain and suggest, never act
                </span>
            </div>

            <div style={{ flex: 1, overflow: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {this.transcript.length === 0 &&
                    <p style={{ color: 'rgba(255,255,255,0.35)' }}>
                        ask anything about operating sembl — why a run blocked, what a drift
                        finding means, what to do next.
                    </p>}
                {this.transcript.map((entry, i) => this.renderEntry(entry, i))}
                {this.busy && <p style={{ color: 'rgba(255,255,255,0.4)' }}>thinking…</p>}
            </div>

            <div style={{ flex: 'none', display: 'flex', gap: '8px', padding: '10px 12px', borderTop: SEMBL.border }}>
                <textarea
                    rows={2}
                    value={this.input}
                    placeholder="ask about your factory…"
                    onChange={e => { this.input = e.target.value; this.update(); }}
                    onKeyDown={e => {
                        if (e.key === 'Enter' && e.ctrlKey) {
                            e.preventDefault();
                            this.ask();
                        }
                    }}
                    style={{ ...this.textAreaStyle(), flex: 1 }}
                />
                <button
                    onClick={() => this.ask()}
                    disabled={this.busy || !this.input.trim()}
                    style={{
                        fontFamily: SEMBL.sans, fontSize: '12px', fontWeight: 600,
                        padding: '8px 16px', borderRadius: '5px', border: 'none',
                        background: SEMBL.cyan, color: '#0d1114', flex: 'none',
                        cursor: (this.busy || !this.input.trim()) ? 'not-allowed' : 'pointer',
                        opacity: (this.busy || !this.input.trim()) ? 0.6 : 1
                    }}
                >ask</button>
            </div>
        </div>;
    }

    protected renderEntry(entry: TranscriptEntry, i: number): React.ReactNode {
        if (entry.role === 'user') {
            return <div key={i} style={{
                alignSelf: 'flex-end', maxWidth: '85%', padding: '8px 10px',
                background: SEMBL.editor, border: SEMBL.border, borderRadius: '6px',
                color: 'rgba(255,255,255,0.85)'
            }}>{entry.text}</div>;
        }
        if (entry.fallback || entry.text.startsWith('error:')) {
            return <div key={i} style={{ fontSize: '12px', color: SEMBL.amber }}>
                {entry.fallback
                    ? 'guide unavailable — model call failed or unparseable. check that the executor CLI is logged in.'
                    : entry.text}
            </div>;
        }
        return <div key={i} style={{
            padding: '10px 12px', background: SEMBL.card, border: SEMBL.borderStrong,
            borderRadius: '6px', display: 'flex', flexDirection: 'column', gap: '8px'
        }}>
            <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.8)' }}>{entry.text}</div>
            {entry.suggestions && entry.suggestions.length > 0 &&
                <div style={{
                    padding: '8px 10px', border: SEMBL.border, borderRadius: '4px',
                    display: 'flex', flexDirection: 'column', gap: '6px'
                }}>
                    <div style={{
                        fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em', color: SEMBL.cyan
                    }}>try:</div>
                    {entry.suggestions.map((s, si) => <SuggestionRow key={si} suggestion={s} />)}
                </div>}
        </div>;
    }
}
