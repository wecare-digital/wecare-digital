/**
 * The Catalog Builder's product edit flow, and the one property that makes it safe.
 *
 * The form that edits a product is the same form that creates one, and it is populated
 * from the catalog list row. That row's `price` is whatever Graph chose to format it as
 * ("₹6,999.00"), while the input edits rupees as a number — so the page parses it for
 * display. The hazard is the return journey: if an edit re-sent that parsed value and the
 * field had in fact been minor units, the handler's rupees -> paise conversion would
 * multiply the stored price by 100. Nothing in the page can prove which representation
 * Graph used, so the page never asserts one: `price` leaves the browser ONLY when the user
 * changes the field, and an untouched price is omitted so Graph keeps the stored amount.
 *
 * That same rule is what lets an availability-only edit succeed on a product whose price
 * string did not parse. Requiring a price on every save blocked every edit to such a
 * product, and told the user "price is required" over a field they never touched and could
 * not meaningfully refill.
 *
 * These tests pin the behaviour, not the spelling: they assert on the arguments handed to
 * api.updateCatalogProduct rather than on the wire body.
 */
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock( '../components/Layout', () => ( { default: ( { children }: { children: React.ReactNode } ) => <div>{ children }</div> } ) );
vi.mock( '../components/SEO', () => ( { default: () => null } ) );

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock( '../contexts/ToastContext', () => ( {
    useToastContext: () => ( { success: toastSuccess, error: toastError, info: vi.fn(), warning: vi.fn() } ),
} ) );
vi.mock( '../contexts/ConfirmContext', () => ( { useConfirm: () => vi.fn().mockResolvedValue( true ) } ) );

const listCatalogProductsAdmin = vi.fn();
const updateCatalogProduct = vi.fn();
const createCatalogProduct = vi.fn();
const deleteCatalogProduct = vi.fn();

vi.mock( '../api/client', async importOriginal => ( {
    ...await importOriginal<typeof import( '../api/client' )>(),
    listCatalogProductsAdmin: ( ...a: unknown[] ) => listCatalogProductsAdmin( ...a ),
    updateCatalogProduct: ( ...a: unknown[] ) => updateCatalogProduct( ...a ),
    createCatalogProduct: ( ...a: unknown[] ) => createCatalogProduct( ...a ),
    deleteCatalogProduct: ( ...a: unknown[] ) => deleteCatalogProduct( ...a ),
    listCatalogFlows: vi.fn().mockResolvedValue( [] ),
} ) );

import CatalogBuilderPage from '../pages/workspace/engage/whatsapp/catalog-builder';

/** A list row as _list_catalog_products normalizes it: the Meta id, and a formatted price. */
const ROW = {
    id: 'pid_1', retailerId: 'WD-PARTNER-UP', name: 'Partner Up', price: '₹6,999.00',
    currency: 'INR', availability: 'in stock', description: 'Stored description',
    imageUrl: 'https://wecare.digital/i.png', url: 'https://wecare.digital/p',
};

const field = ( label: RegExp | string ) => screen.getByText( label ).parentElement!.querySelector( 'input, select' ) as HTMLInputElement;

/**
 * Availability is a ui/Select now, not a native control, so there is no element to fire a
 * `change` at - the user opens the menu and commits a row. This is the same USER ACTION the
 * old `fireEvent.change` stood for, which is why the assertions below are untouched: they were
 * always about the arguments handed to api.updateCatalogProduct, not about the control's
 * spelling.
 */
const chooseAvailability = ( option: string ) => {
    fireEvent.click( screen.getByRole( 'combobox', { name: 'Availability' } ) );
    fireEvent.click( screen.getByRole( 'option', { name: option } ) );
};

const openEdit = async ( row: Record<string, unknown> = ROW ) => {
    listCatalogProductsAdmin.mockResolvedValue( [ row ] );
    render( <CatalogBuilderPage /> );
    fireEvent.click( await screen.findByRole( 'button', { name: 'Edit' } ) );
};

beforeEach( () => {
    vi.clearAllMocks();
    updateCatalogProduct.mockResolvedValue( true );
} );

