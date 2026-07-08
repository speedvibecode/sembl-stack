import { CSSProperties } from 'react';

// The locked design system — exact values from docs/DESIGN-sembl-ide.md §1/§2
// (reference: docs/design/sembl-ide-design-reference.html). Build to it, don't
// restyle ad hoc: cyan means "factory alive", green/amber/red mean verdicts,
// mono means data. Nothing else carries color.
export const SEMBL = {
    cyan: '#7cd4df',
    green: '#7fae86',
    amber: '#c9a15a',
    red: '#c1685c',
    page: '#0b0d10',
    editor: '#0d1114',
    panel: '#101418',
    strip: '#0f1317',
    card: '#12171b',
    border: '1px solid rgba(255,255,255,0.07)',
    borderStrong: '1px solid rgba(255,255,255,0.08)',
    mono: "'IBM Plex Mono', Consolas, 'Courier New', monospace",
    sans: "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
};

export type VerdictTone = 'pass' | 'warn' | 'block' | 'neutral';

export function verdictTone(status?: string): VerdictTone {
    switch (status) {
        case 'PASS': return 'pass';
        case 'WARN': return 'warn';
        case 'BLOCK':
        case 'failed': return 'block';
        default: return 'neutral';
    }
}

const CHIP_TONES: { [t in VerdictTone]: { bg: string; fg: string; bd: string } } = {
    neutral: { bg: 'rgba(255,255,255,0.06)', fg: 'rgba(255,255,255,0.4)', bd: 'rgba(255,255,255,0.1)' },
    pass: { bg: 'rgba(127,174,134,0.12)', fg: SEMBL.green, bd: 'rgba(127,174,134,0.3)' },
    warn: { bg: 'rgba(201,161,90,0.12)', fg: SEMBL.amber, bd: 'rgba(201,161,90,0.3)' },
    block: { bg: 'rgba(193,104,92,0.14)', fg: SEMBL.red, bd: 'rgba(193,104,92,0.4)' }
};

export function gateChipStyle(tone: VerdictTone): CSSProperties {
    const c = CHIP_TONES[tone];
    return {
        fontFamily: SEMBL.mono, fontSize: '10px', fontWeight: 600, letterSpacing: '0.06em',
        padding: '3px 9px', borderRadius: '4px',
        background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
        whiteSpace: 'nowrap'
    };
}

export function tickColor(status?: string): string {
    switch (verdictTone(status)) {
        case 'pass': return 'rgba(127,174,134,0.65)';
        case 'warn': return SEMBL.amber;
        case 'block': return SEMBL.red;
        default: return 'rgba(255,255,255,0.15)';
    }
}

/** Run-tick fill+border for a run still executing (design step 2, DESIGN-sembl-ide.md §2
 * "run ticks"): transparent fill, 1.5px cyan border, soft-pulse — overrides the normal
 * verdict tick color/selection border for that one tick. */
export function runningTickStyle(): CSSProperties {
    return {
        background: 'transparent',
        border: `1.5px solid ${SEMBL.cyan}`,
        animation: 'sembl-soft-pulse 1.3s ease-in-out infinite'
    };
}

/** Inject IBM Plex + the three sanctioned keyframes once per window. */
export function ensureSemblDesign(): void {
    if (document.getElementById('sembl-design')) { return; }
    const link = document.createElement('link');
    link.id = 'sembl-fonts';
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap';
    document.head.appendChild(link);
    const style = document.createElement('style');
    style.id = 'sembl-design';
    style.textContent = `
@keyframes sembl-blink { 0%, 45% { opacity: 1; } 50%, 95% { opacity: 0; } 100% { opacity: 1; } }
@keyframes sembl-pulse-ring { 0% { box-shadow: 0 0 0 0 rgba(124,212,223,0.45); } 100% { box-shadow: 0 0 0 6px rgba(124,212,223,0); } }
@keyframes sembl-soft-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
#sembl-strip-host { position: absolute; top: 0; left: 0; right: 0; height: 32px; z-index: 5; }
#theia-app-shell { top: 32px !important; }
.sembl-factory-strip { width: 100%; height: 32px; min-height: 32px; }
.sembl-strip-guide:hover { color: ${SEMBL.cyan} !important; }
`;
    document.head.appendChild(style);
}
