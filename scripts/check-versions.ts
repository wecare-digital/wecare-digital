/**
 * Version drift gate. Brief §60, requirements R1.
 *
 *   node scripts/check-versions.ts            report drift; exit 1 on any error finding
 *   node scripts/check-versions.ts --write     regenerate config/vendor-versions.json
 *   node scripts/check-versions.ts --json      machine-readable output
 *   node scripts/check-versions.ts --npm       additionally query the npm registry
 *
 * Runs under Node's native type stripping, so this file must use erasable syntax only:
 * no `enum`, no `namespace`, no parameter properties. Type annotations and `as` are fine.
 * That constraint is why it has no build step and no dependencies.
 *
 * What it does NOT do
 * -------------------
 * It does not reach Meta or Google. Those versions are established by reading vendor
 * documentation and by the live probes recorded in `docs/current-environment.md`, and a
 * scraper pretending to do that would produce a number nobody could trust. For those the
 * gate enforces the weaker but honest property: a lag must carry a written reason. `--npm`
 * is the exception, because the npm registry is a real machine-readable source of truth.
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';

import {
  VENDOR_VERSIONS,
  REJECTED_RUNTIMES,
  checkVersions,
  toJsonMirror,
  graphApiVersion,
  type DriftFinding,
} from '../packages/config/vendorVersions.ts';

const REPO_ROOT = resolve(import.meta.dirname, '..');
const JSON_MIRROR = resolve(REPO_ROOT, 'config/vendor-versions.json');

/** npm package name -> the key in VENDOR_VERSIONS it backs. Only genuinely checkable ones. */
const NPM_BACKED: Readonly<Record<string, string>> = {
  next: 'frontendFramework',
  typescript: 'typescript',
  'aws-cdk-lib': 'awsCdk',
  '@playwright/test': 'playwright',
};

interface Options {
  readonly write: boolean;
  readonly json: boolean;
  readonly npm: boolean;
}

function parseArgs(argv: readonly string[]): Options {
  return {
    write: argv.includes('--write'),
    json: argv.includes('--json'),
    npm: argv.includes('--npm'),
  };
}

/** Read the JSON mirror, or null when it does not exist yet. */
function readMirror(): string | null {
  try {
    return readFileSync(JSON_MIRROR, 'utf8');
  } catch {
    return null;
  }
}

function renderMirror(): string {
  return `${JSON.stringify(toJsonMirror(), null, 2)}\n`;
}

/**
 * Whether the generated JSON is in sync with the TypeScript source.
 *
 * Compared as exact text rather than by parsing, so a reformat is caught too: the file is
 * generated, and a hand edit to it is the drift this guards against.
 */
function mirrorState(): 'missing' | 'stale' | 'current' {
  const existing = readMirror();
  if (existing === null) return 'missing';
  return existing === renderMirror() ? 'current' : 'stale';
}

function writeMirror(): void {
  mkdirSync(dirname(JSON_MIRROR), { recursive: true });
  writeFileSync(JSON_MIRROR, renderMirror(), 'utf8');
}

/** Latest version on the npm registry, or null when the lookup fails. */
function npmLatest(pkg: string): string | null {
  try {
    const out = execFileSync('npm', ['view', pkg, 'version'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 30_000,
    });
    const value = out.trim();
    return value.length > 0 ? value : null;
  } catch {
    // Offline, or the package was unpublished. Not a drift failure: a network problem must
    // not fail a gate whose job is to report version policy.
    return null;
  }
}

interface NpmFinding {
  readonly pkg: string;
  readonly key: string;
  readonly recorded: string | null;
  readonly registry: string | null;
  readonly agrees: boolean;
}

/**
 * Check that `verifiedLatest` still matches the registry.
 *
 * This validates the *measurement*, not the configuration — it catches a
 * `verifiedLatest` that has gone stale since `verifiedOn`, which is the failure mode a
 * hand-maintained table always has.
 */
