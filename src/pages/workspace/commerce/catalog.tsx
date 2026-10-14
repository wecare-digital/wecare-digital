/**
 * Staff AWS-native product editor.
 *
 * The public shop renders a static ProductsTable snapshot. Staff edits update
 * ProductsTable, and the scheduled OIDC catalog publisher commits a new snapshot
 * to trigger an Amplify rebuild. Payment quotes always read live ProductsTable.
 *
 * No Wix runtime API and no Meta catalog as price authority.
 */
import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import Layout from '../../../components/Layout';
import PageHeader from '../../../components/PageHeader';
import SEO from '../../../components/SEO';
import Spinner from '../../../components/ui/Spinner';
import * as api from '../../../api/client';
import { useConfirm } from '../../../contexts/ConfirmContext';

interface PageProps { signOut?: () => void; user?: any; }

interface NativeVariant {
  sku: string;
  label: string;
  priceMinor: number;
  inventory: number;
}
interface NativeProduct {
  id: string;
  title: string;
  slug: string;
  status: 'draft' | 'active' | 'archived';
  currency: string;
  priceMinor: number;
  updatedAt: string;
  tagline?: string;
  descriptionHtml?: string;
  variants: NativeVariant[];
  imageRefs?: string[];
  categories?: string[];
}
type Tab = 'products' | 'orders' | 'meta';
type VariantDraft = { price: string; stockDelta: string; label: string };

const API_ROOT = (process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api')
  .replace(/\/$/, '') + '/native-catalog/products';
const boxStyle: React.CSSProperties = {
  background: '#fff', border: '1px solid #dfe5e4', borderRadius: 12,
  padding: 18, marginBottom: 16,
};
const fieldStyle: React.CSSProperties = {
  display: 'block', width: '100%', padding: '9px 12px', fontSize: 14,
  borderRadius: 8, border: '1px solid #cbd5d1', marginTop: 5,
};
const muted: React.CSSProperties = { color: '#66746f', fontSize: 12 };
const rowStyle: React.CSSProperties = {
  padding: '11px 0', borderBottom: '1px solid #e4e9e7', display: 'flex',
  alignItems: 'center', gap: 14, flexWrap: 'wrap',
};

function formatINR(paise: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR',
  }).format(paise / 100);
}

function parsePaise(input: string): number {
  const value = input.trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) {
    throw new Error('Enter an amount in rupees with at most two decimal places.');
  }
  const parts = value.split('.');
  const minor = Number(parts[0]) * 100 + Number((parts[1] || '').padEnd(2, '0') || 0);
  if (!Number.isSafeInteger(minor) || minor < 0 || minor > 100_000_000) {
    throw new Error('Amount outside the supported price range.');
  }
  return minor;
}

