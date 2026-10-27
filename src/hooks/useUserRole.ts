/**
 * useUserRole — reads the signed-in Cognito user's groups from the access token
 * and derives a role + whether they are a limited-access partner (customer).
 *
 * Admin/Operator/Viewer  → internal team (full app).
 * Partner                → onboarded business customer (limited: own account only).
 */
import { useEffect, useState } from 'react';
// Configures Amplify before this module's first Auth call; see lib/amplifyConfig.ts.
import '../lib/amplifyConfig';
import { fetchAuthSession } from 'aws-amplify/auth';

export type AppRole = 'Admin' | 'Operator' | 'Viewer' | 'Partner' | 'unknown';

export interface UserRole {
    role: AppRole;
    groups: string[];
    isPartner: boolean;   // limited-access customer
    isAdmin: boolean;     // internal full-access
    wabaId: string | null;
    loading: boolean;
}

export function useUserRole (): UserRole {
    const [ state, setState ] = useState<UserRole>( {
        role: 'unknown', groups: [], isPartner: false, isAdmin: false, wabaId: null, loading: true,
    } );

    useEffect( () => {
        let cancelled = false;
        ( async () => {
            try
            {
                const session = await fetchAuthSession();
                const payload: any = session.tokens?.accessToken?.payload || {};
                const idPayload: any = session.tokens?.idToken?.payload || {};
                const groups: string[] = payload[ 'cognito:groups' ] || idPayload[ 'cognito:groups' ] || [];
                const wabaId: string | null = idPayload[ 'custom:partner_waba_id' ] || null;

                const isAdmin = groups.includes( 'Admin' ) || groups.includes( 'Operator' );
                const isPartner = !isAdmin && groups.includes( 'Partner' );
                const role: AppRole = isAdmin
                    ? ( groups.includes( 'Admin' ) ? 'Admin' : 'Operator' )
                    : isPartner ? 'Partner' : ( groups.includes( 'Viewer' ) ? 'Viewer' : 'unknown' );

                if ( !cancelled ) setState( { role, groups, isPartner, isAdmin, wabaId, loading: false } );
            } catch
            {
                if ( !cancelled ) setState( { role: 'unknown', groups: [], isPartner: false, isAdmin: false, wabaId: null, loading: false } );
            }
        } )();
        return () => { cancelled = true; };
    }, [] );

    return state;
}

/** Routes a limited-access partner customer is allowed to open.
 *  The shared WhatsApp inbox is intentionally excluded until it is tenant-scoped,
 *  otherwise a customer would see platform-wide data. */
export const PARTNER_ALLOWED_PATHS = [
    '/workspace/engage/whatsapp/my-account',
    '/',
];

export function isPartnerAllowed ( pathname: string ): boolean {
    const p = pathname.replace( /\/$/, '' );
    return PARTNER_ALLOWED_PATHS.some( a => {
        const ap = a.replace( /\/$/, '' );
        return p === ap || p === ap + '/index';
    } );
}