function checkNpm(): readonly NpmFinding[] {
  const out: NpmFinding[] = [];
  for (const [pkg, key] of Object.entries(NPM_BACKED)) {
    const entry = (VENDOR_VERSIONS as Readonly<Record<string, { verifiedLatest: string | null }>>)[key];
    const recorded = entry?.verifiedLatest ?? null;
    const registry = npmLatest(pkg);
    out.push({
      pkg,
      key,
      recorded,
      registry,
      agrees: registry === null || recorded === registry,
    });
  }
  return out;
}

/** `python3.12` style ids currently deployed, so a rejected runtime cannot slip in. */
function localRuntimeChecks(): readonly string[] {
  const problems: string[] = [];
  try {
    const nvmrc = readFileSync(resolve(REPO_ROOT, '.nvmrc'), 'utf8').trim();
    const configured = VENDOR_VERSIONS.nodeRuntime.configured;
    if (nvmrc !== configured) {
      problems.push(`.nvmrc says Node ${nvmrc} but vendorVersions says ${configured}`);
    }
  } catch {
    problems.push('.nvmrc is missing, so the Node major is unpinned');
  }

  // Graph version shape. graphApiVersion() throws on a malformed value, which is the
  // startup-validation requirement (R1.3) exercised here at gate time as well.
  try {
    graphApiVersion();
  } catch (error) {
    problems.push(error instanceof Error ? error.message : 'Graph version is malformed');
  }

  return problems;
}

function severityMark(severity: DriftFinding['severity']): string {
  if (severity === 'error') return 'FAIL';
  if (severity === 'warn') return 'WARN';
  return ' ok ';
}

function main(): number {
  const options = parseArgs(process.argv.slice(2));
  const findings = checkVersions();
  const runtimeProblems = localRuntimeChecks();

  if (options.write) {
    writeMirror();
  }
  const mirror = mirrorState();

  const npmFindings = options.npm ? checkNpm() : [];

  const errors =
    findings.filter((f) => f.severity === 'error').length +
    runtimeProblems.length +
    (mirror === 'current' ? 0 : 1) +
    npmFindings.filter((f) => !f.agrees).length;

  if (options.json) {
    process.stdout.write(
      `${JSON.stringify(
        { findings, runtimeProblems, mirror, npmFindings, errorCount: errors },
        null,
        2,
      )}\n`,
    );
    return errors > 0 ? 1 : 0;
  }

  const lines: string[] = ['Vendor version check', ''];
  for (const finding of findings) {
    const latest = finding.verifiedLatest ?? 'unmeasurable';
    lines.push(
      `  [${severityMark(finding.severity)}] ${finding.name}`,
      `          configured ${finding.configured}  latest ${latest}`,
    );
    if (finding.severity !== 'ok') {
      lines.push(`          ${finding.message}`);
    }
  }

  lines.push('', '  Rejected production runtimes');
  for (const runtime of REJECTED_RUNTIMES) {
    lines.push(`    ${runtime.id.padEnd(14)} ${runtime.reason}`);
  }

  lines.push('', `  JSON mirror (config/vendor-versions.json): ${mirror}`);
  if (mirror !== 'current') {
    lines.push('    regenerate with: node scripts/check-versions.ts --write');
  }

  if (npmFindings.length > 0) {
    lines.push('', '  npm registry cross-check of verifiedLatest');
    for (const finding of npmFindings) {
      const state = finding.registry === null ? 'lookup failed' : finding.agrees ? 'agrees' : 'STALE';
      lines.push(
        `    ${finding.pkg.padEnd(18)} recorded ${String(finding.recorded).padEnd(10)} ` +
          `registry ${String(finding.registry).padEnd(10)} ${state}`,
      );
    }
  }

  if (runtimeProblems.length > 0) {
    lines.push('', '  Runtime/config problems');
    for (const problem of runtimeProblems) {
      lines.push(`    FAIL ${problem}`);
    }
  }

  lines.push(
    '',
    errors > 0
      ? `  RESULT: ${errors} error finding(s). Warnings are recorded lags with reasons and do not fail.`
      : '  RESULT: no error findings.',
    '',
  );

  process.stdout.write(lines.join('\n'));
  return errors > 0 ? 1 : 0;
}

process.exit(main());