describe( 'catalog product edit', () => {
    it( 'loads the product into the form and switches it into update mode', async () => {
        await openEdit();
        expect( screen.getByText( 'Edit product' ) ).toBeInTheDocument();
        expect( screen.getByRole( 'button', { name: 'Save changes' } ) ).toBeInTheDocument();
        expect( screen.queryByRole( 'button', { name: 'Create product' } ) ).toBeNull();
        expect( screen.getByRole( 'button', { name: 'Cancel edit' } ) ).toBeInTheDocument();
        expect( field( 'Name *' ).value ).toBe( 'Partner Up' );
        expect( field( /^Price/ ).value ).toBe( '6999' );
        expect( field( 'Description' ).value ).toBe( 'Stored description' );
        // retailer_id is the SKU identity and the update payload cannot change it
        expect( field( /SKU/ ).disabled ).toBe( true );
        expect( field( /SKU/ ).value ).toBe( 'WD-PARTNER-UP' );
    } );

    it( 'omits price when the field was not touched, so a formatted price is never re-sent', async () => {
        await openEdit();
        chooseAvailability( 'out of stock' );
        fireEvent.click( screen.getByRole( 'button', { name: 'Save changes' } ) );
        await waitFor( () => expect( updateCatalogProduct ).toHaveBeenCalled() );
        const [ pid, updates ] = updateCatalogProduct.mock.calls[ 0 ];
        expect( pid ).toBe( 'pid_1' );
        expect( updates.availability ).toBe( 'out of stock' );
        expect( updates.price ).toBeUndefined();
        expect( updates.currency ).toBeUndefined();
        // unchanged description is left alone for the same reason
        expect( updates.description ).toBeUndefined();
    } );

    it( 'sends a changed price in rupees, the same representation the create path uses', async () => {
        await openEdit();
        fireEvent.change( field( /^Price/ ), { target: { value: '7499' } } );
        fireEvent.click( screen.getByRole( 'button', { name: 'Save changes' } ) );
        await waitFor( () => expect( updateCatalogProduct ).toHaveBeenCalled() );
        const updates = updateCatalogProduct.mock.calls[ 0 ][ 1 ];
        expect( updates.price ).toBe( 7499 );
        expect( updates.currency ).toBe( 'INR' );
        // create sends Number( form.price ) for the same typed string; update must not diverge
        expect( updates.price ).toBe( Number( '7499' ) );
    } );

    it( 'still saves an availability-only edit when the price string did not parse', async () => {
        await openEdit( { ...ROW, price: 'on request' } );
        expect( field( /^Price/ ).value ).toBe( '' );
        chooseAvailability( 'out of stock' );
        fireEvent.click( screen.getByRole( 'button', { name: 'Save changes' } ) );
        await waitFor( () => expect( updateCatalogProduct ).toHaveBeenCalled() );
        expect( updateCatalogProduct.mock.calls[ 0 ][ 1 ].price ).toBeUndefined();
        expect( toastError ).not.toHaveBeenCalled();
    } );

    it( 'refreshes the list and leaves update mode once the save succeeds', async () => {
        await openEdit();
        expect( listCatalogProductsAdmin ).toHaveBeenCalledTimes( 1 );
        fireEvent.change( field( 'Name *' ), { target: { value: 'Partner Up Plus' } } );
        fireEvent.click( screen.getByRole( 'button', { name: 'Save changes' } ) );
        await waitFor( () => expect( listCatalogProductsAdmin ).toHaveBeenCalledTimes( 2 ) );
        expect( toastSuccess ).toHaveBeenCalledWith( 'Product updated' );
        expect( await screen.findByRole( 'button', { name: 'Create product' } ) ).toBeInTheDocument();
        expect( screen.getByText( 'New product' ) ).toBeInTheDocument();
        expect( field( 'Name *' ).value ).toBe( '' );
    } );

    it( 'hides the create-only fields while editing rather than letting them read as editable', async () => {
        listCatalogProductsAdmin.mockResolvedValue( [ ROW ] );
        render( <CatalogBuilderPage /> );
        await screen.findByRole( 'button', { name: 'Edit' } );
        expect( screen.getByText( /Sale price/ ) ).toBeInTheDocument();
        fireEvent.click( screen.getByRole( 'button', { name: 'Edit' } ) );
        // _update_catalog_product has no sale_price or brand branch
        expect( screen.queryByText( /Sale price/ ) ).toBeNull();
        expect( screen.queryByText( 'Brand' ) ).toBeNull();
    } );

    it( 'deletes by the id carried on the list row, and does not touch the create path', async () => {
        deleteCatalogProduct.mockResolvedValue( true );
        listCatalogProductsAdmin.mockResolvedValue( [ ROW ] );
        render( <CatalogBuilderPage /> );
        fireEvent.click( await screen.findByRole( 'button', { name: 'Delete' } ) );
        await waitFor( () => expect( deleteCatalogProduct ).toHaveBeenCalledWith( 'pid_1' ) );
        expect( createCatalogProduct ).not.toHaveBeenCalled();
        expect( updateCatalogProduct ).not.toHaveBeenCalled();
    } );
} );
