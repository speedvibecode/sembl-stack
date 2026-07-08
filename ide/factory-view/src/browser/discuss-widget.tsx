import * as React from 'react';
import { inject, injectable, postConstruct } from '@theia/core/shared/inversify';
import { ReactWidget } from '@theia/core/lib/browser';
import { WorkspaceService } from '@theia/workspace/lib/browser';
import { DiscussProposal, FactoryService } from '../common/factory-protocol';
import { SEMBL, ensureSemblDesign } from './sembl-design';

export const DISCUSS_WIDGET_ID = 'sembl-discuss';

type Executor = 'claude' | 'opencode' | 'mock';

interface TranscriptEntry {
    role: 'user' | 'sembl';
    text: string;
    proposal?: DiscussProposal;
    /** plain sembl lines render amber (warnings/errors) unless marked ok. */
    tone?: 'ok';
}

// The discuss panel — a side-chat for planning a spec (design step 6b). THIN RENDERER
// per O1: every judgment call (the bounded LLM parse, the fixed-schema proposal, the
// deterministic write) lives in sembl_stack/discuss.py; this widget only spawns the
// existing `discuss` / `discuss-confirm` CLI commands (via FactoryService) and renders
// the proposal for a human to edit before confirming. The LLM never touches the gate.
@injectable()
export class DiscussWidget extends ReactWidget {

    static readonly ID = DISCUSS_WIDGET_ID;
    static readonly LABEL = 'Discuss';

    @inject(FactoryService) protected readonly factoryService: FactoryService;
    @inject(WorkspaceService) protected readonly workspaceService: WorkspaceService;

    protected repoPath = '';
    protected transcript: TranscriptEntry[] = [];
    protected input = '';
    protected executor: Executor = 'claude';
    protected busy = false;

    // The proposal currently under review — editable fields split out so the textareas
    // can be freely typed into without re-deriving from `proposal` on every keystroke.
    protected proposal: DiscussProposal | undefined;
    protected editTaskText = '';
    protected editEditablePaths = '';
    protected editForbiddenAreas = '';

    @postConstruct()
    protected init(): void {
        this.id = DiscussWidget.ID;
        this.title.label = DiscussWidget.LABEL;
        this.title.caption = 'plan a task in plain english';
        this.title.closable = true;
        this.title.iconClass = 'fa fa-comments';
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

    /** Build the userText for the next bounded parse. Each round is still ONE bounded
     * call — a prior round's clarifying questions + this round's answer are folded into
     * a single prompt, never a second engine entry point. */
    protected buildUserText(): string {
        const answer = this.input.trim();
        const prior = this.transcript.length > 0
            ? this.transcript[this.transcript.length - 1].proposal
            : undefined;
        if (prior && !prior.fallback && prior.clarifyingQuestions.length > 0) {
            // The original request must survive rounds where the model returned only
            // questions (empty taskText), and the single free-text reply answers the
            // question block as a whole — not each question separately.
            const original = this.transcript.find(t => t.role === 'user')?.text ?? '';
            return [
                original && `Request: ${original}`,
                prior.taskText && `Current draft task: ${prior.taskText}`,
                `Open questions:\n${prior.clarifyingQuestions.map(q => `- ${q}`).join('\n')}`,
                `Answers from the human: ${answer}`
            ].filter(Boolean).join('\n');
        }
        return answer;
    }

    protected async propose(): Promise<void> {
        const text = this.input.trim();
        if (!text || this.busy) { return; }
        const userText = this.buildUserText();
        this.transcript.push({ role: 'user', text });
        this.input = '';
        this.busy = true;
        this.update();
        try {
            const proposal = await this.factoryService.discussPropose(
                this.repoPath, userText, this.executor);
            this.transcript.push({ role: 'sembl', text: '', proposal });
            this.proposal = proposal;
            this.editTaskText = proposal.taskText;
            this.editEditablePaths = proposal.editablePaths.join('\n');
            this.editForbiddenAreas = proposal.forbiddenAreas.join('\n');
        } catch (e) {
            this.transcript.push({ role: 'sembl', text: `error: ${e}` });
        } finally {
            this.busy = false;
            this.update();
        }
    }

    protected async confirm(): Promise<void> {
        if (!this.proposal || this.busy || !this.editTaskText.trim()) { return; }
        this.busy = true;
        this.update();
        const edited: DiscussProposal = {
            ...this.proposal,
            taskText: this.editTaskText.trim(),
            editablePaths: this.splitLines(this.editEditablePaths),
            forbiddenAreas: this.splitLines(this.editForbiddenAreas)
        };
        try {
            const result = await this.factoryService.discussConfirm(this.repoPath, edited);
            if (result.ok) {
                this.transcript.push({
                    role: 'sembl',
                    text: 'wrote task.yaml + bounds.json — run it from the factory view',
                    tone: 'ok'
                });
                this.proposal = undefined;
            } else {
                this.transcript.push({ role: 'sembl', text: result.message || 'confirm failed' });
            }
        } catch (e) {
            this.transcript.push({ role: 'sembl', text: `error: ${e}` });
        } finally {
            this.busy = false;
            this.update();
        }
    }

    protected discard(): void {
        this.proposal = undefined;
        this.update();
    }

    protected splitLines(text: string): string[] {
        return text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    }

    protected labelStyle(): React.CSSProperties {
        return {
            fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase',
            color: 'rgba(255,255,255,0.35)', marginBottom: '4px'
        };
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
                display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 12px',
                borderBottom: SEMBL.border, flex: 'none'
            }}>
                <span style={{
                    fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase',
                    color: 'rgba(255,255,255,0.4)'
                }}>discuss — plan a task</span>
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

