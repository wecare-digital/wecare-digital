/**
 * WhatsApp media helpers — single source of truth.
 *
 * Consolidates the MIME map, per-type size limits, category classifier, file-input
 * accept string, and size validation that were previously duplicated across
 * src/api/client.ts and src/pages/workspace/engage/whatsapp/inbox.tsx (and elsewhere).
 *
 * The live consumers are now src/api/client.ts and src/pages/workspace/engage/inbox/index.tsx.
 * whatsapp/inbox.tsx is named above because that is where the duplication was, but it has since
 * collapsed into a wrapper over the omnichannel inbox and imports nothing from here.
 *
 * Limits and supported types follow the WhatsApp Cloud API "Supported Media Types".
 */

export type WaMediaCategory = 'document' | 'image' | 'video' | 'audio' | 'sticker';

/** Meta WhatsApp Cloud API media size limits, by category (bytes). */
export const WA_MEDIA_LIMITS: Record<WaMediaCategory, number> = {
    document: 100 * 1024 * 1024, // 100 MB
    image: 5 * 1024 * 1024,      // 5 MB
    video: 16 * 1024 * 1024,     // 16 MB
    audio: 16 * 1024 * 1024,     // 16 MB
    sticker: 500 * 1024,         // 500 KB
};

/** Extension → WhatsApp-supported MIME type. Browsers sometimes report an empty
 *  File.type (e.g. .amr, occasionally .webp/.3gp), so we infer from the name. */
const EXT_TO_MIME: Record<string, string> = {
    jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp',
    mp4: 'video/mp4', '3gp': 'video/3gpp', '3gpp': 'video/3gpp',
    aac: 'audio/aac', amr: 'audio/amr', mp3: 'audio/mpeg', m4a: 'audio/mp4', ogg: 'audio/ogg', opus: 'audio/ogg',
    pdf: 'application/pdf', txt: 'text/plain',
    doc: 'application/msword',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    xls: 'application/vnd.ms-excel',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ppt: 'application/vnd.ms-powerpoint',
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
};

/** Infer a WhatsApp-supported MIME type from a filename extension. */
export function inferMimeFromName ( name: string ): string {
    const ext = ( name.split( '.' ).pop() || '' ).toLowerCase();
    return EXT_TO_MIME[ ext ] || 'application/octet-stream';
}

/** Resolve a MIME type to its WhatsApp media category for limit lookup. */
export function waMediaCategory ( mime: string ): WaMediaCategory {
    const m = ( mime || '' ).toLowerCase();
    if ( m === 'image/webp' ) return 'sticker';
    if ( m.startsWith( 'image/' ) ) return 'image';
    if ( m.startsWith( 'video/' ) ) return 'video';
    if ( m.startsWith( 'audio/' ) ) return 'audio';
    return 'document';
}

/** Accept string for <input type="file"> covering all WhatsApp-supported media. */
export const WA_ACCEPT_STRING = Array.from( new Set( Object.values( EXT_TO_MIME ) ) ).join( ',' );

/** Human-readable byte size (e.g. "5MB", "500KB", "1.3MB"). */
export function formatBytes ( bytes: number ): string {
    if ( bytes >= 1024 * 1024 )
    {
        const mb = bytes / ( 1024 * 1024 );
        return `${Number.isInteger( mb ) ? mb.toFixed( 0 ) : mb.toFixed( 1 )}MB`;
    }
    return `${( bytes / 1024 ).toFixed( 0 )}KB`;
}

export interface WaSizeValidation {
    ok: boolean;
    category: WaMediaCategory;
    limit: number;
    message?: string;
}

/**
 * Validate a file against Meta's per-type size limit.
 * Pass an explicit mime when File.type may be empty (use inferMimeFromName).
 */
export function validateWaMediaSize ( file: { size: number; name?: string; type?: string }, mime?: string ): WaSizeValidation {
    const resolved = mime || file.type || ( file.name ? inferMimeFromName( file.name ) : 'application/octet-stream' );
    const category = waMediaCategory( resolved );
    const limit = WA_MEDIA_LIMITS[ category ];
    if ( file.size > limit )
    {
        return {
            ok: false,
            category,
            limit,
            message: `${category} file is ${formatBytes( file.size )} — exceeds WhatsApp's ${formatBytes( limit )} limit for ${category}s. Please use a smaller file.`,
        };
    }
    return { ok: true, category, limit };
}
