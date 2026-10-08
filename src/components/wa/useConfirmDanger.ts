/**
 * useConfirmDanger (Part 5) — thin wrapper over the app ConfirmContext that
 * enforces a typed-to-confirm destructive dialog for delete / unsubscribe /
 * deprecate / publish / refund / replay / access-change / secret-update.
 */
import { useConfirm } from '../../contexts/ConfirmContext';
import React from 'react';

export type DangerAction =
    | 'delete' | 'unsubscribe' | 'deprecate' | 'publish'
    | 'refund' | 'replay' | 'access-change' | 'secret-update';

const VERB: Record<DangerAction, string> = {
    delete: 'DELETE', unsubscribe: 'UNSUBSCRIBE', deprecate: 'DEPRECATE', publish: 'PUBLISH',
    refund: 'REFUND', replay: 'REPLAY', 'access-change': 'CONFIRM', 'secret-update': 'ROTATE',
};

export function useConfirmDanger () {
    const confirm = useConfirm();
    // confirmText is overridable because the button label and the typed verb are not always
    // the same word: a "Clean ALL 1,279 posts?" dialog types CLEAN and must not sit above a
    // button reading DELETE. The ?? default leaves all existing consumers unchanged.
    return ( action: DangerAction, message: React.ReactNode, opts?: { confirmInput?: string; title?: string; confirmText?: string } ) =>
        confirm( {
            title: opts?.title || `Confirm ${action}`,
            message,
            danger: true,
            confirmInput: opts?.confirmInput ?? VERB[ action ],
            confirmText: opts?.confirmText ?? VERB[ action ],
        } );
}
