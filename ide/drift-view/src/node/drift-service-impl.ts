import { injectable } from '@theia/core/shared/inversify';
import * as fs from 'fs';
import * as path from 'path';
import { DriftFinding, DriftService } from '../common/drift-protocol';

interface DriftStateFile {
    findings?: {
        [key: string]: {
            finding: DriftFinding;
            acknowledged?: boolean;
        };
    };
}

@injectable()
export class DriftServiceImpl implements DriftService {

    async getPending(repoPath: string): Promise<DriftFinding[]> {
        const statePath = path.join(repoPath, '.sembl', 'drift-state.json');
        let data: DriftStateFile;
        try {
            data = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
        } catch {
            return [];
        }
        const findings: DriftFinding[] = [];
        for (const entry of Object.values(data.findings || {})) {
            if (!entry.acknowledged) {
                findings.push(entry.finding);
            }
        }
        return findings;
    }
}
