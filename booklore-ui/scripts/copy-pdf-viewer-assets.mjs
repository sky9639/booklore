import { cp, mkdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');

const sourceDir = path.join(projectRoot, 'node_modules', 'ngx-extended-pdf-viewer', 'assets');
const targetDir = path.join(projectRoot, 'dist', 'booklore', 'browser', 'assets', 'pdf-viewer');

await rm(targetDir, { recursive: true, force: true });
await mkdir(path.dirname(targetDir), { recursive: true });
await cp(sourceDir, targetDir, { recursive: true, force: true });

console.log(`Copied ngx-extended-pdf-viewer assets to ${targetDir}`);
