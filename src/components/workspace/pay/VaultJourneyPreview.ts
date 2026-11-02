/**
 * Read-only adapter for historical Vault journey metadata.
 *
 * The sender, payment state and approved Meta templates are authoritative.
 * This file never controls dispatch or re-enables the retired ready_offer step.
 * The legacy SystemConfig row is for display ONLY and may be stale.
 */
export interface VaultRegistryStep {
  role: string;
  templateName: string;
  templateId: string;
}
export interface VaultRegistryJourney {
  journeyId: string;
  steps: VaultRegistryStep[];
}

const isObject = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v);

export function parseVaultJourney(raw: unknown): VaultRegistryJourney | null {
  let source = raw;
  if (typeof source === 'string') {
    try { source = JSON.parse(source) as unknown; }
    catch { return null; }
  }
  if (!isObject(source)) return null;
  // SystemConfig responses may wrap configValue or config in a nested object.
  let candidate: unknown = source;
  if (typeof source.configValue === 'string' || isObject(source.configValue)) {
    candidate = source.configValue;
  } else if (isObject(source.config)) {
    candidate = source.config;
  }
  if (typeof candidate === 'string') {
    try { candidate = JSON.parse(candidate) as unknown; }
    catch { return null; }
  }
  if (!isObject(candidate)) return null;
  const rows = Array.isArray(candidate.steps) ? candidate.steps : [];
  const steps: VaultRegistryStep[] = rows
    .filter(isObject)
    .map(step => ({
      role: typeof step.role === 'string' ? step.role : '',
      templateName: typeof step.templateName === 'string' ? step.templateName : '',
      templateId: typeof step.templateId === 'string' ? step.templateId : '',
    }))
    // No "Unlock Vault" chooser. The retired V1 offer is never a live stage.
    .filter(step => step.role !== 'ready_offer' && !!step.role);
  return {
    journeyId: typeof candidate.journeyId === 'string' ? candidate.journeyId : '',
    steps,
  };
}
