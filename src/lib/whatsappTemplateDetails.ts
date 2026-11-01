/**
 * Normalize the two read-only Meta template detail response shapes.
 *
 * The staff template API returns a wrapped record with metaTemplateId,
 * templateName, and templateStatus. Other Meta endpoints expose native
 * id, name, and status fields. Consumers must never mistake an approved
 * template for UNKNOWN, or invent approval when those aliases disagree.
 */
export interface NormalizedWhatsAppTemplateDetail extends Record<string, unknown> {
  id: string;
  name: string;
  status: string;
  components: unknown[];
}

function record ( value: unknown ): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray( value )
    ? value as Record<string, unknown> : null;
}

function metaId ( value: unknown ): string | null {
  if ( typeof value === 'string' && /^[0-9]+$/.test( value ) ) return value;
  // Meta identifiers can exceed Number.MAX_SAFE_INTEGER. Do not round them.
  if ( typeof value === 'number' && Number.isSafeInteger( value ) && value > 0 ) return String( value );
  return null;
}

function nonEmptyText ( value: unknown ): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export function normalizeWhatsAppTemplateDetails (
  response: unknown, expectedId?: string,
): NormalizedWhatsAppTemplateDetail | null {
  const envelope = record( response );
  if ( !envelope ) return null;
  const raw = record( envelope.template ) || envelope;

  const nativeId = raw.id === undefined ? null : metaId( raw.id );
  const aliasId = raw.metaTemplateId === undefined ? null : metaId( raw.metaTemplateId );
  const id = nativeId || aliasId;
  if ( !id || ( raw.id !== undefined && !nativeId )
    || ( raw.metaTemplateId !== undefined && !aliasId )
    || ( nativeId && aliasId && nativeId !== aliasId )
    || ( expectedId !== undefined && id !== expectedId ) ) return null;

  const nativeName = raw.name === undefined ? null : nonEmptyText( raw.name );
  const aliasName = raw.templateName === undefined ? null : nonEmptyText( raw.templateName );
  const name = nativeName || aliasName;
  if ( !name || ( raw.name !== undefined && !nativeName )
    || ( raw.templateName !== undefined && !aliasName )
    || ( nativeName && aliasName && nativeName !== aliasName ) ) return null;

  const nativeStatus = raw.status === undefined ? null : nonEmptyText( raw.status )?.toUpperCase();
  const aliasStatus = raw.templateStatus === undefined ? null : nonEmptyText( raw.templateStatus )?.toUpperCase();
  const status = nativeStatus || aliasStatus;
  if ( !status || ( raw.status !== undefined && !nativeStatus )
    || ( raw.templateStatus !== undefined && !aliasStatus )
    || ( nativeStatus && aliasStatus && nativeStatus !== aliasStatus )
    || !Array.isArray( raw.components ) ) return null;

  return { ...raw, id, name, status, components: raw.components };
}
