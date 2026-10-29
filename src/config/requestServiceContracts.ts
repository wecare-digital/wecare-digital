/** Single-order request-service contracts.
 *
 * Stable identity only. Prices are always read from ProductsTable by the backend.
 * Flow IDs are intentionally NOT copied here; canonicalFlows owns Meta Flow identity.
 */
export type RequestServiceCode =
  | 'SUBMIT_REQUEST'
  | 'REQUEST_AMENDMENT'
  | 'DROP_DOCS'
  | 'VAULT'
  | 'REQUEST_PICKUP';

export interface RequestServiceContract {
  readonly serviceCode: RequestServiceCode;
  readonly label: string;
  readonly productId: string;
  readonly sku: string;
  readonly flowCapability: string | null;
  readonly fulfillmentKind: 'flow' | 'secure_download';
  readonly requiresExistingOrder: true;
  readonly onePaymentOneFulfillment: true;
  readonly catalogVisible: false;
  readonly supplyGstBps: number;
  readonly expressPaise: number;
}

export const REQUEST_SERVICE_CONTRACTS: readonly RequestServiceContract[] = [
  { serviceCode:'SUBMIT_REQUEST', label:'Submit Request', productId:'f829697a-b1db-5c4e-bfce-51d1487278a7', sku:'RSR7M2P9', flowCapability:'submit_request', fulfillmentKind:'flow', requiresExistingOrder:true, onePaymentOneFulfillment:true, catalogVisible:false, supplyGstBps:0, expressPaise:0 },
  { serviceCode:'REQUEST_AMENDMENT', label:'Request Amendment', productId:'7133c98d-de8d-5e56-94ff-8d9fea7aa331', sku:'RAM5Q8K4', flowCapability:'amend_request', fulfillmentKind:'flow', requiresExistingOrder:true, onePaymentOneFulfillment:true, catalogVisible:false, supplyGstBps:0, expressPaise:0 },
  { serviceCode:'DROP_DOCS', label:'Drop Docs', productId:'e1ca7833-5d7d-567b-837c-face04647598', sku:'RDD9P3M7', flowCapability:'drop_docs', fulfillmentKind:'flow', requiresExistingOrder:true, onePaymentOneFulfillment:true, catalogVisible:false, supplyGstBps:1800, expressPaise:2500 },
  { serviceCode:'VAULT', label:'Vault', productId:'d4cfc6e8-10b3-5c47-94c8-3c69f4c03907', sku:'RVT6K4Q8', flowCapability:null, fulfillmentKind:'secure_download', requiresExistingOrder:true, onePaymentOneFulfillment:true, catalogVisible:false, supplyGstBps:1800, expressPaise:2500 },
  { serviceCode:'REQUEST_PICKUP', label:'Request Pickup', productId:'166370fe-69a8-5ad2-9f9a-e9ce3f92839c', sku:'SHP7Q4N9', flowCapability:'request_pickup', fulfillmentKind:'flow', requiresExistingOrder:true, onePaymentOneFulfillment:true, catalogVisible:false, supplyGstBps:0, expressPaise:0 },
] as const;

export const requestServiceContract = ( serviceCode: unknown ): RequestServiceContract | null =>
  REQUEST_SERVICE_CONTRACTS.find( contract =>
    contract.serviceCode === String( serviceCode || '' ).trim().toUpperCase()
  ) || null;