async function nativeCall(
  path: string, init: RequestInit = {},
): Promise<any> {
  const response = await api.authFetch(API_ROOT + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
  let data: any = null;
  try { data = await response.json(); } catch { /* fail as an HTTP error below */ }
  if (!response.ok || !data) {
    const reason = typeof data?.error === 'string' ? data.error :
      'AWS catalog API unavailable';
    throw new Error(reason + (response.status === 409 ? ' — Reload and review the current version.' : ''));
  }
  return data;
}

const CatalogPage: React.FC<PageProps> = ({ signOut, user }) => {
  const [tab, setTab] = useState<Tab>('products');
  const [products, setProducts] = useState<NativeProduct[]>([]);
  const [orders, setOrders] = useState<api.Order[]>([]);
  const [selected, setSelected] = useState<NativeProduct | null>(null);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const confirm = useConfirm();
  const [editTitle, setEditTitle] = useState('');
  const [editTagline, setEditTagline] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editStatus, setEditStatus] = useState<NativeProduct['status']>('draft');
  const [drafts, setDrafts] = useState<Record<string, VariantDraft>>({});
  const [newTitle, setNewTitle] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [newPrice, setNewPrice] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [metaPlan, setMetaPlan] = useState<api.MetaCatalogSyncControl | null>(null);

  const reloadProducts = useCallback(async () => {
    const data = await nativeCall('');
    if (!Array.isArray(data.products)) throw new Error('Invalid native products response');
    setProducts(data.products);
    return data.products as NativeProduct[];
  }, []);

  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError('');
    setMessage('');
    try { await fn(); } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Request failed');
    } finally { setBusy(false); }
  }, []);

  const showProduct = useCallback((p: NativeProduct | null) => {
    setSelected(p);
    if (!p) return;
    setEditTitle(p.title);
    setEditTagline(p.tagline || '');
    setEditDescription(p.descriptionHtml || '');
    setEditStatus(p.status);
    setDrafts(Object.fromEntries((p.variants || []).map(v => [v.sku, {
      label: v.label || 'Standard',
      price: (v.priceMinor / 100).toFixed(2),
      stockDelta: '0',
    }])));
  }, []);

  useEffect(() => {
    void run(async () => { await reloadProducts(); });
  }, [reloadProducts, run]);

  useEffect(() => {
    if (tab === 'orders') {
      void run(async () => {
        const result = await api.listOrders({ limit: 50 });
        setOrders(result.orders || []);
      });
    }
    if (tab === 'meta') {
      void run(async () => {
        const result = await api.getMetaCatalogSyncPlan();
        if (result.ok) setMetaPlan(result.data);
        else throw new Error(result.failure.message);
      });
    }
  }, [tab, run]);

  const updateProduct = () => {
    if (!selected) return;
    void run(async () => {
      const data = await nativeCall('/' + encodeURIComponent(selected.id), {
        method: 'PATCH',
        body: JSON.stringify({
          expectedUpdatedAt: selected.updatedAt,
          title: editTitle,
          tagline: editTagline,
          descriptionHtml: editDescription,
          status: editStatus,
        }),
      });
      showProduct(data.product);
      await reloadProducts();
      setMessage('Saved to AWS ProductsTable. The public shop updates after the next catalog publish.');
    });
  };

  const updateVariant = (v: NativeVariant) => {
    if (!selected) return;
    const draft = drafts[v.sku];
    if (!draft) return;
    void run(async () => {
      const delta = Number(draft.stockDelta);
      if (!Number.isSafeInteger(delta) || Math.abs(delta) > 1_000_000) {
        throw new Error('Stock change must be a whole number (maximum 1,000,000).');
      }
      const data = await nativeCall(
        '/' + encodeURIComponent(selected.id) + '/variants/' + encodeURIComponent(v.sku), {
          method: 'PATCH',
          body: JSON.stringify({
            expectedUpdatedAt: selected.updatedAt,
            priceMinor: parsePaise(draft.price),
            label: draft.label,
            stockDelta: delta,
          }),
        },
      );
      showProduct(data.product);
      await reloadProducts();
      setMessage('Variant price and stock adjustment saved. Checkout reads AWS prices directly.');
    });
  };

  const createProduct = () => {
    void run(async () => {
      const result = await nativeCall('', {
        method: 'POST',
        body: JSON.stringify({
          title: newTitle, slug: newSlug,
          descriptionHtml: newDescription, currency: 'INR',
          variants: [{
            label: 'Standard', priceMinor: parsePaise(newPrice), inventory: 0,
          }],
        }),
      });
      await reloadProducts();
      showProduct(result.product);
      setNewTitle(''); setNewSlug(''); setNewPrice(''); setNewDescription('');
      setMessage('Created as a draft in AWS; it is not publicly for sale until approved.');
    });
  };

  const archive = () => {
    if (!selected) return;
    void (async () => {
      const ok = await confirm({
        title: 'Archive this product?',
        message: 'Past order references will be retained.',
        confirmText: 'Archive',
      });
      if (!ok) return;
      await run(async () => {
        const data = await nativeCall('/' + encodeURIComponent(selected.id), {
          method: 'DELETE',
          body: JSON.stringify({ expectedUpdatedAt: selected.updatedAt }),
        });
        showProduct(data.product);
        await reloadProducts();
        setMessage('Product archived in AWS; historical orders remain intact.');
      });
    })();
  };

  const filtered = products.filter(p => {
    const q = search.trim().toLowerCase();
    return !q || (p.title + ' ' + p.slug + ' ' + p.id).toLowerCase().includes(q);
  });
  const totalVariants = products.reduce((count, p) => count + (p.variants || []).length, 0);

  return (
    <Layout user={user} onSignOut={signOut}>
      <SEO title="AWS Product Catalog" description="WECARE.DIGITAL AWS-native product management" />
      <div style={{ paddingBottom: 40 }}>
        <PageHeader
          title="Product Catalog"
          subtitle={'AWS ProductsTable — ' + products.length + ' products, ' + totalVariants + ' variants'}
          icon="store"
          actions={<button onClick={() => void run(async () => { await reloadProducts(); })}
            disabled={busy}>Refresh AWS</button>}
        />

        <nav aria-label="Commerce sections" style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
          {(['products', 'orders', 'meta'] as Tab[]).map(id => (
            <button type="button" key={id} onClick={() => setTab(id)}
              aria-pressed={tab === id}
              style={{
                padding: '10px 14px', borderRadius: 8,
                border: '1px solid #bdd0c7',
                background: tab === id ? '#1b4837' : '#fff',
                color: tab === id ? '#fff' : '#1b4837',
              }}>{id === 'products' ? 'Products & variants' : id === 'orders' ? 'Order history' : 'Meta catalog'}</button>
          ))}
        </nav>

        {error && <div role="alert" style={{ color: '#a11', margin: '10px 0' }}>{error}</div>}
        {message && <div role="status" style={{ color: '#176440', margin: '10px 0' }}>{message}</div>}
        {busy && <div role="status" style={{ marginBottom: 12 }}><Spinner size="sm" /> Updating...</div>}

        {tab === 'products' && (
          <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 350px), 1fr))' }}>
            <section style={boxStyle} aria-label="Products">
              <h2 style={{ fontSize: 18, marginTop: 0 }}>Products</h2>
              <input style={fieldStyle} aria-label="Search products" placeholder="Search products"
                value={search} onChange={e => setSearch(e.target.value)} />
              <div style={{ maxHeight: 530, overflowY: 'auto', marginTop: 12 }}>
                {filtered.map(p => (
                  <button type="button" key={p.id} onClick={() => showProduct(p)}
                    style={{ ...rowStyle, width: '100%', background: selected?.id === p.id ? '#e8f3ed' : '#fff',
                      borderTop: 'none', borderLeft: 'none', borderRight: 'none', cursor: 'pointer', textAlign: 'left' }}>
                    {p.imageRefs?.[0] && <img src={p.imageRefs[0]} alt=""
                      width={48} height={48} style={{ borderRadius: 6, objectFit: 'cover' }} />}
                    <span style={{ flex: 1 }}>
                      <strong style={{ display: 'block' }}>{p.title}</strong>
                      <span style={muted}>/shop/{p.slug}/ · {p.status} · {(p.variants || []).length} variant(s)</span>
                    </span>
                    <strong>{formatINR(p.priceMinor)}</strong>
                  </button>
                ))}
                {filtered.length === 0 && <p>No matching AWS products.</p>}
              </div>
            </section>

            <section style={boxStyle} aria-label="Product editor">
              {selected ? (
                <>
                  <h2 style={{ fontSize: 18, marginTop: 0 }}>Edit {selected.title}</h2>
                  <p style={muted}>Product ID {selected.id} · Slug /{selected.slug}/ · Version {selected.updatedAt}</p>
                  <label>Title
                    <input style={fieldStyle} value={editTitle}
                      onChange={e => setEditTitle(e.target.value)} />
                  </label>
                  <label>Summary
                    <textarea style={{ ...fieldStyle, minHeight: 65 }} value={editTagline}
                      onChange={e => setEditTagline(e.target.value)} />
                  </label>
                  <label>Description HTML
                    <textarea style={{ ...fieldStyle, minHeight: 95 }} value={editDescription}
                      onChange={e => setEditDescription(e.target.value)} />
                  </label>
                  <label>Visibility
                    <select style={fieldStyle} value={editStatus}
                      onChange={e => setEditStatus(e.target.value as NativeProduct['status'])}>
                      <option value="draft">Draft</option>
                      <option value="active">Active</option>
                      <option value="archived">Archived</option>
                    </select>
                  </label>
                  <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
                    <button disabled={busy} onClick={updateProduct}>Save product</button>
                    <button disabled={busy} onClick={archive}>Archive</button>
                  </div>
                  <h3 style={{ marginTop: 25 }}>Variants ({selected.variants.length})</h3>
                  <p style={muted}>SKU/variant ID stays immutable to protect carts and historical orders.
                    Stock is adjusted by delta rather than overwritten while payments may reserve units.</p>
                  {selected.variants.map(v => {
                    const draft = drafts[v.sku];
                    if (!draft) return null;
                    return (
                      <div style={{ ...boxStyle, background: '#f8faf8' }} key={v.sku}>
                        <div style={muted}>{v.sku}</div>
                        <label>Variant label
                          <input style={fieldStyle} value={draft.label}
                            onChange={e => setDrafts(prev => ({
                              ...prev, [v.sku]: { ...prev[v.sku], label: e.target.value },
                            }))} />
                        </label>
                        <label>Price (INR)
                          <input style={fieldStyle} value={draft.price} inputMode="decimal"
                            onChange={e => setDrafts(prev => ({
                              ...prev, [v.sku]: { ...prev[v.sku], price: e.target.value },
                            }))} />
                        </label>
                        <p style={muted}>Currently {v.inventory} units available</p>
                        <label>Stock adjustment (+ to add, - to remove)
                          <input style={fieldStyle} value={draft.stockDelta} inputMode="numeric"
                            onChange={e => setDrafts(prev => ({
                              ...prev, [v.sku]: { ...prev[v.sku], stockDelta: e.target.value },
                            }))} />
                        </label>
                        <button onClick={() => updateVariant(v)} disabled={busy}
                          style={{ marginTop: 12 }}>Save variant</button>
                      </div>
                    );
                  })}
                  <p style={muted}>Artwork is hosted under the media service. Upload replacement
                    images using the controlled S3 catalog-media migration; do not paste untrusted external URLs.</p>
                </>
              ) : (
                <p>Select a product to edit its AWS source record.</p>
              )}
            </section>

            <section style={boxStyle} aria-label="Create draft product">
              <h2 style={{ fontSize: 18, marginTop: 0 }}>Create draft</h2>
              <p style={muted}>New products start unpublished with zero available stock.</p>
              <label>Product name
                <input style={fieldStyle} value={newTitle}
                  onChange={e => setNewTitle(e.target.value)} />
              </label>
              <label>URL slug
                <input style={fieldStyle} value={newSlug}
                  onChange={e => setNewSlug(e.target.value.toLowerCase())} />
              </label>
              <label>Price (INR)
                <input style={fieldStyle} inputMode="decimal" value={newPrice}
                  onChange={e => setNewPrice(e.target.value)} />
              </label>
              <label>Description HTML
                <textarea style={{ ...fieldStyle, minHeight: 90 }} value={newDescription}
                  onChange={e => setNewDescription(e.target.value)} />
              </label>
              <button style={{ marginTop: 12 }} disabled={busy} onClick={createProduct}>
                Create AWS draft
              </button>
            </section>
          </div>
        )}

        {tab === 'orders' && (
          <section style={boxStyle}>
            <h2 style={{ fontSize: 18 }}>AWS order history</h2>
            <p style={muted}>Orders are read from the existing native order service.
              Previous Wix identifiers are retained only where needed to reconcile history.</p>
            {orders.length ? (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr>
                  <th align="left">Order</th><th align="left">Status</th>
                  <th align="left">Payment</th><th align="left">Date</th>
                </tr></thead>
                <tbody>{orders.map((o, index) => (
                  <tr key={o.orderId || String(index)} style={{ borderTop: '1px solid #e3e9e6' }}>
                    <td style={{ padding: '12px 8px' }}>{o.orderNumber || o.orderId}</td>
                    <td>{o.orderStatus || o.status || '—'}</td>
                    <td>{o.paymentStatus || '—'}</td>
                    <td>{o.orderDate || (o.createdAt ? new Date(o.createdAt * 1000).toLocaleDateString('en-IN') : '—')}</td>
                  </tr>
                ))}</tbody>
              </table>
            ) : <p>No orders returned by the AWS order service.</p>}
            <Link href="/workspace/pay/records">Open invoice and payment records</Link>
          </section>
        )}

        {tab === 'meta' && (
          <section style={boxStyle}>
            <h2 style={{ fontSize: 18 }}>Meta commerce synchronization</h2>
            <p>Product prices come from AWS ProductsTable. Meta is a projected sales channel,
              not the product database. Sync application and approvals stay owner-gated.</p>
            {metaPlan ? (
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, overflowX: 'auto',
                background: '#f5f7f6', padding: 14, borderRadius: 8 }}>
                {JSON.stringify({
                  enabled: metaPlan.enabled,
                  dryRun: metaPlan.dryRun,
                  blocked: metaPlan.blocked,
                  planHash: metaPlan.planHash,
                  currentPlanHash: metaPlan.currentPlanHash,
                }, null, 2)}
              </pre>
            ) : <p>Meta plan not loaded.</p>}
            <p style={muted}>Use the existing Meta catalog authorization controls to
              review and approve changes before enabling publishing.</p>
          </section>
        )}
      </div>
    </Layout>
  );
};

export default CatalogPage;
