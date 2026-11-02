import React from 'react';
import {
  CONTRIBUTION_CHOICES,
  CONTRIBUTION_PRODUCT_ID,
} from '../../../config/contribution';
import {
  fetchContributionPrice,
  type ServicePrice,
} from '../../../lib/servicePricing';

const UNAVAILABLE: ServicePrice = { available: false };

export default function ContributeWorkspace () {
  const [ price, setPrice ] = React.useState<ServicePrice>( UNAVAILABLE );
  const [ loading, setLoading ] = React.useState( true );
  const choice = CONTRIBUTION_CHOICES[ 0 ];

  React.useEffect( () => {
    let active = true;
    setLoading( true );
    void fetchContributionPrice()
      .then( next => { if ( active ) setPrice( next ); } )
      .finally( () => { if ( active ) setLoading( false ); } );
    return () => { active = false; };
  }, [] );

  const amount = price.available ? `₹${ price.rupees }` : 'Unavailable';
  const payable = price.available && price.breakdown
    ? `₹${ Math.trunc( price.breakdown.totalPayablePaise / 100 ).toLocaleString( 'en-IN' ) }${ price.breakdown.totalPayablePaise % 100 ? `.${ String( price.breakdown.totalPayablePaise % 100 ).padStart( 2, '0' ) }` : '' }`
    : amount;

  return (
    <section className="contribute-workspace" aria-labelledby="contribute-title">
      <header className="contribute-head">
        <p>Service · Contribute</p>
        <h1 id="contribute-title">Contribute</h1>
        <span>Voluntary payment · no fulfilment Flow</span>
      </header>

      <div className="contribute-card">
        <div className="contribute-grid">
          <div>
            <small>Live catalog amount</small>
            <strong>{ loading ? 'Loading…' : amount }</strong>
          </div>
          <div>
            <small>Payable</small>
            <strong>{ loading ? 'Loading…' : payable }</strong>
          </div>
          <div>
            <small>SKU</small>
            <strong>{ choice?.variantId || 'Not configured' }</strong>
          </div>
          <div>
            <small>Flow</small>
            <strong>None</strong>
          </div>
        </div>

        <p className="contribute-note">
          Contribute uses its own server-authoritative ₹300 pricing. Its Review and Pay
          breakdown includes supply GST, Delight, ₹15 Express, convenience and fee GST
          inside that total. WhatsApp sends and payments stay blocked until release checks pass.
        </p>

        <div className="contribute-actions">
          <a
            className={ `contribute-cta${ price.available ? '' : ' disabled' }` }
            href={ price.available ? '/orders/' : undefined }
            aria-disabled={ !price.available }
            onClick={ event => { if ( !price.available ) event.preventDefault(); } }
          >
            Open customer Orders
          </a>
          <span data-wc-no-translate="true">{ CONTRIBUTION_PRODUCT_ID }</span>
        </div>
      </div>

      <style jsx>{`
        .contribute-workspace{padding:4px 0 40px}
        .contribute-head{margin:0 0 20px}
        .contribute-head p{margin:0 0 6px;font-size:13px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted)}
        .contribute-head h1{margin:0;color:var(--text-primary);font-size:clamp(28px,3.2vw,40px);line-height:1.08;letter-spacing:-1.2px}
        .contribute-head span{display:block;margin-top:8px;color:var(--text-muted);font-size:15px}
        .contribute-card{border:2px solid var(--border);border-radius:16px;padding:22px;background:var(--surface)}
        .contribute-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
        .contribute-grid>div{border:1px solid var(--border);border-radius:12px;padding:14px;background:var(--surface-raised,#fff)}
        .contribute-grid small{display:block;color:var(--text-muted);font-size:12px;font-weight:700;margin-bottom:6px}
        .contribute-grid strong{display:block;color:var(--text-primary);font-size:18px;overflow-wrap:anywhere}
        .contribute-note{margin:18px 0 0;max-width:760px;color:var(--text-muted);font-size:15px;line-height:1.55}
        .contribute-actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:20px}
        .contribute-cta{display:inline-flex;align-items:center;justify-content:center;min-height:46px;padding:0 18px;border:2px solid var(--accent);border-radius:999px;background:var(--lime);color:var(--accent);font-weight:800;text-decoration:none}
        .contribute-cta.disabled{opacity:.45;cursor:not-allowed}
        .contribute-actions span{color:var(--text-muted);font:600 12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
        @media(max-width:800px){.contribute-grid{grid-template-columns:1fr 1fr}}
        @media(max-width:520px){.contribute-grid{grid-template-columns:1fr}.contribute-actions{align-items:stretch}.contribute-cta{width:100%}}
      `}</style>
    </section>
  );
}
