import React from 'react';

import { COUNTRY_OPTIONS, countryCodeForName, countryNameForCode } from '../config/countryOptions';
import { INDIA_SUBDIVISION_NAMES } from '../config/indiaSubdivisions';
import Select from './ui/Select';

export interface StoredAddress {
  addressLine1: string;
  addressLine2: string;
  locality: string;
  city: string;
  state: string;
  postalCode: string;
  country: string;
  countryCode: string;
  fullAddress: string;
}

export interface AddressDraft {
  addressLine1: string;
  addressLine2: string;
  locality: string;
  city: string;
  state: string;
  postalCode: string;
  country: string;
  countryCode: string;
}

export const ADDRESS_COUNTRY = 'India';
export const ADDRESS_COUNTRY_CODE = 'IN';
export const INDIA_PIN_RE = /^[1-9][0-9]{5}$/;

export const EMPTY_ADDRESS_DRAFT: AddressDraft = {
  addressLine1: '',
  addressLine2: '',
  locality: '',
  city: '',
  state: '',
  postalCode: '',
  country: ADDRESS_COUNTRY,
  countryCode: ADDRESS_COUNTRY_CODE,
};

export function draftFromStored ( address: StoredAddress | null | undefined ): AddressDraft {
  if ( !address ) return { ...EMPTY_ADDRESS_DRAFT };
  const rawCode = String( address.countryCode || '' ).trim().toUpperCase();
  const rawCountry = String( address.country || '' ).trim();
  const country = countryNameForCode( rawCode ) || rawCountry || ADDRESS_COUNTRY;
  const countryCode = countryCodeForName( country ) || rawCode || ADDRESS_COUNTRY_CODE;
  return {
    addressLine1: String( address.addressLine1 || '' ),
    addressLine2: String( address.addressLine2 || '' ),
    locality: String( address.locality || '' ),
    city: String( address.city || '' ),
    state: String( address.state || '' ),
    postalCode: String( address.postalCode || '' ),
    country,
    countryCode,
  };
}

export function addressDraftValid ( draft: AddressDraft ): boolean {
  const country = draft.country.trim();
  const countryCode = countryCodeForName( country ) || draft.countryCode.trim().toUpperCase();
  if ( !draft.addressLine1.trim() || !draft.city.trim() || !draft.state.trim()
      || !draft.postalCode.trim() || !country || !countryCode ) return false;
  if ( countryCode === ADDRESS_COUNTRY_CODE ) {
    return INDIA_PIN_RE.test( draft.postalCode.trim() );
  }
  return true;
}

export function addressPayload ( draft: AddressDraft ): Record<string, string> {
  const country = draft.country.trim();
  const countryCode = countryCodeForName( country ) || draft.countryCode.trim().toUpperCase();
  return {
    addressLine1: draft.addressLine1.trim(),
    addressLine2: draft.addressLine2.trim(),
    locality: draft.locality.trim(),
    city: draft.city.trim(),
    state: draft.state.trim(),
    postalCode: draft.postalCode.trim(),
    country,
    countryCode,
  };
}

interface Props {
  value: AddressDraft;
  onChange: ( next: AddressDraft ) => void;
  disabled?: boolean;
  invalidField?: string;
}

