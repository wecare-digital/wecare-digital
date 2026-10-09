/**
 * Catalog - Wix Headless Commerce: Catalog V3, categories, inventory, orders.
 *
 * WHY THIS MOVED FROM /store TO /workspace/commerce/catalog.
 *
 * It is a staff page: it imports the authenticated Layout, and _app.tsx wraps every route
 * that is not on the public allowlist in the Cognito Authenticator. At /store that produced a
 * PUBLIC-looking URL whose prerendered HTML was the staff sign-in screen at HTTP 200, with the
 * public header and footer around it. Measured on the export: no <main>, no <h1>, no
 * .page-title - because the Authenticator renders INSTEAD of these children when there is no
 * session, and a static export is always prerendered without one. It was the only public
 * route on the site failing both the landmark and heading checks in tools/audit/htmlcheck.js.
 *
 * _app.tsx already records what this shape cost once: /contact-test was both allowlisted AND
 * wrapped in Layout, which leaked the entire staff sidebar into public HTML. That note names
 * /store as having been clean at the time. It was not clean any more.
 *
 * Under /workspace/ the sign-in wall is the correct response to an anonymous request, the URL
 * no longer implies a storefront, and htmlcheck's public sweep - which is scoped to the 18
 * authored public routes - stops reporting it.
 *
 * IT ALSO FREES A PREFIX THAT WAS DOING THREE JOBS. _routes.json declares
 * GET /store/preview-product-image, POST /store/generate-product-image and
 * POST /store/convert-flag, so /store/* was simultaneously a public page, a staff page and an
 * API namespace. Those API routes are unaffected by this move and keep their paths.
 *
 * The old URL is not redirected in-repo: there are no public inbound links to it, it was never
 * in the sitemap, and Amplify's /<*> -> /index.html rule already catches a stale bookmark.
 */

import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../components/Layout';
import PageHeader from '../../../components/PageHeader';
import SEO from '../../../components/SEO';
import Tabs, { TabItem } from '../../../components/ui/Tabs';
import Table from '../../../components/ui/Table';
import Modal from '../../../components/ui/Modal';
import Spinner from '../../../components/ui/Spinner';
import EmptyState from '../../../components/ui/EmptyState';
import Select, { type SelectOption } from '../../../components/ui/Select';
import * as api from '../../../api/client';

interface PageProps {
  signOut?: () => void;
  user?: any;
}

type TabType = 'products' | 'orders' | 'collections' | 'manage' | 'admin' | 'settings';

/* The option rows, hoisted. Same order, same values, same visible text as the <option>s they
   replaced, including the '' placeholder row the order filter reads as "no filter". */
const ORDER_STATUS_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Statuses' },
  { value: 'PAID', label: 'Paid' },
  { value: 'NOT_PAID', label: 'Not Paid' },
  { value: 'PARTIALLY_PAID', label: 'Partially Paid' },
  { value: 'PARTIALLY_REFUNDED', label: 'Partially Refunded' },
  { value: 'FULLY_REFUNDED', label: 'Fully Refunded' },
];
const CURRENCY_OPTIONS: SelectOption[] = [
  { value: 'INR', label: 'INR (₹)' },
  { value: 'USD', label: 'USD ($)' },
  { value: 'EUR', label: 'EUR (€)' },
  { value: 'GBP', label: 'GBP (£)' },
];
const PRODUCT_TYPE_OPTIONS: SelectOption[] = [
  { value: 'digital', label: 'Digital' },
  { value: 'physical', label: 'Physical' },
];

/* LAYOUT ONLY - what the inline `width: '100%'` carried, and a width for the filter, which
   is a flex child beside a search input. */
const FULL_WIDTH: React.CSSProperties = { width: '100%' };
const FILTER_STYLE: React.CSSProperties = { width: 190 };

const TABS: TabItem[] = [
  { id: 'products', label: 'Products' },
  { id: 'orders', label: 'Orders' },
  { id: 'collections', label: 'Categories' },
  { id: 'manage', label: 'Product Manager' },
  { id: 'admin', label: 'Store Admin' },
  { id: 'settings', label: 'Settings' },
];

