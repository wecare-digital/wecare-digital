/**
 * Two controls that were UNCONTROLLED, and the one regression that converting them could cause.
 *
 * `engage/meta-agent`'s Audience picker and `engage/whatsapp/flow-responses`' per-row status
 * picker both used React's uncontrolled default attribute: a seed value, an onChange that
 * saved, and no state variable behind either. A native element keeps the operator's choice
 * across a parent re-render by itself. A controlled ui/Select does not - and BOTH sites call a
 * reload immediately after the save, so a `value` pointed at the fetched object would snap the
 * control back to whatever the server last said. That is silent and it is wrong twice over:
 * while the request is in flight, and permanently when it fails.
 *
 * So each site gained its own `useState`, with the setter running BEFORE the save. These tests
 * drive the save path with a server that keeps answering with the OLD value, which is the exact
 * shape the snap-back needs, and assert the control still shows what was chosen.
 *
 * Both are workspace routes, so there is no browser evidence for either of them anywhere in
 * this task - jsdom is the only automated check these two controls get.
 */
import React from 'react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock( '../components/Layout', () => ( { default: ( { children }: { children: React.ReactNode } ) => <div>{ children }</div> } ) );
vi.mock( '../components/SEO', () => ( {
    default: () => null,
    PAGE_SEO: {},
} ) );

const toastSuccess = vi.fn();
const toastError = vi.fn();
/*
 * ONE object, not a fresh one per call, and that is load-bearing rather than tidiness.
 * flow-responses' reload effect depends on `loadSubmissions`, which depends on `toast` - so a
 * mock that returned a new object every render would change the callback's identity every
 * render and re-fire the effect forever. The reload count below would then be meaningless.
 */
const toast = { success: toastSuccess, error: toastError, info: vi.fn(), warning: vi.fn() };
vi.mock( '../contexts/ToastContext', () => ( { useToastContext: () => toast } ) );
vi.mock( '../contexts/ConfirmContext', () => ( { useConfirm: () => vi.fn().mockResolvedValue( true ) } ) );

vi.mock( 'aws-amplify/auth', () => ( {
    fetchAuthSession: vi.fn().mockResolvedValue( { tokens: { accessToken: { toString: () => 't' } } } ),
} ) );

const listFlowSubmissions = vi.fn();
const updateSubmissionStatus = vi.fn();

vi.mock( '../api/client', async importOriginal => ( {
    ...await importOriginal<typeof import( '../api/client' )>(),
    listFlowRegistry: vi.fn().mockResolvedValue( [] ),
    listSubmitRequests: vi.fn().mockResolvedValue( [] ),
    listFlowLogs: vi.fn().mockResolvedValue( [] ),
    listFlowSubmissions: ( ...a: unknown[] ) => listFlowSubmissions( ...a ),
    updateSubmissionStatus: ( ...a: unknown[] ) => updateSubmissionStatus( ...a ),
} ) );

import FlowResponsesPage from '../pages/workspace/engage/whatsapp/flow-responses';
import MetaAgentPage from '../pages/workspace/engage/meta-agent/index';

beforeEach( () => {
    vi.clearAllMocks();
} );

afterEach( () => {
    vi.unstubAllGlobals();
} );