            <div style={{ flex: 1, overflow: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {this.transcript.length === 0 &&
                    <p style={{ color: 'rgba(255,255,255,0.35)' }}>
                        describe what you want in plain english below — sembl will propose a
                        task, editable paths, and anything worth clarifying.
                    </p>}
                {this.transcript.map((entry, i) => this.renderEntry(entry, i))}
                {this.busy && <p style={{ color: 'rgba(255,255,255,0.4)' }}>thinking…</p>}
            </div>

            {this.proposal && <div style={{
                flex: 'none', padding: '12px', borderTop: SEMBL.borderStrong,
                display: 'flex', flexDirection: 'column', gap: '10px', background: SEMBL.card
            }}>
                <div>
                    <div style={this.labelStyle()}>task</div>
                    <textarea rows={3} style={this.textAreaStyle()}
                        value={this.editTaskText}
                        onChange={e => { this.editTaskText = e.target.value; this.update(); }} />
                </div>
                <div>
                    <div style={this.labelStyle()}>editable paths</div>
                    <textarea rows={3} style={this.textAreaStyle()}
                        value={this.editEditablePaths}
                        onChange={e => { this.editEditablePaths = e.target.value; this.update(); }} />
                </div>
                <div>
                    <div style={this.labelStyle()}>forbidden areas</div>
                    <textarea rows={2} style={this.textAreaStyle()}
                        value={this.editForbiddenAreas}
                        onChange={e => { this.editForbiddenAreas = e.target.value; this.update(); }} />
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                        onClick={() => this.confirm()}
                        disabled={this.busy || !this.editTaskText.trim()}
                        style={{
                            fontFamily: SEMBL.sans, fontSize: '12px', fontWeight: 600,
                            padding: '8px 16px', borderRadius: '5px', border: 'none',
                            background: SEMBL.cyan, color: '#0d1114',
                            cursor: (this.busy || !this.editTaskText.trim()) ? 'not-allowed' : 'pointer',
                            opacity: (this.busy || !this.editTaskText.trim()) ? 0.6 : 1
                        }}
                    >confirm → task.yaml</button>
                    <button
                        onClick={() => this.discard()}
                        disabled={this.busy}
                        style={{
                            fontFamily: SEMBL.sans, fontSize: '12px', padding: '8px 16px',
                            borderRadius: '5px', border: '1px solid rgba(255,255,255,0.18)',
                            background: 'transparent', color: 'rgba(255,255,255,0.65)',
                            cursor: this.busy ? 'not-allowed' : 'pointer'
                        }}
                    >discard</button>
                </div>
            </div>}

            <div style={{ flex: 'none', display: 'flex', gap: '8px', padding: '10px 12px', borderTop: SEMBL.border }}>
                <textarea
                    rows={2}
                    value={this.input}
                    placeholder="what do you want to build or change?"
                    onChange={e => { this.input = e.target.value; this.update(); }}
                    onKeyDown={e => {
                        if (e.key === 'Enter' && e.ctrlKey) {
                            e.preventDefault();
                            this.propose();
                        }
                    }}
                    style={{ ...this.textAreaStyle(), flex: 1 }}
                />
                <button
                    onClick={() => this.propose()}
                    disabled={this.busy || !this.input.trim()}
                    style={{
                        fontFamily: SEMBL.sans, fontSize: '12px', fontWeight: 600,
                        padding: '8px 16px', borderRadius: '5px', border: 'none',
                        background: SEMBL.cyan, color: '#0d1114', flex: 'none',
                        cursor: (this.busy || !this.input.trim()) ? 'not-allowed' : 'pointer',
                        opacity: (this.busy || !this.input.trim()) ? 0.6 : 1
                    }}
                >propose</button>
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
        if (entry.proposal) {
            const p = entry.proposal;
            return <div key={i} style={{
                padding: '10px 12px', background: SEMBL.card, border: SEMBL.borderStrong,
                borderRadius: '6px', display: 'flex', flexDirection: 'column', gap: '8px'
            }}>
                {p.fallback &&
                    <div style={{ color: SEMBL.amber, fontSize: '11px' }}>
                        model unavailable or unparseable — fill the proposal in manually
                    </div>}
                {p.taskText &&
                    <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.85)' }}>{p.taskText}</div>}
                {p.editablePaths.length > 0 &&
                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.55)' }}>
                        editable: {p.editablePaths.join(', ')}
                    </div>}
                {p.forbiddenAreas.length > 0 &&
                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.55)' }}>
                        forbidden: {p.forbiddenAreas.join(', ')}
                    </div>}
                {p.clarifyingQuestions.length > 0 &&
                    <div style={{
                        padding: '8px 10px', border: `1px solid ${SEMBL.amber}`, borderRadius: '4px',
                        background: 'rgba(201,161,90,0.08)'
                    }}>
                        <div style={{ color: SEMBL.amber, fontSize: '10px', textTransform: 'uppercase', marginBottom: '4px' }}>
                            sembl asks:
                        </div>
                        {p.clarifyingQuestions.map((q, qi) =>
                            <div key={qi} style={{ fontSize: '12px', color: 'rgba(255,255,255,0.8)' }}>{q}</div>)}
                    </div>}
            </div>;
        }
        return <div key={i} style={{
            fontSize: '12px', color: entry.tone === 'ok' ? SEMBL.cyan : SEMBL.amber
        }}>{entry.text}</div>;
    }
}