const AddressFields: React.FC<Props> = ( { value, onChange, disabled, invalidField } ) => {
  const patch = ( field: keyof AddressDraft, next: string ) =>
    onChange( { ...value, [ field ]: next } );

  const countryCode = countryCodeForName( value.country ) || value.countryCode || ADDRESS_COUNTRY_CODE;
  const india = countryCode === ADDRESS_COUNTRY_CODE;
  const pinEntered = value.postalCode.trim().length > 0;
  const pinBad = india && pinEntered && !INDIA_PIN_RE.test( value.postalCode.trim() );

  const chooseCountry = ( country: string ): void => {
    const nextCode = countryCodeForName( country );
    onChange( {
      ...value,
      country,
      countryCode: nextCode,
      postalCode: value.postalCode,
    } );
  };

  return (
    <fieldset className="address-fields" disabled={ disabled }>
      <legend className="sr-only">Delivery address</legend>

      <div className="address-grid">
        <label className="span-2">
          <span>Street address</span>
          <input
            value={ value.addressLine1 }
            onChange={ event => patch( 'addressLine1', event.target.value ) }
            autoComplete="address-line1"
            maxLength={ 200 }
            aria-required="true"
            aria-invalid={ invalidField === 'addressLine1' ? 'true' : undefined }
          />
        </label>

        <label className="span-2">
          <span>Apartment / suite / unit</span>
          <input
            value={ value.addressLine2 }
            onChange={ event => patch( 'addressLine2', event.target.value ) }
            autoComplete="address-line2"
            maxLength={ 200 }
            aria-invalid={ invalidField === 'addressLine2' ? 'true' : undefined }
          />
        </label>

        <label className="span-2">
          <span>Landmark / neighborhood</span>
          <input
            value={ value.locality }
            onChange={ event => patch( 'locality', event.target.value ) }
            autoComplete="address-level3"
            maxLength={ 100 }
            aria-invalid={ invalidField === 'locality' ? 'true' : undefined }
          />
        </label>

        <label>
          <span>City</span>
          <input
            value={ value.city }
            onChange={ event => patch( 'city', event.target.value ) }
            autoComplete="address-level2"
            maxLength={ 100 }
            aria-required="true"
            aria-invalid={ invalidField === 'city' ? 'true' : undefined }
          />
        </label>

        { india ? (
          <Select
            className="address-state"
            menuClassName="public-checkout-select"
            label="State / region"
            value={ value.state }
            onChange={ next => patch( 'state', next ) }
            invalid={ invalidField === 'state' }
            required
            options={ [
              { value: '', label: 'Select a state' },
              ...INDIA_SUBDIVISION_NAMES.map( name => ( { value: name, label: name } ) ),
            ] }
          />
        ) : (
          <label>
            <span>State / region</span>
            <input
              value={ value.state }
              onChange={ event => patch( 'state', event.target.value ) }
              autoComplete="address-level1"
              maxLength={ 100 }
              aria-required="true"
              aria-invalid={ invalidField === 'state' ? 'true' : undefined }
            />
          </label>
        ) }

        <label>
          <span>Postal code</span>
          <input
            value={ value.postalCode }
            onChange={ event => patch(
              'postalCode',
              india
                ? event.target.value.replace( /\D/g, '' ).slice( 0, 6 )
                : event.target.value.slice( 0, 100 )
            ) }
            autoComplete="postal-code"
            inputMode={ india ? 'numeric' : 'text' }
            maxLength={ india ? 6 : 100 }
            aria-required="true"
            aria-invalid={ pinBad || invalidField === 'postalCode' ? 'true' : undefined }
            aria-describedby={ pinBad ? 'address-postal-help' : undefined }
          />
        </label>

        <Select
          className="address-country"
          menuClassName="public-checkout-select"
          label="Country"
          value={ value.country }
          onChange={ chooseCountry }
          invalid={ invalidField === 'country' || invalidField === 'countryCode' }
          required
          options={ COUNTRY_OPTIONS.map( item => ( { value: item.name, label: item.name } ) ) }
        />
      </div>

      { pinBad && (
        <p id="address-postal-help" className="address-help" role="alert">
          Enter a six-digit Indian PIN code.
        </p>
      ) }

      <style jsx>{`
        .address-fields{
          margin:24px 0 0;padding:0;border:0;min-inline-size:0;
        }
        .sr-only{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
          clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        .address-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px 24px;align-items:start}
        .span-2{grid-column:1/-1}
        label{
          display:flex;flex-direction:column;gap:7px;min-inline-size:0;
          color:var(--public-text);font-size:var(--public-supporting-size);font-weight:600;
        }
        label>span{min-inline-size:0}
        input{
          min-inline-size:0;width:100%;min-height:54px;padding:0 2px;box-sizing:border-box;
          border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;
          background:transparent;color:var(--public-text);
          font:var(--public-body-weight) var(--public-body-size)/1.2 var(--font-sans);
          box-shadow:none;outline:0;-webkit-appearance:none;appearance:none;
          transition:border-color .2s,box-shadow .2s;
        }
        input::placeholder{color:rgba(0,0,0,.42)}
        input:focus{
          border-bottom-color:var(--public-brand-green);
          box-shadow:0 1px 0 0 var(--public-brand-lime);
        }
        input[aria-invalid='true']{
          border-bottom-color:var(--public-brand-green);
          box-shadow:0 1px 0 0 var(--public-brand-lime);
        }

        .address-grid :global(.address-state),
        .address-grid :global(.address-country){
          min-inline-size:0;width:100%;
        }
        .address-grid :global(.address-state .ui-field-label),
        .address-grid :global(.address-country .ui-field-label){
          margin:0 0 7px;color:var(--public-text);font-size:var(--public-supporting-size);font-weight:600;line-height:1.4;
        }
        .address-grid :global(.address-state .ui-select-trigger),
        .address-grid :global(.address-country .ui-select-trigger){
          min-height:54px !important;width:100% !important;padding:0 2px !important;
          border:0 !important;border-bottom:1px solid var(--public-hairline) !important;
          border-radius:0 !important;background:transparent !important;color:var(--public-text) !important;
          box-shadow:none !important;outline:0 !important;
          font:var(--public-body-weight) var(--public-body-size)/1.2 var(--font-sans) !important;
          transition:border-color .2s,box-shadow .2s !important;
        }
        .address-grid :global(.address-state .ui-select-trigger:hover),
        .address-grid :global(.address-country .ui-select-trigger:hover){
          border-bottom-color:var(--public-hairline) !important;background:transparent !important;
        }
        .address-grid :global(.address-state .ui-select-trigger:focus),
        .address-grid :global(.address-country .ui-select-trigger:focus){
          border-bottom-color:var(--public-brand-green) !important;
          box-shadow:0 1px 0 0 var(--public-brand-lime) !important;
          outline:0 !important;
        }
        .address-grid :global(.address-state .ui-select-trigger[aria-invalid='true']),
        .address-grid :global(.address-country .ui-select-trigger[aria-invalid='true']){
          border-bottom-color:var(--public-brand-green) !important;
          box-shadow:0 1px 0 0 var(--public-brand-lime) !important;
        }

        .address-help{
          margin:12px 0 0;padding:11px 13px;border-inline-start:4px solid var(--public-brand-lime);
          border-radius:10px;background:var(--public-lime-tint);color:var(--public-text);
          font-size:var(--public-supporting-size);font-weight:600;line-height:1.4;
        }

        @media(max-width:767px){
          .address-grid{grid-template-columns:1fr;gap:18px}
          .span-2{grid-column:auto}
          input{min-height:52px;font-size:16px}
          .address-grid :global(.address-state .ui-select-trigger),
          .address-grid :global(.address-country .ui-select-trigger){
            min-height:52px !important;font-size:16px !important;
          }
        }
      `}</style>
    </fieldset>
  );
};

export default AddressFields;
