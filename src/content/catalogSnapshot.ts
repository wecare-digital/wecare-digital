export interface CatalogSnapshotVariant {
  id: string;
  label?: string;
  inStock?: boolean;
  [key: string]: unknown;
}

export interface CatalogSnapshotProduct {
  id?: string;
  name?: string;
  slug?: string;
  formattedPrice?: string;
  price?: string;
  currency?: string;
  inStock?: boolean;
  visible?: boolean;
  descriptionHtml?: string;
  image?: string;
  canonicalPath?: string;
  websiteEnabled?: boolean;
  metaEnabled?: boolean;
  variantCount?: number;
  variants?: CatalogSnapshotVariant[];
  [key: string]: unknown;
}

export interface CatalogSnapshot {
  source?: string;
  catalogVersion?: string;
  fetchedAt?: string;
  productCount?: number;
  products: CatalogSnapshotProduct[];
  variantVerifiedAt?: string;
  [key: string]: unknown;
}

/**
 * Clean-slate Shop catalog.
 *
 * The retired generated Shop snapshot and its product identities have been removed.
 * Keep this empty until the fresh SKU-first catalog is deliberately created.
 */
export const CATALOG_SNAPSHOT: CatalogSnapshot = {
  source: 'clean-slate',
  catalogVersion: 'SKU_FIRST_V1',
  fetchedAt: '2026-10-17T00:00:00.000Z',
  productCount: 0,
  products: [],
  variantVerifiedAt: '2026-10-17T00:00:00.000Z',
};

export default CATALOG_SNAPSHOT;