const StorePage: React.FC<PageProps> = ( { signOut, user } ) => {
  const [ activeTab, setActiveTab ] = useState<TabType>( 'products' );
  const [ loading, setLoading ] = useState( false );
  const [ syncing, setSyncing ] = useState( false );

  // Meta catalog owner-approval control. This never bypasses server gates: the backend requires
  // Admin + MFA, derives the approver identity from Cognito and recomputes the exact live plan.
  const [ metaCatalog, setMetaCatalog ] = useState<api.MetaCatalogSyncControl | null>( null );
  const [ metaCatalogBusy, setMetaCatalogBusy ] = useState( false );
  const [ metaCatalogMessage, setMetaCatalogMessage ] = useState( '' );

  // Products
  const [ products, setProducts ] = useState<api.WixProduct[]>( [] );
  const [ productCount, setProductCount ] = useState( 0 );
  const [ productSearch, setProductSearch ] = useState( '' );
  const [ selectedProduct, setSelectedProduct ] = useState<api.WixProduct | null>( null );

  // Orders
  const [ orders, setOrders ] = useState<api.WixOrder[]>( [] );
  const [ orderCount, setOrderCount ] = useState( 0 );
  const [ orderSearch, setOrderSearch ] = useState( '' );
  const [ orderStatusFilter, setOrderStatusFilter ] = useState( '' );
  const [ selectedOrder, setSelectedOrder ] = useState<api.WixOrder | null>( null );

  // Categories (the route id stays 'collections' for compatibility)
  const [ collections, setCollections ] = useState<api.WixCollection[]>( [] );
  const [ collectionCount, setCollectionCount ] = useState( 0 );
  const [ selectedCollectionId, setSelectedCollectionId ] = useState<string>( '' );

  // Sites (settings)
  const [ sites, setSites ] = useState<any[]>( [] );

  // Product Manager
  const [ manageMode, setManageMode ] = useState<'single' | 'bulk'>( 'single' );
  const [ creating, setCreating ] = useState( false );
  const [ createResult, setCreateResult ] = useState<any>( null );
  const [ sampleProducts, setSampleProducts ] = useState<any[]>( [] );
  const [ newProduct, setNewProduct ] = useState( {
    name: '',
    productType: 'digital' as 'digital' | 'physical',
    description: '',
    price: '',
    currency: 'INR',
    sku: '',
    ribbon: 'BNB CLUB',
    brand: 'WECARE.DIGITAL',
    weight: '0',
  } );
  const [ bulkJson, setBulkJson ] = useState( '' );

  // ---- Data fetching ----
  const fetchProducts = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listWixProducts( {
        limit: 100,
        search: productSearch || undefined,
        collectionId: selectedCollectionId || undefined,
      } );
      setProducts( data.products );
      setProductCount( data.totalCount );
    } catch ( e )
    {
      console.error( 'Failed to fetch products:', e );
    }
    setLoading( false );
  }, [ productSearch, selectedCollectionId ] );

  const fetchOrders = useCallback( async () => {
    setLoading( true );
    try
    {
      const params: any = { limit: 50 };
      if ( orderStatusFilter ) params.paymentStatus = orderStatusFilter;
      if ( orderSearch )
      {
        // Search: try as WD custom order number first, then email
        if ( orderSearch.startsWith( 'WD' ) )
        {
          params.customOrderNumber = orderSearch;
        } else if ( orderSearch.includes( '@' ) )
        {
          params.email = orderSearch;
        } else
        {
          params.customOrderNumber = orderSearch;
        }
      }
      const data = await api.listWixOrders( params );
      setOrders( data.orders );
      setOrderCount( data.totalCount );
    } catch ( e )
    {
      console.error( 'Failed to fetch orders:', e );
    }
    setLoading( false );
  }, [ orderSearch, orderStatusFilter ] );

  const fetchCollections = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listWixCollections( 100 );
      setCollections( data.collections );
      setCollectionCount( data.totalCount );
    } catch ( e )
    {
      console.error( 'Failed to fetch categories:', e );
    }
    setLoading( false );
  }, [] );

  const fetchSites = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listWixSites();
      setSites( data );
    } catch ( e )
    {
      console.error( 'Failed to fetch sites:', e );
    }
    setLoading( false );
  }, [] );

  const fetchSamples = useCallback( async () => {
    try
    {
      const data = await api.getWixSampleProducts();
      setSampleProducts( data.products || [] );
    } catch ( e )
    {
      console.error( 'Failed to fetch samples:', e );
    }
  }, [] );

  useEffect( () => {
    if ( activeTab === 'products' ) fetchProducts();
    else if ( activeTab === 'orders' ) fetchOrders();
    else if ( activeTab === 'collections' ) fetchCollections();
    else if ( activeTab === 'settings' ) fetchSites();
    else if ( activeTab === 'manage' ) fetchSamples();
    else if ( activeTab === 'admin' ) refreshMetaCatalogPlan();
  // refreshMetaCatalogPlan intentionally excluded: it is a one-shot tab load, not a render loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ activeTab, fetchProducts, fetchOrders, fetchCollections, fetchSites, fetchSamples ] );

  const refreshMetaCatalogPlan = async () => {
    setMetaCatalogBusy( true );
    setMetaCatalogMessage( '' );
    const result = await api.getMetaCatalogSyncPlan();
    if ( result.ok )
    {
      setMetaCatalog( result.data );
    } else
    {
      setMetaCatalogMessage( result.failure.message );
    }
    setMetaCatalogBusy( false );
  };

  const runMetaCatalogAction = async ( action: 'propose' | 'approve' | 'apply' | 'readback' ) => {
    const planHash = metaCatalog?.planHash || metaCatalog?.currentPlanHash || '';
    if ( action !== 'propose' && !planHash )
    {
      setMetaCatalogMessage( 'Refresh the live plan before continuing.' );
      return;
    }
    setMetaCatalogBusy( true );
    setMetaCatalogMessage( '' );
    const result = await api.controlMetaCatalogSync( action, action === 'propose' ? undefined : planHash );
    if ( result.ok )
    {
      setMetaCatalog( prev => ( { ...( prev || {} as api.MetaCatalogSyncControl ), ...result.data } ) );
      setMetaCatalogMessage(
        action === 'propose' ? 'Proposal recorded against this exact plan.' :
          action === 'approve' ? 'Exact plan approved. Release gates remain unchanged.' :
            action === 'apply' ? 'Apply submitted. Use Readback to verify provider state.' :
              'Provider readback refreshed.'
      );
    } else
    {
      setMetaCatalogMessage( result.failure.message );
      // A 409 may carry useful server state, but apiCallResult deliberately normalises failures.
      // Refresh immediately so the operator sees the current plan rather than acting on stale UI.
      const fresh = await api.getMetaCatalogSyncPlan();
      if ( fresh.ok ) setMetaCatalog( fresh.data );
    }
    setMetaCatalogBusy( false );
  };

  const handleSync = async ( type: 'products' | 'orders' ) => {
    setSyncing( true );
    try
    {
      if ( type === 'products' )
      {
        await api.syncWixProducts();
        await fetchProducts();
      } else
      {
        await api.syncWixOrders();
        await fetchOrders();
      }
    } catch ( e )
    {
      console.error( 'Sync failed:', e );
    }
    setSyncing( false );
  };

  const handleProductClick = async ( product: api.WixProduct ) => {
    try
    {
      const full = await api.getWixProduct( product._id );
      setSelectedProduct( full || product );
    } catch
    {
      setSelectedProduct( product );
    }
  };

  const handleCreateProduct = async () => {
    if ( !newProduct.name || !newProduct.price ) return;
    setCreating( true );
    setCreateResult( null );
    try
    {
      const productData: any = {
        name: newProduct.name,
        productType: newProduct.productType,
        description: newProduct.description,
        priceData: { currency: newProduct.currency, price: parseFloat( newProduct.price ) },
        sku: newProduct.sku,
        ribbon: newProduct.ribbon,
        brand: newProduct.brand,
      };
      if ( newProduct.productType === 'physical' )
      {
        productData.weight = parseFloat( newProduct.weight ) || 0;
      }
      const result = await api.createWixProduct( productData );
      setCreateResult( { success: true, ...result } );
      setNewProduct( { name: '', productType: 'digital', description: '', price: '', currency: 'INR', sku: '', ribbon: 'BNB CLUB', brand: 'WECARE.DIGITAL', weight: '0' } );
    } catch ( e: any )
    {
      setCreateResult( { success: false, error: e.message } );
    }
    setCreating( false );
  };

  const handleBulkCreate = async () => {
    setCreating( true );
    setCreateResult( null );
    try
    {
      const products = JSON.parse( bulkJson );
      if ( !Array.isArray( products ) ) throw new Error( 'JSON must be an array of products' );
      const result = await api.bulkCreateWixProducts( products );
      setCreateResult( { success: true, bulk: true, ...result } );
    } catch ( e: any )
    {
      setCreateResult( { success: false, error: e.message } );
    }
    setCreating( false );
  };

  const handleLoadSample = ( sample: any ) => {
    if ( manageMode === 'single' )
    {
      setNewProduct( {
        name: sample.name || '',
        productType: sample.productType || 'digital',
        description: sample.description || '',
        price: String( sample.priceData?.price || sample.price || '' ),
        currency: sample.priceData?.currency || 'INR',
        sku: sample.sku || '',
        ribbon: sample.ribbon || 'BNB CLUB',
        brand: sample.brand || 'WECARE.DIGITAL',
        weight: String( sample.weight || 0 ),
      } );
    } else
    {
      setBulkJson( JSON.stringify( [ sample ], null, 2 ) );
    }
  };

  const handleLoadAllSamples = () => {
    setBulkJson( JSON.stringify( sampleProducts, null, 2 ) );
    setManageMode( 'bulk' );
  };

  const handleOrderClick = async ( order: api.WixOrder ) => {
    try
    {
      const full = await api.getWixOrder( order._id );
      setSelectedOrder( full || order );
    } catch
    {
      setSelectedOrder( order );
    }
  };

  // ---- Product columns ----
  const productColumns = [
    {
      key: 'image', header: '', width: '50px',
      render: ( p: api.WixProduct ) => (
        <div style={ { width: 40, height: 40, borderRadius: 8, overflow: 'hidden', background: '#f3f4f6' } }>
          { p.mainMedia?.url ? (
            <img src={ p.mainMedia.url } alt={ p.name } style={ { width: '100%', height: '100%', objectFit: 'cover' } } />
          ) : (
            <div style={ { width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9ca3af', fontSize: 12 } }>—</div>
          ) }
        </div>
      ),
    },
    {
      key: 'name', header: 'Product', render: ( p: api.WixProduct ) => (
        <div>
          <div style={ { fontWeight: 500 } }>{ p.name }</div>
          { p.sku && <div style={ { fontSize: 12, color: '#6b7280' } }>SKU: { p.sku }</div> }
        </div>
      )
    },
    {
      key: 'price', header: 'Price', render: ( p: api.WixProduct ) => (
        <span>{ p.formattedPrice || `${p.currency || '₹'}${p.price || 0}` }</span>
      )
    },
    {
      key: 'collections', header: 'Collections', render: ( p: api.WixProduct ) => (
        <div style={ { display: 'flex', gap: 4, flexWrap: 'wrap' } }>
          { ( p.collections || [] ).map( c => (
            <span key={ c._id } style={ { background: '#f9fafb', color: '#1a3a2a', padding: '2px 8px', borderRadius: 12, fontSize: 11 } }>{ c.name }</span>
          ) ) }
        </div>
      )
    },
    {
      key: 'stock', header: 'Stock', render: ( p: api.WixProduct ) => (
        <span style={ { color: p.inStock ? '#1a3a2a' : '#1a3a2a', fontWeight: 500, fontSize: 13 } }>
          { p.inStock ? ( p.quantityInStock !== undefined ? `${p.quantityInStock} in stock` : 'In Stock' ) : 'Out of Stock' }
        </span>
      )
    },
    {
      key: 'type', header: 'Type', render: ( p: api.WixProduct ) => (
        <span style={ { textTransform: 'capitalize', fontSize: 13 } }>{ p.productType || 'physical' }</span>
      )
    },
    {
      key: 'actions', header: '', width: '80px', render: ( p: api.WixProduct ) => (
        <button onClick={ () => handleProductClick( p ) } style={ { background: 'none', border: '1px solid #d1d5db', borderRadius: 8, padding: '4px 12px', cursor: 'pointer', fontSize: 12 } }>View</button>
      )
    },
  ];

  // ---- Order columns ----
  const orderColumns = [
    {
      key: 'number', header: 'Order #', width: '100px', render: ( o: api.WixOrder ) => (
        <div>
          <div style={ { fontWeight: 600 } }>{ o.customOrderNumber || o._summary?.customOrderNumber || o.customField?.value || o._summary?.externalOrderId || `#${o.number || '—'}` }</div>
        </div>
      )
    },
    {
      key: 'buyer', header: 'Buyer', render: ( o: api.WixOrder ) => {
        const email = ( o as any ).buyerEmail || o.buyerInfo?.email || o._summary?.buyerEmail || '';
        const name = ( o as any ).buyerName || o._summary?.billingName || '';
        return (
          <div>
            { name && <div style={ { fontWeight: 500, fontSize: 13 } }>{ name }</div> }
            <div style={ { fontSize: 12, color: '#6b7280' } }>{ email }</div>
          </div>
        );
      }
    },
    {
      key: 'items', header: 'Items', width: '60px', render: ( o: api.WixOrder ) => (
        <span>{ ( o as any ).lineItemCount || o.lineItems?.length || o._summary?.lineItemCount || 0 }</span>
      )
    },
    {
      key: 'total', header: 'Total', render: ( o: api.WixOrder ) => {
        const total = o.totals?.total || o._summary?.totalAmount || '0';
        const currency = o.currency || o._summary?.currency || 'INR';
        return <span style={ { fontWeight: 600 } }>{ currency === 'INR' ? '₹' : currency + ' ' }{ total }</span>;
      }
    },
    {
      key: 'payment', header: 'Payment', render: ( o: api.WixOrder ) => {
        const status = o.paymentStatus || o._summary?.paymentStatus || '';
        const color = status === 'PAID' ? '#1a3a2a' : status === 'NOT_PAID' ? '#1a3a2a' : '#1a3a2a';
        return <span style={ { color, fontWeight: 500, fontSize: 12, textTransform: 'uppercase' } }>{ status.replace( /_/g, ' ' ) }</span>;
      }
    },
    {
      key: 'fulfillment', header: 'Fulfillment', render: ( o: api.WixOrder ) => {
        const status = o.fulfillmentStatus || o._summary?.fulfillmentStatus || '';
        const color = status === 'FULFILLED' ? '#1a3a2a' : status === 'NOT_FULFILLED' ? '#6b7280' : '#1a3a2a';
        return <span style={ { color, fontWeight: 500, fontSize: 12, textTransform: 'uppercase' } }>{ status.replace( /_/g, ' ' ) || '—' }</span>;
      }
    },
    {
      key: 'date', header: 'Date', render: ( o: api.WixOrder ) => {
        const d = o.dateCreated || ( o as any ).createdDate || o._summary?.createdDate || '';
        return <span style={ { fontSize: 12, color: '#6b7280' } }>{ d ? new Date( d ).toLocaleDateString( 'en-IN', { day: '2-digit', month: 'short', year: 'numeric' } ) : '—' }</span>;
      }
    },
    {
      key: 'actions', header: '', width: '80px', render: ( o: api.WixOrder ) => (
        <button onClick={ () => handleOrderClick( o ) } style={ { background: 'none', border: '1px solid #d1d5db', borderRadius: 8, padding: '4px 12px', cursor: 'pointer', fontSize: 12 } }>View</button>
      )
    },
  ];

  // ---- Render ----
  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Store" description="Wix Store — Products, Orders, Collections" />
      <div className="store-page">
        <PageHeader
          title="Store"
          subtitle={ `Wix Store Integration — ${productCount} products, ${orderCount} orders` }
          icon="store"
          actions={
            <div style={ { display: 'flex', gap: 8 } }>
              <button onClick={ () => handleSync( 'products' ) } disabled={ syncing } style={ { display: 'flex', alignItems: 'center', gap: 6 } }>
                { syncing ? <Spinner size="sm" /> : null } Sync Products
              </button>
              <button onClick={ () => handleSync( 'orders' ) } disabled={ syncing } style={ { display: 'flex', alignItems: 'center', gap: 6 } }>
                { syncing ? <Spinner size="sm" /> : null } Sync Orders
              </button>
            </div>
          }
        />

        <Tabs items={ TABS } activeTab={ activeTab } onChange={ ( id ) => setActiveTab( id as TabType ) } />

        <div style={ { marginTop: 16 } }>
          {/* ---- PRODUCTS TAB ---- */ }
          { activeTab === 'products' && (
            <div>
              <div style={ { display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' } }>
                <input
                  type="text"
                  placeholder="Search products..."
                  value={ productSearch }
                  onChange={ e => setProductSearch( e.target.value ) }
                  onKeyDown={ e => e.key === 'Enter' && fetchProducts() }
                  style={ { flex: 1, padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 12, fontSize: 14, outline: 'none' } }
                />
                <button onClick={ fetchProducts }>Search</button>
                { selectedCollectionId && (
                  <button
                    onClick={ () => { setSelectedCollectionId( '' ); } }
                    className="btn btn-sm btn-secondary"
                  >
                    Clear filter
                  </button>
                ) }
              </div>
              { loading ? (
                <div style={ { textAlign: 'center', padding: 60 } }><Spinner size="lg" /></div>
              ) : products.length === 0 ? (
                <EmptyState icon="search" title="No Products Found" description="Connect your Wix Store and sync products to see them here." />
              ) : (
                <Table columns={ productColumns } data={ products } keyField="_id" />
              ) }
            </div>
          ) }

          {/* ---- ORDERS TAB ---- */ }
          { activeTab === 'orders' && (
            <div>
              <div style={ { display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' } }>
                <input
                  type="text"
                  placeholder="Search by WD order number or email..."
                  value={ orderSearch }
                  onChange={ e => setOrderSearch( e.target.value ) }
                  onKeyDown={ e => e.key === 'Enter' && fetchOrders() }
                  style={ { flex: 1, minWidth: 200, padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 12, fontSize: 14, outline: 'none' } }
                />
                <Select
                  ariaLabel="Payment status"
                  value={ orderStatusFilter }
                  onChange={ v => setOrderStatusFilter( v ) }
                  options={ ORDER_STATUS_FILTER_OPTIONS }
                  style={ FILTER_STYLE }
                />
                <button onClick={ fetchOrders }>Search</button>
              </div>
              { loading ? (
                <div style={ { textAlign: 'center', padding: 60 } }><Spinner size="lg" /></div>
              ) : orders.length === 0 ? (
                <EmptyState icon="order" title="No Orders Found" description="Orders from your Wix Store will appear here." />
              ) : (
                <Table columns={ orderColumns } data={ orders } keyField="_id" />
              ) }
            </div>
          ) }

          {/* ---- COLLECTIONS TAB ---- */ }
          { activeTab === 'collections' && (
            <div>
              { loading ? (
                <div style={ { textAlign: 'center', padding: 60 } }><Spinner size="lg" /></div>
              ) : collections.length === 0 ? (
                <EmptyState icon="default" title="No Collections" description="Create collections in your Wix Store to organize products." />
              ) : (
                <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 } }>
                  { collections.map( c => (
                    <div key={ c._id } style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 16, cursor: 'pointer' } }
                      onClick={ () => { setProductSearch( '' ); setSelectedCollectionId( c._id ); setActiveTab( 'products' ); } }>
                      { c.mainMedia?.url && (
                        <img src={ c.mainMedia.url } alt={ c.name } style={ { width: '100%', height: 140, objectFit: 'cover', borderRadius: 8, marginBottom: 12 } } />
                      ) }
                      <h4 style={ { margin: 0, fontSize: 16, fontWeight: 600 } }>{ c.name }</h4>
                      { c.description && <p style={ { margin: '4px 0 0', fontSize: 13, color: '#6b7280' } }>{ c.description }</p> }
                    </div>
                  ) ) }
                </div>
              ) }
            </div>
          ) }

          {/* ---- PRODUCT MANAGER TAB ---- */ }
          { activeTab === 'manage' && (
            <div style={ { maxWidth: 900 } }>
              {/* Mode Toggle */ }
              <div style={ { display: 'flex', gap: 8, marginBottom: 16 } }>
                <button
                  onClick={ () => setManageMode( 'single' ) }
                  style={ { padding: '8px 20px', borderRadius: 8, border: manageMode === 'single' ? '2px solid #1a3a2a' : '1px solid #d1d5db', background: manageMode === 'single' ? '#f9fafb' : '#fff', cursor: 'pointer', fontWeight: manageMode === 'single' ? 600 : 400, fontSize: 13 } }
                >
                  Single Product
                </button>
                <button
                  onClick={ () => setManageMode( 'bulk' ) }
                  style={ { padding: '8px 20px', borderRadius: 8, border: manageMode === 'bulk' ? '2px solid #1a3a2a' : '1px solid #d1d5db', background: manageMode === 'bulk' ? '#f9fafb' : '#fff', cursor: 'pointer', fontWeight: manageMode === 'bulk' ? 600 : 400, fontSize: 13 } }
                >
                  Bulk Create (JSON)
                </button>
              </div>

              {/* Sample Products */ }
              { sampleProducts.length > 0 && (
                <div style={ { background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 12, padding: 16, marginBottom: 16 } }>
                  <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 } }>
                    <span style={ { fontWeight: 600, fontSize: 14 } }>BNB CLUB Templates</span>
                    <button onClick={ handleLoadAllSamples } style={ { fontSize: 12, padding: '4px 12px', border: '1px solid #86efac', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#1a3a2a' } }>
                      Load All → Bulk
                    </button>
                  </div>
                  <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap' } }>
                    { sampleProducts.map( ( s: any, i: number ) => (
                      <button key={ i } onClick={ () => handleLoadSample( s ) }
                        style={ { padding: '6px 14px', borderRadius: 8, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer', fontSize: 12, textAlign: 'left', maxWidth: 260 } }>
                        <div style={ { fontWeight: 500 } }>{ s.name }</div>
                        <div style={ { color: '#6b7280', fontSize: 11 } }>₹{ s.priceData?.price || s.price } · { s.sku }</div>
                      </button>
                    ) ) }
                  </div>
                </div>
              ) }

              {/* Single Product Form */ }
              { manageMode === 'single' && (
                <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 20 } }>
                  <h3 style={ { margin: '0 0 16px', fontSize: 16, fontWeight: 600 } }>Create Product</h3>
                  <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 } }>
                    <div style={ { gridColumn: '1 / -1' } }>
                      <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Product Name *</label>
                      <input type="text" value={ newProduct.name } onChange={ e => setNewProduct( { ...newProduct, name: e.target.value } ) } placeholder="Visa Assistance — Tourist Visa"
                        style={ { width: '100%', padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 10, fontSize: 14, outline: 'none', boxSizing: 'border-box' } } />
                    </div>
                    <div>
                      <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Price *</label>
                      <input type="number" value={ newProduct.price } onChange={ e => setNewProduct( { ...newProduct, price: e.target.value } ) } placeholder="2999"
                        style={ { width: '100%', padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 10, fontSize: 14, outline: 'none', boxSizing: 'border-box' } } />
                    </div>
                    <div>
                      { /* The caption is an UNASSOCIATED <label> - no `for`, no wrapped control -
                           so it was never a name source. It stays, keeping its own type and
                           spacing, and the control takes `ariaLabel`. The four currency values
                           are unchanged: INR is the only one this store settles in, and the list
                           is a Wix catalogue field rather than a payment decision. */ }
                      <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Currency</label>
                      <Select ariaLabel="Currency" value={ newProduct.currency }
                        onChange={ v => setNewProduct( { ...newProduct, currency: v } ) }
                        options={ CURRENCY_OPTIONS } style={ FULL_WIDTH } />
                    </div>
                    <div>
                      <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>SKU</label>
                      <input type="text" value={ newProduct.sku } onChange={ e => setNewProduct( { ...newProduct, sku: e.target.value } ) } placeholder="BNB-VISA-SINGLE-001"
                        style={ { width: '100%', padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 10, fontSize: 14, outline: 'none', boxSizing: 'border-box' } } />
                    </div>
                    <div>
                      <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Type</label>
                      <Select ariaLabel="Product type" value={ newProduct.productType }
                        onChange={ v => setNewProduct( { ...newProduct, productType: v as 'digital' | 'physical' } ) }
                        options={ PRODUCT_TYPE_OPTIONS } style={ FULL_WIDTH } />
                    </div>
                    <div>
                      <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Ribbon</label>
                      <input type="text" value={ newProduct.ribbon } onChange={ e => setNewProduct( { ...newProduct, ribbon: e.target.value } ) } placeholder="BNB CLUB"
                        style={ { width: '100%', padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 10, fontSize: 14, outline: 'none', boxSizing: 'border-box' } } />
                    </div>
                    <div>
                      <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Brand</label>
                      <input type="text" value={ newProduct.brand } onChange={ e => setNewProduct( { ...newProduct, brand: e.target.value } ) } placeholder="WECARE.DIGITAL"
                        style={ { width: '100%', padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 10, fontSize: 14, outline: 'none', boxSizing: 'border-box' } } />
                    </div>
                    { newProduct.productType === 'physical' && (
                      <div>
                        <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Weight (kg)</label>
                        <input type="number" value={ newProduct.weight } onChange={ e => setNewProduct( { ...newProduct, weight: e.target.value } ) } placeholder="0"
                          style={ { width: '100%', padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 10, fontSize: 14, outline: 'none', boxSizing: 'border-box' } } />
                      </div>
                    ) }
                    <div style={ { gridColumn: '1 / -1' } }>
                      <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Description (HTML)</label>
                      <textarea value={ newProduct.description } onChange={ e => setNewProduct( { ...newProduct, description: e.target.value } ) } rows={ 5 } placeholder="<p>Product description...</p>"
                        style={ { width: '100%', padding: '10px 14px', border: '1.5px solid #d1d5db', borderRadius: 10, fontSize: 13, outline: 'none', fontFamily: 'monospace', resize: 'vertical', boxSizing: 'border-box' } } />
                    </div>
                  </div>
                  <div style={ { marginTop: 16, display: 'flex', gap: 8, alignItems: 'center' } }>
                    <button onClick={ handleCreateProduct } disabled={ creating || !newProduct.name || !newProduct.price }
                      style={ { padding: '10px 24px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 10, cursor: 'pointer', fontWeight: 600, fontSize: 14, opacity: creating || !newProduct.name || !newProduct.price ? 0.5 : 1 } }>
                      { creating ? 'Creating...' : 'Create Product' }
                    </button>
                  </div>
                </div>
              ) }

              {/* Bulk Create */ }
              { manageMode === 'bulk' && (
                <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 20 } }>
                  <h3 style={ { margin: '0 0 16px', fontSize: 16, fontWeight: 600 } }>Bulk Create Products</h3>
                  <label style={ { display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4, color: '#374151' } }>Products JSON Array</label>
                  <textarea value={ bulkJson } onChange={ e => setBulkJson( e.target.value ) } rows={ 14 } placeholder='[{"name": "Product 1", "productType": "digital", "priceData": {"currency": "INR", "price": 999}, "sku": "SKU-001"}]'
                    style={ { width: '100%', padding: '12px 14px', border: '1.5px solid #d1d5db', borderRadius: 10, fontSize: 12, outline: 'none', fontFamily: 'monospace', resize: 'vertical', boxSizing: 'border-box' } } />
                  <div style={ { marginTop: 16, display: 'flex', gap: 8, alignItems: 'center' } }>
                    <button onClick={ handleBulkCreate } disabled={ creating || !bulkJson.trim() }
                      style={ { padding: '10px 24px', background: '#d1f470', color: '#1a3a2a', border: 'none', borderRadius: 10, cursor: 'pointer', fontWeight: 600, fontSize: 14, opacity: creating || !bulkJson.trim() ? 0.5 : 1 } }>
                      { creating ? 'Creating...' : 'Bulk Create' }
                    </button>
                  </div>
                </div>
              ) }

              {/* Result */ }
              { createResult && (
                <div style={ { marginTop: 16, background: createResult.success ? '#f9fafb' : '#f3f4f6', border: `1px solid ${createResult.success ? '#e5e7eb' : '#e5e7eb'}`, borderRadius: 12, padding: 16 } }>
                  <div style={ { fontWeight: 600, fontSize: 14, color: createResult.success ? '#1a3a2a' : '#6b7280', marginBottom: 8 } }>
                    { createResult.success ? ( createResult.bulk ? `Bulk: ${createResult.succeeded}/${createResult.total} created` : 'Product Created' ) : 'Error' }
                  </div>
                  <pre style={ { fontSize: 12, margin: 0, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto', color: '#374151' } }>
                    { JSON.stringify( createResult, null, 2 ) }
                  </pre>
                </div>
              ) }
            </div>
          ) }

          {/* ---- STORE ADMIN TAB ---- */ }
          { activeTab === 'admin' && (
            <div style={ { maxWidth: 900 } }>
              <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 20, marginBottom: 16 } }>
                <div style={ { display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', marginBottom: 14 } }>
                  <div>
                    <h3 style={ { margin: '0 0 4px', fontSize: 16, fontWeight: 600 } }>WhatsApp Catalog Approval</h3>
                    <p style={ { margin: 0, fontSize: 13, color: '#6b7280', lineHeight: 1.5 } }>
                      The proposal is recomputed from live Wix and Meta state. Approval is bound to the exact hash below.
                      Background sync cannot spend an approval; Apply also requires the server release gates.
                    </p>
                  </div>
                  <button onClick={ refreshMetaCatalogPlan } disabled={ metaCatalogBusy }
                    style={ { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', cursor: metaCatalogBusy ? 'default' : 'pointer' } }>
                    { metaCatalogBusy ? 'Checking…' : 'Refresh plan' }
                  </button>
                </div>

                { metaCatalog ? (
                  <>
                    <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 12 } }>
                      <div style={ statBox }><span style={ statLabel }>Catalog</span><span style={ statValue }>{ metaCatalog.catalogId }</span></div>
                      <div style={ statBox }><span style={ statLabel }>Create</span><span style={ statValue }>{ metaCatalog.counts?.create ?? 0 }</span></div>
                      <div style={ statBox }><span style={ statLabel }>Update</span><span style={ statValue }>{ metaCatalog.counts?.update ?? 0 }</span></div>
                      <div style={ statBox }><span style={ statLabel }>Retire</span><span style={ statValue }>{ metaCatalog.counts?.retire ?? 0 }</span></div>
                      <div style={ statBox }><span style={ statLabel }>Approval</span><span style={ statValue }>{ metaCatalog.approval?.status || 'Not proposed' }</span></div>
                      <div style={ statBox }><span style={ statLabel }>Release gates</span><span style={ statValue }>{ metaCatalog.enabled && metaCatalog.dryRun === false ? 'Open' : 'Closed' }</span></div>
                    </div>
                    <div style={ { background: '#f9fafb', borderRadius: 8, padding: 10, marginBottom: 12, fontSize: 12 } }>
                      <strong>Exact plan hash</strong><br />
                      <code style={ { wordBreak: 'break-all' } }>{ metaCatalog.planHash || metaCatalog.currentPlanHash || '—' }</code>
                      { ( metaCatalog.blocked?.length || 0 ) > 0 && (
                        <div style={ { marginTop: 8, color: '#6b7280' } }>Blocked: { metaCatalog.blocked?.join( ', ' ) }</div>
                      ) }
                    </div>
                    <div style={ { display: 'flex', flexWrap: 'wrap', gap: 8 } }>
                      <button onClick={ () => runMetaCatalogAction( 'propose' ) } disabled={ metaCatalogBusy || ( metaCatalog.blocked?.length || 0 ) > 0 }>
                        Record proposal
                      </button>
                      <button onClick={ () => runMetaCatalogAction( 'approve' ) }
                        disabled={ metaCatalogBusy || metaCatalog.approval?.status !== 'PROPOSED' }>
                        Approve exact plan
                      </button>
                      <button onClick={ () => runMetaCatalogAction( 'apply' ) }
                        disabled={ metaCatalogBusy || metaCatalog.approval?.status !== 'APPROVED' || !metaCatalog.enabled || metaCatalog.dryRun !== false }>
                        Apply approved plan
                      </button>
                      <button onClick={ () => runMetaCatalogAction( 'readback' ) }
                        disabled={ metaCatalogBusy || ![ 'APPLYING', 'APPLY_SUBMITTED', 'APPLIED' ].includes( metaCatalog.approval?.status || '' ) }>
                        Provider readback
                      </button>
                    </div>
                    { ( !metaCatalog.enabled || metaCatalog.dryRun !== false ) && (
                      <p style={ { margin: '10px 0 0', fontSize: 12, color: '#6b7280' } }>
                        Apply is intentionally locked: production catalog writes are disabled / dry-run.
                      </p>
                    ) }
                  </>
                ) : (
                  <p style={ { color: '#6b7280', fontSize: 13 } }>{ metaCatalogBusy ? 'Reading live Wix + Meta plan…' : 'No live plan loaded.' }</p>
                ) }
                { metaCatalogMessage && <p style={ { margin: '10px 0 0', fontSize: 12, color: '#374151' } }>{ metaCatalogMessage }</p> }
              </div>

              <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 20, marginBottom: 16 } }>
                <h3 style={ { margin: '0 0 8px', fontSize: 16, fontWeight: 600 } }>Headless Commerce Architecture</h3>
                <p style={ { fontSize: 13, color: '#6b7280', margin: 0, lineHeight: 1.6 } }>
                  Amplify owns the storefront and checkout UI. Wix is a backend-only commerce service accessed through REST APIs.
                  There is no Wix Editor or Velo runtime dependency in WECARE.DIGITAL.
                </p>
              </div>

              <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12, marginBottom: 16 } }>
                <div style={ adminCard }><span style={ adminLabel }>Products</span><span style={ adminVal }>Catalog V3</span></div>
                <div style={ adminCard }><span style={ adminLabel }>Organization</span><span style={ adminVal }>Categories V3</span></div>
                <div style={ adminCard }><span style={ adminLabel }>Stock</span><span style={ adminVal }>Inventory Items V3</span></div>
                <div style={ adminCard }><span style={ adminLabel }>Orders</span><span style={ adminVal }>eCommerce Orders</span></div>
                <div style={ adminCard }><span style={ adminLabel }>Cart / Checkout</span><span style={ adminVal }>Cart V2 + AWS UI</span></div>
                <div style={ adminCard }><span style={ adminLabel }>Payment</span><span style={ adminVal }>Razorpay via AWS</span></div>
              </div>

              <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 20 } }>
                <h3 style={ { margin: '0 0 12px', fontSize: 16, fontWeight: 600 } }>Commerce API</h3>
                <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 13 } }>
                  { [
                    [ 'GET', '/wix-store/products', 'Catalog V3 products' ],
                    [ 'GET', '/wix-store/products/{id}', 'Product + variants + inventory' ],
                    [ 'GET', '/wix-store/collections', 'Categories V3 compatibility route' ],
                    [ 'GET', '/wix-store/inventory', 'Inventory Items V3' ],
                    [ 'GET', '/wix-store/orders', 'eCommerce orders' ],
                    [ 'POST', '/wix-store/create-product', 'Create Catalog V3 product' ],
                    [ 'POST', '/wix-store/update-product', 'Revision-safe product update' ],
                    [ 'POST', '/wix-store/sync/products', 'Refresh AWS product cache' ],
                  ].map( ( [ method, path, description ] ) => (
                    <div key={ path } style={ { padding: 10, borderRadius: 8, background: '#f9fafb' } }>
                      <div><strong>{ method }</strong> <code>{ path }</code></div>
                      <div style={ { color: '#6b7280', marginTop: 3 } }>{ description }</div>
                    </div>
                  ) ) }
                </div>
              </div>
            </div>
          ) }

          {/* ---- SETTINGS TAB ---- */ }
          { activeTab === 'settings' && (
            <div style={ { maxWidth: 700 } }>
              <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 20, marginBottom: 16 } }>
                <h3 style={ { margin: '0 0 12px', fontSize: 16, fontWeight: 600 } }>Connected Wix Sites</h3>
                { loading ? (
                  <Spinner size="md" />
                ) : sites.length === 0 ? (
                  <p style={ { color: '#6b7280', fontSize: 14 } }>No sites found. Check your WIX_API_KEY and WIX_ACCOUNT_ID configuration.</p>
                ) : (
                  <div style={ { display: 'flex', flexDirection: 'column', gap: 12 } }>
                    { sites.map( ( s: any ) => (
                      <div key={ s.id } style={ { display: 'flex', alignItems: 'center', gap: 12, padding: 12, background: '#f9fafb', borderRadius: 8 } }>
                        { s.thumbnail && <img src={ s.thumbnail } alt={ s.displayName } style={ { width: 48, height: 36, borderRadius: 6, objectFit: 'cover' } } /> }
                        <div style={ { flex: 1 } }>
                          <div style={ { fontWeight: 500 } }>{ s.displayName }</div>
                          <div style={ { fontSize: 12, color: '#6b7280' } }>ID: { s.id }</div>
                        </div>
                        <span style={ { fontSize: 11, padding: '2px 8px', borderRadius: 12, background: s.published ? '#f3f4f6' : '#f9fafb', color: s.published ? '#1a3a2a' : '#1a3a2a' } }>
                          { s.published ? 'Published' : 'Draft' }
                        </span>
                        { s.viewUrl && (
                          <a href={ s.viewUrl } target="_blank" rel="noopener noreferrer" style={ { fontSize: 12, color: '#1a3a2a' } }>Visit →</a>
                        ) }
                      </div>
                    ) ) }
                  </div>
                ) }
              </div>
              <div style={ { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 20 } }>
                <h3 style={ { margin: '0 0 8px', fontSize: 16, fontWeight: 600 } }>Integration Mode</h3>
                <p style={ { fontSize: 13, color: '#6b7280', margin: '0 0 12px' } }>
                  API-only self-managed headless. The Lambda reads credentials and project identity from AWS runtime configuration.
                </p>
                <div style={ { fontSize: 13, background: '#f9fafb', padding: 12, borderRadius: 8, fontFamily: 'monospace', lineHeight: 1.8 } }>
                  Catalog = Wix Stores V3<br />
                  Inventory = Inventory Items V3<br />
                  Cart = eCommerce Cart V2<br />
                  Frontend = AWS Amplify / Next.js
                </div>
              </div>
            </div>
          ) }
        </div>

        {/* ---- PRODUCT DETAIL MODAL ---- */ }
        <Modal isOpen={ !!selectedProduct } onClose={ () => setSelectedProduct( null ) } title={ selectedProduct?.name || 'Product Detail' } size="lg">
          { selectedProduct && (
            <div style={ { display: 'flex', flexDirection: 'column', gap: 16 } }>
              <div style={ { display: 'flex', gap: 16 } }>
                { selectedProduct.mainMedia?.url && (
                  <img src={ selectedProduct.mainMedia.url } alt={ selectedProduct.name } style={ { width: 160, height: 160, objectFit: 'cover', borderRadius: 12 } } />
                ) }
                <div style={ { flex: 1 } }>
                  <h3 style={ { margin: 0 } }>{ selectedProduct.name }</h3>
                  <p style={ { color: '#6b7280', fontSize: 14, margin: '4px 0' } }>{ selectedProduct.description }</p>
                  <div style={ { display: 'flex', gap: 16, marginTop: 8 } }>
                    <div><span style={ { fontSize: 12, color: '#6b7280' } }>Price</span><br /><span style={ { fontWeight: 600, fontSize: 18 } }>{ selectedProduct.formattedPrice || `₹${selectedProduct.price}` }</span></div>
                    <div><span style={ { fontSize: 12, color: '#6b7280' } }>SKU</span><br /><span style={ { fontWeight: 500 } }>{ selectedProduct.sku || '—' }</span></div>
                    <div><span style={ { fontSize: 12, color: '#6b7280' } }>Stock</span><br /><span style={ { fontWeight: 500, color: selectedProduct.inStock ? '#1a3a2a' : '#1a3a2a' } }>{ selectedProduct.inStock ? `${selectedProduct.quantityInStock ?? 'Yes'}` : 'Out' }</span></div>
                    <div><span style={ { fontSize: 12, color: '#6b7280' } }>Type</span><br /><span style={ { fontWeight: 500, textTransform: 'capitalize' } }>{ selectedProduct.productType }</span></div>
                  </div>
                </div>
              </div>
              { selectedProduct.collections?.length > 0 && (
                <div>
                  <span style={ { fontSize: 12, color: '#6b7280' } }>Collections</span>
                  <div style={ { display: 'flex', gap: 6, marginTop: 4 } }>
                    { selectedProduct.collections.map( c => (
                      <span key={ c._id } style={ { background: '#f9fafb', color: '#1a3a2a', padding: '3px 10px', borderRadius: 12, fontSize: 12 } }>{ c.name }</span>
                    ) ) }
                  </div>
                </div>
              ) }
              { selectedProduct.productOptions?.length > 0 && (
                <div>
                  <span style={ { fontSize: 12, color: '#6b7280' } }>Options</span>
                  <div style={ { marginTop: 4 } }>
                    { selectedProduct.productOptions.map( ( opt: any, i: number ) => (
                      <div key={ i } style={ { fontSize: 13 } }>{ opt.name }: { ( opt.choices || [] ).map( ( c: any ) => c.description || c.value ).join( ', ' ) }</div>
                    ) ) }
                  </div>
                </div>
              ) }
              { selectedProduct.variants?.length > 1 && (
                <div>
                  <span style={ { fontSize: 12, color: '#6b7280' } }>Variants ({ selectedProduct.variants.length })</span>
                  <div style={ { marginTop: 4, maxHeight: 200, overflowY: 'auto' } }>
                    { selectedProduct.variants.map( ( v: any, i: number ) => (
                      <div key={ i } style={ { display: 'flex', gap: 12, padding: '6px 0', borderBottom: '1px solid #f3f4f6', fontSize: 13 } }>
                        <span style={ { flex: 1 } }>{ Object.values( v.choices || {} ).join( ' / ' ) || `Variant ${i + 1}` }</span>
                        <span style={ { fontWeight: 500 } }>{ v.variant?.priceData?.formatted?.price || '—' }</span>
                        <span style={ { color: '#6b7280' } }>SKU: { v.variant?.sku || '—' }</span>
                      </div>
                    ) ) }
                  </div>
                </div>
              ) }
            </div>
          ) }
        </Modal>

        {/* ---- ORDER DETAIL MODAL ---- */ }
        <Modal isOpen={ !!selectedOrder } onClose={ () => setSelectedOrder( null ) } title={ `Order ${selectedOrder?.customOrderNumber || selectedOrder?._summary?.customOrderNumber || selectedOrder?.customField?.value || selectedOrder?._summary?.externalOrderId || '#' + ( selectedOrder?.number || '—' )}` } size="lg">
          { selectedOrder && ( () => {
            const s = selectedOrder._summary || {};
            const buyerEmail = ( selectedOrder as any ).buyerEmail || s.buyerEmail || selectedOrder.buyerInfo?.email || '';
            const buyerName = ( selectedOrder as any ).buyerName || s.billingName || '';
            const buyerPhone = ( selectedOrder as any ).buyerPhone || s.billingPhone || '';
            const total = selectedOrder.totals?.total || s.totalAmount || '0';
            const currency = selectedOrder.currency || s.currency || 'INR';
            const customNum = selectedOrder.customOrderNumber || s.customOrderNumber || selectedOrder.customField?.value || s.externalOrderId || '';
            const items = ( selectedOrder as any ).lineItemsSummary || s.lineItems || selectedOrder.lineItems || [];

            return (
              <div style={ { display: 'flex', flexDirection: 'column', gap: 16 } }>
                {/* Order summary */ }
                <div style={ { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 } }>
                  <div style={ statBox }><span style={ statLabel }>Order ID</span><span style={ statValue }>{ customNum || `#${selectedOrder.number || s.orderNumber || '—'}` }</span></div>
                  <div style={ statBox }><span style={ statLabel }>Total</span><span style={ statValue }>{ currency === 'INR' ? '₹' : currency + ' ' }{ total }</span></div>
                  <div style={ statBox }><span style={ statLabel }>Payment</span><span style={ { ...statValue, color: ( selectedOrder.paymentStatus || s.paymentStatus ) === 'PAID' ? '#1a3a2a' : '#1a3a2a' } }>{ ( selectedOrder.paymentStatus || s.paymentStatus || '' ).replace( /_/g, ' ' ) }</span></div>
                  <div style={ statBox }><span style={ statLabel }>Fulfillment</span><span style={ statValue }>{ ( selectedOrder.fulfillmentStatus || s.fulfillmentStatus || '—' ).replace( /_/g, ' ' ) }</span></div>
                  <div style={ statBox }><span style={ statLabel }>Date</span><span style={ statValue }>{ new Date( selectedOrder.dateCreated || ( selectedOrder as any ).createdDate || s.createdDate || '' ).toLocaleDateString( 'en-IN' ) }</span></div>
                </div>

                {/* Buyer info */ }
                <div style={ { background: '#f9fafb', borderRadius: 8, padding: 12 } }>
                  <span style={ { fontSize: 12, color: '#6b7280', fontWeight: 600 } }>Buyer</span>
                  <div style={ { marginTop: 4, fontSize: 14 } }>
                    { buyerName && <div>{ buyerName }</div> }
                    { buyerEmail && <div style={ { color: '#6b7280' } }>{ buyerEmail }</div> }
                    { buyerPhone && <div style={ { color: '#6b7280' } }>{ buyerPhone }</div> }
                  </div>
                  { selectedOrder.buyerNote && <div style={ { marginTop: 8, fontSize: 13, fontStyle: 'italic', color: '#6b7280' } }>Note: { selectedOrder.buyerNote }</div> }
                </div>

                {/* Line items */ }
                <div>
                  <span style={ { fontSize: 12, color: '#6b7280', fontWeight: 600 } }>Line Items ({ items.length })</span>
                  <div style={ { marginTop: 8 } }>
                    { items.map( ( item: any, i: number ) => (
                      <div key={ i } style={ { display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid #f3f4f6' } }>
                        { ( item.image?.url || item.mediaItem?.url ) && (
                          <img src={ item.image?.url || item.mediaItem?.url } alt={ item.name } style={ { width: 36, height: 36, borderRadius: 6, objectFit: 'cover' } } />
                        ) }
                        <div style={ { flex: 1 } }>
                          <div style={ { fontWeight: 500, fontSize: 14 } }>{ item.name || item.productName }</div>
                          { item.sku && <div style={ { fontSize: 11, color: '#6b7280' } }>SKU: { item.sku }</div> }
                        </div>
                        <span style={ { fontSize: 13, color: '#6b7280' } }>×{ item.quantity }</span>
                        <span style={ { fontWeight: 500, fontSize: 14 } }>{ currency === 'INR' ? '₹' : '' }{ item.price || item.totalPrice || '0' }</span>
                      </div>
                    ) ) }
                  </div>
                </div>

                {/* Transactions & Fulfillments */ }
                { selectedOrder._transactions && (
                  <div>
                    <span style={ { fontSize: 12, color: '#6b7280', fontWeight: 600 } }>Transactions</span>
                    <pre style={ { background: '#f9fafb', padding: 12, borderRadius: 8, fontSize: 12, overflow: 'auto', maxHeight: 150 } }>
                      { JSON.stringify( selectedOrder._transactions, null, 2 ) }
                    </pre>
                  </div>
                ) }
                { selectedOrder._fulfillments && Array.isArray( selectedOrder._fulfillments ) && selectedOrder._fulfillments.length > 0 && (
                  <div>
                    <span style={ { fontSize: 12, color: '#6b7280', fontWeight: 600 } }>Fulfillments</span>
                    <pre style={ { background: '#f9fafb', padding: 12, borderRadius: 8, fontSize: 12, overflow: 'auto', maxHeight: 150 } }>
                      { JSON.stringify( selectedOrder._fulfillments, null, 2 ) }
                    </pre>
                  </div>
                ) }
              </div>
            );
          } )() }
        </Modal>
      </div>
    </Layout>
  );
};

const statBox: React.CSSProperties = { background: '#f9fafb', borderRadius: 8, padding: '10px 12px' };
const statLabel: React.CSSProperties = { fontSize: 11, color: '#6b7280', display: 'block' };
const statValue: React.CSSProperties = { fontSize: 15, fontWeight: 600, display: 'block', marginTop: 2 };
const adminCard: React.CSSProperties = { background: '#f9fafb', borderRadius: 8, padding: '10px 12px' };
const adminLabel: React.CSSProperties = { fontSize: 11, color: '#6b7280', display: 'block' };
const adminVal: React.CSSProperties = { fontSize: 14, fontWeight: 600, display: 'block', marginTop: 2 };
const actionBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', background: '#f9fafb', borderRadius: 10, textDecoration: 'none', color: 'inherit', border: '1px solid #e5e7eb', transition: 'background 0.15s' };

export default StorePage;