describe( 'flow-responses per-row status survives the refresh that follows the save', () => {
    /**
     * The list ALWAYS answers `open`, which is what a slow write, a read replica or a failed
     * save all look like from the browser. Before the state addition the cell would read "Open"
     * again the moment this resolved.
     */
    const SUBMISSION = {
        submissionId: 'sub-1', submissionNumber: 'WD-SR-1', flowCode: '01.WD_SR',
        phone: '+918100640044', subject: 'A thing', status: 'open', paymentStatus: 'none',
        paymentAmount: 0, createdAt: '2026-10-06T09:00:00Z',
    };

    it( 'keeps the chosen status after the list reloads with the old one', async () => {
        listFlowSubmissions.mockResolvedValue( [ SUBMISSION ] );
        updateSubmissionStatus.mockResolvedValue( true );
        render( <FlowResponsesPage embedded /> );

        const control = await screen.findByRole( 'combobox', { name: 'Update status' } );
        expect( control ).toHaveTextContent( 'Open' );

        fireEvent.click( control );
        fireEvent.click( screen.getByRole( 'option', { name: 'Resolved' } ) );

        await waitFor( () => expect( updateSubmissionStatus ).toHaveBeenCalledWith( 'sub-1', 'resolved' ) );
        // The refresh has been asked for and has answered `open` again.
        await waitFor( () => expect( listFlowSubmissions ).toHaveBeenCalledTimes( 2 ) );
        expect( screen.getByRole( 'combobox', { name: 'Update status' } ) ).toHaveTextContent( 'Resolved' );
    } );

    it( 'keeps the chosen status even when the save fails outright', async () => {
        listFlowSubmissions.mockResolvedValue( [ SUBMISSION ] );
        updateSubmissionStatus.mockRejectedValue( new Error( 'Update failed' ) );
        render( <FlowResponsesPage embedded /> );

        const control = await screen.findByRole( 'combobox', { name: 'Update status' } );
        fireEvent.click( control );
        fireEvent.click( screen.getByRole( 'option', { name: 'Closed' } ) );

        await waitFor( () => expect( toastError ).toHaveBeenCalledWith( 'Update failed' ) );
        // The operator sees what they picked, and the error beside it - not a control that
        // quietly reverted and left them guessing which value the server now holds.
        expect( screen.getByRole( 'combobox', { name: 'Update status' } ) ).toHaveTextContent( 'Closed' );
    } );
} );

describe( 'meta-agent Audience survives the settings reload that follows the save', () => {
    /** The page talks to POST /meta-agent with an `action`; only `settings` matters here. */
    function stubAgentApi () {
        const fetchMock = vi.fn( async ( _url: string, init: RequestInit ) => {
            const body = JSON.parse( String( init.body ) );
            if ( body.action === 'settings' )
            {
                return {
                    status: 200,
                    json: async () => ( {
                        settings: {
                            agent_id: 'agent-1', channel: 'whatsapp',
                            rollout: { enabled: true }, ai_audience: 'EVERYONE',
                        },
                    } ),
                };
            }
            return { status: 200, json: async () => ( {} ) };
        } );
        vi.stubGlobal( 'fetch', fetchMock );
        return fetchMock;
    }

    it( 'keeps the chosen audience after the settings reload answers with the old one', async () => {
        const fetchMock = stubAgentApi();
        render( <MetaAgentPage embedded /> );

        const control = await screen.findByRole( 'combobox', { name: 'Audience' } );
        expect( control ).toHaveTextContent( 'Everyone' );

        fireEvent.click( control );
        fireEvent.click( screen.getByRole( 'option', { name: /Allowlisted numbers only/ } ) );

        await waitFor( () => expect(
            fetchMock.mock.calls.some( ( [ , init ] ) =>
                JSON.parse( String( ( init as RequestInit ).body ) ).action === 'settings_update' )
        ).toBe( true ) );
        await waitFor( () => expect( toastSuccess ).toHaveBeenCalledWith( 'Settings saved' ) );

        expect( screen.getByRole( 'combobox', { name: 'Audience' } ) )
            .toHaveTextContent( /Allowlisted numbers only/ );
    } );

    it( 'sends the chosen value to settings_update, not the one it replaced', async () => {
        const fetchMock = stubAgentApi();
        render( <MetaAgentPage embedded /> );

        fireEvent.click( await screen.findByRole( 'combobox', { name: 'Audience' } ) );
        fireEvent.click( screen.getByRole( 'option', { name: /Allowlisted numbers only/ } ) );

        await waitFor( () => {
            const update = fetchMock.mock.calls
                .map( ( [ , init ] ) => JSON.parse( String( ( init as RequestInit ).body ) ) )
                .find( b => b.action === 'settings_update' );
            expect( update?.aiAudience ).toBe( 'ALLOWLISTED_ONLY' );
        } );
    } );
} );
