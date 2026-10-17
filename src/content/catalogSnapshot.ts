import rawCatalog from './catalog-snapshot.json';

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
 * Stable TypeScript boundary for the generated JSON snapshot.
 *
 * JSON imports infer an empty array as never[]. The catalogue is allowed to be intentionally empty,
 * so every TypeScript consumer must read through this typed adapter instead of importing the JSON
 * file directly.
 */
export const CATALOG_SNAPSHOT: CatalogSnapshot = rawCatalog as CatalogSnapshot;

export default CATALOG_SNAPSHOT;
