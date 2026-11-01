import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import VoiceSearchMic from './VoiceSearchMic';
import { publicActionText } from '../lib/publicActionNotices';
import { symbol, type MaterialSymbol } from '../config/materialSymbols';

type TravelMode = 'flights' | 'hotels' | 'activities' | 'rail' | 'car' | 'bus';

interface TravelResult {
  id: string;
  sourceLabel: string;
  /** Optional backend/provider identifier or raw display name from a live bridge response. */
  provider?: string;
  title: string;
  description: string;
  meta: string[];
  price: string;
  websiteUrl?: string;
  whatsappUrl?: string;
  providerRef?: string;
  offerId?: string;
  quoteExpiresAt?: string;
  cancellationSummary?: string;
  availability?: string;
  checkoutReady?: boolean;
}

interface TravelResponse {
  source?: 'api' | 'mcp' | 'demo';
  summary?: string;
  results: TravelResult[];
}

interface ModeConfig {
  label: string;
  /** A ligature in the shipped icon-font subset; see config/materialSymbols.ts. */
  icon: MaterialSymbol;
  placeholder: string;
  understanding: string;
  chips: string[];
  results: Array<[ string, string, string, string, string, string ]>;
}

const MODE_ORDER: TravelMode[] = [ 'flights', 'hotels', 'activities', 'car' ];

const MODE_RESULT_SUMMARIES: Record<TravelMode, string> = {
  flights: 'I found a few flight options that balance timing, stops and fare rules. I’d start with the first one.',
  hotels: 'I found a few stays that fit the location, comfort and flexibility you described. I’d start with the first one.',
  activities: 'I found a few options that fit your timing, pace and budget. I’d start with the first one.',
  rail: 'I found a few rail options that fit the arrival time and class you described. I’d start with the first one.',
  car: 'I found a few transfer options that fit the pickup, space and comfort you described. I’d start with the first one.',
  bus: 'I found a few bus options that fit your boarding point, timing and fare preferences. I’d start with the first one.',
};

const MODES: Record<TravelMode, ModeConfig> = {
  flights: {
    label: 'Flights',
    icon: 'flight',
    placeholder: 'e.g. Kolkata to Delhi next Friday, return Sunday evening. 2 adults, cabin baggage only, prefer morning departure.',
    understanding: 'I’ll compare departure windows, stops, baggage, fare rules and arrival time against the trip you described.',
    chips: [ 'Morning · nonstop', 'Cheapest flexible fare', '2 travellers · weekend', 'Cabin bag only' ],
    results: [
      [ 'Best timing option', 'Morning nonstop with the cleanest arrival window for the rest of the day.', 'Nonstop', '2h 20m', 'Cabin bag', '~₹6,480' ],
      [ 'Best value option', 'Slightly later departure with a lower total fare and a similar arrival time.', 'Nonstop', '2h 25m', 'Cabin bag', '~₹5,920' ],
      [ 'Most flexible option', 'Higher fare, but easier change terms for a weekend plan that may move.', 'Nonstop', '2h 30m', 'Flexible', '~₹7,350' ],
    ],
  },
  hotels: {
    label: 'Hotels',
    icon: 'hotel',
    placeholder: 'e.g. 3 nights in South Goa for a couple. Quiet, near the beach, breakfast included, under ₹7,000/night.',
    understanding: 'I’ll weigh neighbourhood, room type, cancellation terms, breakfast and transfer friction — not just star rating.',
    chips: [ 'Quiet beach stay', 'Family room · breakfast', 'Near station · 1 night', 'Free cancellation' ],
    results: [
      [ 'Quiet beach-side stay', 'Best balance of beach access, calm surroundings and flexible cancellation.', '600 m beach', 'Breakfast', 'Free cancellation', '~₹6,650' ],
      [ 'Best-value boutique stay', 'Smaller property with a lower rate and strong location for the same beach area.', '900 m beach', 'Breakfast', 'Pay later', '~₹5,780' ],
      [ 'Most convenient full-service stay', 'More facilities and easier transfers, useful if the trip has mixed activity levels.', 'Pool + desk', 'Breakfast', 'Airport transfer', '~₹7,250' ],
    ],
  },
  activities: {
    label: 'Activities',
    icon: 'local_activity',
    placeholder: 'e.g. Two adults in Jaipur on Saturday. We like food and architecture, want something relaxed, and need to be back by 8 PM. Budget ₹3,000 each.',
    understanding: 'I’ll rank experiences by travel time, opening hours, pace, budget and how well they fit the rest of the day.',
    chips: [ 'Food + culture · 4 hours', 'Family-friendly · afternoon', 'Low walking · evening', 'Under ₹3,000 · relaxed' ],
    results: [
      [ 'Old City food + architecture walk', 'Best fit for a relaxed cultural afternoon without crossing the city twice.', '3.5 h', 'Pickup nearby', 'Free cancellation', '~₹1,850' ],
      [ 'Craft district studio visit', 'Hands-on local craft experience with a shorter duration and an indoor fallback.', '2 h', 'Small group', 'Indoor option', '~₹1,400' ],
      [ 'Sunset fort + dinner transfer', 'Later start, sunset timing and a direct transfer toward dinner instead of backtracking.', '4 h', 'Private transfer', 'Evening', '~₹2,950' ],
    ],
  },
  rail: {
    label: 'Rail',
    icon: 'train',
    placeholder: 'e.g. Delhi to Jaipur Tuesday morning. 2 people. Prefer chair car and arrive before lunch.',
    understanding: 'I’ll prioritise arrival time, class, station, journey duration and whether the train fits the day on either side.',
    chips: [ 'Arrive before noon', 'Chair car', 'Lowest change risk', 'Window seat preferred' ],
    results: [
      [ 'Fast morning intercity', 'Earliest useful arrival with a straightforward daytime journey.', '3h 45m', 'Chair car', 'Morning', '~₹1,120' ],
      [ 'Best-value daytime train', 'A little slower but lower fare and still reaches before lunch.', '4h 20m', 'Chair car', 'Day train', '~₹860' ],
      [ 'Flexible later option', 'Later departure if the morning plan changes, while keeping the journey same-day.', '4h 05m', 'Chair car', 'Flexible time', '~₹980' ],
    ],
  },
  car: {
    label: 'Transfer',
    icon: 'directions_car',
    placeholder: 'e.g. Jaipur airport to Amer Fort tomorrow at 10 AM. 3 people, luggage, prefer a clean AC car with an English-speaking driver.',
    understanding: 'I’ll compare vehicle type, pickup convenience, included distance or time, cancellation terms and the total fare.',
    chips: [ 'Airport pickup · AC', 'Driver for 8 hours', 'SUV · 4 travellers', 'One-way · lowest fare' ],
    results: [
      [ 'Private sedan with driver', 'Best fit for three travellers with luggage and a straightforward point-to-point transfer.', 'AC sedan', 'Meet & greet', 'Free cancellation', '~₹1,450' ],
      [ 'Driver for the day', 'Better value if you expect multiple stops instead of booking separate rides.', '8 hours', '80 km included', 'Local driver', '~₹2,850' ],
      [ 'Roomier SUV option', 'More luggage space and easier seating if the group wants extra comfort.', 'AC SUV', '6 seats', 'Airport pickup', '~₹2,250' ],
    ],
  },
  bus: {
    label: 'Bus',
    icon: 'directions_bus',
    placeholder: 'e.g. Bangalore to Mysore tomorrow evening. 1 person, AC seat, pickup near Indiranagar after 6 PM.',
    understanding: 'I’ll rank boarding-point convenience, seat type, arrival time, operator rules and total price.',
    chips: [ 'AC sleeper', 'Near my pickup', 'Arrive before midnight', 'Lowest fare' ],
    results: [
      [ 'Nearest pickup option', 'Closest boarding point with a comfortable AC service and a useful arrival time.', 'AC seater', '3h 25m', 'Nearby pickup', '~₹640' ],
      [ 'Best-value option', 'Slightly farther boarding point with the lowest total fare.', 'AC seater', '3h 40m', 'Value', '~₹520' ],
      [ 'Most comfortable option', 'Wider seat and fewer intermediate stops for a calmer evening ride.', 'Premium AC', '3h 20m', 'Fewer stops', '~₹790' ],
    ],
  },
};

function demoResponse( mode: TravelMode ): TravelResponse {
  const config = MODES[ mode ];
  return {
    source: 'demo',
    summary: MODE_RESULT_SUMMARIES[ mode ],
    results: config.results.map( ( item, index ) => ( {
      id: 'demo-' + mode + '-' + String( index + 1 ),
      sourceLabel: 'WECARE.DIGITAL',
      title: item[ 0 ],
      description: item[ 1 ],
      meta: [ item[ 2 ], item[ 3 ], item[ 4 ] ],
      price: item[ 5 ],
    } ) ),
  };
}

function safeHttpsUrl( value: unknown ): string {
  if ( typeof value !== 'string' || !value.trim() ) return '';
  try {
    const parsed = new URL( value );
    return parsed.protocol === 'https:' ? parsed.href : '';
  } catch {
    return '';
  }
}

function quoteIsFresh( value?: string ): boolean {
  if ( !value ) return false;
  const timestamp = Date.parse( value );
  return Number.isFinite( timestamp ) && timestamp > Date.now();
}

function hasRupeePrice( value: string ): boolean {
  return /₹|\bINR\b|\bRs\.?\b/i.test( value );
}

function rupeeAmount( value: string ): string {
  return value
    .replace( /₹/g, '' )
    .replace( /\bINR\b\s*/gi, '' )
    .replace( /\bRs\.?\b\s*/gi, '' )
    .trim();
}


function normaliseResponse( payload: Partial<TravelResponse> ): TravelResponse {
  const rows = Array.isArray( payload.results ) ? payload.results : [];
  const results = rows.slice( 0, 8 ).map( ( result, index ) => ( {
    id: String( result.id || 'result-' + String( index + 1 ) ),
    sourceLabel: String( result.sourceLabel || result.provider || 'WECARE.DIGITAL' ),
    title: String( result.title || 'Travel option' ),
    description: String( result.description || '' ),
    meta: Array.isArray( result.meta ) ? result.meta.slice( 0, 4 ).map( String ) : [],
    price: String( result.price || '' ),
    websiteUrl: safeHttpsUrl( result.websiteUrl ),
    whatsappUrl: safeHttpsUrl( result.whatsappUrl ),
    providerRef: typeof result.providerRef === 'string' ? result.providerRef.trim() : '',
    offerId: typeof result.offerId === 'string' ? result.offerId.trim() : '',
    quoteExpiresAt: typeof result.quoteExpiresAt === 'string' ? result.quoteExpiresAt.trim() : '',
    cancellationSummary: typeof result.cancellationSummary === 'string' ? result.cancellationSummary.trim() : '',
    availability: typeof result.availability === 'string' ? result.availability.trim() : '',
    checkoutReady: result.checkoutReady === true,
  } ) );
  if ( !results.length ) throw new Error( 'No usable provider results' );
  return {
    source: payload.source || 'api',
    summary: typeof payload.summary === 'string' ? payload.summary.trim() : undefined,
    results,
  };
}

async function searchTravel( mode: TravelMode, query: string, preferences: string[], signal: AbortSignal ): Promise<TravelResponse> {
  if ( typeof window !== 'undefined' ) {
    const travelWindow = window as typeof window & {
      ElsewhereTravelBridge?: {
        search: ( request: { mode: TravelMode; query: string; preferences: string[]; signal: AbortSignal } ) => Promise<TravelResponse>;
      };
    };
    if ( travelWindow.ElsewhereTravelBridge?.search ) {
      const response = await travelWindow.ElsewhereTravelBridge.search( { mode, query, preferences, signal } );
      return normaliseResponse( { ...response, source: 'mcp' } );
    }
  }

  const endpoint = process.env.NEXT_PUBLIC_ELSEWHERE_SEARCH_ENDPOINT || '';
  if ( endpoint ) {
    const response = await fetch( endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'same-origin',
      signal,
      body: JSON.stringify( { mode, query, preferences } ),
    } );
    if ( !response.ok ) throw new Error( 'Provider search failed (' + String( response.status ) + ')' );
    const payload = await response.json() as TravelResponse;
    return normaliseResponse( { ...payload, source: 'api' } );
  }

  await new Promise<void>( ( resolve, reject ) => {
    const timer = globalThis.setTimeout( resolve, 420 );
    signal.addEventListener( 'abort', () => {
      globalThis.clearTimeout( timer );
      reject( new DOMException( 'Aborted', 'AbortError' ) );
    }, { once: true } );
  } );
  return demoResponse( mode );
}

const ElsewhereTravelAssistant: React.FC = () => {
  const [ mode, setMode ] = useState<TravelMode>( 'activities' );
  const [ query, setQuery ] = useState( '' );
  const [ preferences, setPreferences ] = useState<string[]>( [] );
  const [ results, setResults ] = useState<TravelResult[]>( [] );
  const [ responseSummary, setResponseSummary ] = useState( '' );
  const [ responseSource, setResponseSource ] = useState<TravelResponse['source'] | null>( null );
  const [ status, setStatus ] = useState<'idle' | 'loading' | 'ready' | 'error'>( 'idle' );
  const [ continuationNote, setContinuationNote ] = useState( '' );
  const abortRef = useRef<AbortController | null>( null );
  const tabRefs = useRef<Record<TravelMode, HTMLButtonElement | null>>( {
    flights: null, hotels: null, activities: null, rail: null, car: null, bus: null,
  } );

  const config = MODES[ mode ];
  const canSubmit = query.trim().length > 0 || preferences.length > 0;

  useEffect( () => {
    if ( typeof window === 'undefined' || !window.matchMedia( '(max-width: 720px)' ).matches ) return;

    // SupportWidget changes <html lang> and <html dir> in place. Firefox/WebKit keep the
    // horizontal tab rail's old physical scroll position when that happens, so the active tab
    // stops being the mirror of its LTR position. Re-centre on both mode and direction changes.
    let frame = 0;
    const centreActiveTab = () => {
      window.cancelAnimationFrame( frame );
      frame = window.requestAnimationFrame( () => {
        // SCROLL THE RAIL, NOT THE PAGE. This was tab.scrollIntoView({ block: 'nearest',
        // inline: 'center' }), and scrollIntoView moves EVERY scrollable ancestor - the
        // document included. On a short viewport (a folded-landscape 653x280, a small phone
        // in landscape, or 200% zoom) the rail starts below the fold, so on load the page
        // itself jumped down and the hero's h1 ended up under the fixed header
        // (tools/browser/pageaudit.js, 2026-10-25). Moving the rail by the physical distance
        // between the two centres touches only the rail, and it is right in RTL too: under
        // the spec's negative-scrollLeft convention a larger value still moves the view right.
        const tab = tabRefs.current[ mode ];
        const rail = tab?.parentElement;
        if ( !tab || !rail ) return;
        const tabBox = tab.getBoundingClientRect();
        const railBox = rail.getBoundingClientRect();
        const delta = ( tabBox.left + tabBox.width / 2 ) - ( railBox.left + railBox.width / 2 );
        if ( Math.abs( delta ) < 1 ) return;
        // An ABSOLUTE scrollTo, not scrollBy. On this scroll-snapping rail a relative scroll is
        // snapped directionally - to the next snap point in the scroll's direction - and under
        // dir="rtl" Chromium sent a sub-pixel scrollBy to the far end of the rail, 49-69px off
        // centre at 320-360px (measured 2026-10-25). An absolute target snaps to the nearest
        // point, which is the active tab's own.
        rail.scrollTo( { left: rail.scrollLeft + delta, behavior: 'auto' } );
      } );
    };

    centreActiveTab();
    const observer = new MutationObserver( centreActiveTab );
    observer.observe( document.documentElement, {
      attributes: true,
      attributeFilter: [ 'dir', 'lang' ],
    } );

    return () => {
      observer.disconnect();
      window.cancelAnimationFrame( frame );
    };
  }, [ mode ] );

  const changeMode = useCallback( ( next: TravelMode ) => {
    abortRef.current?.abort();
    setMode( next );
    setQuery( '' );
    setPreferences( [] );
    setResults( [] );
    setResponseSummary( '' );
    setResponseSource( null );
    setStatus( 'idle' );
    setContinuationNote( '' );
  }, [] );

  const selectedPreferenceText = useMemo( () => preferences.join( ', ' ), [ preferences ] );

  const togglePreference = ( value: string ) => {
    setPreferences( current => (
      current.includes( value ) ? current.filter( item => item !== value ) : [ ...current, value ]
    ) );
    setContinuationNote( '' );
  };

  const submit = async () => {
    const typed = query.trim();
    if ( !typed && !preferences.length ) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus( 'loading' );
    setResults( [] );
    setResponseSummary( '' );
    setResponseSource( null );
    setContinuationNote( '' );

    try {
      const response = await searchTravel(
        mode,
        typed || 'Preferences: ' + selectedPreferenceText,
        [ ...preferences ],
        controller.signal,
      );
      setResults( response.results.slice( 0, 3 ) );
      setResponseSummary( response.summary || MODE_RESULT_SUMMARIES[ mode ] );
      setResponseSource( response.source || 'demo' );
      setStatus( 'ready' );
    } catch ( error ) {
      if ( error instanceof DOMException && error.name === 'AbortError' ) return;
      setStatus( 'error' );
    } finally {
      if ( abortRef.current === controller ) abortRef.current = null;
    }
  };

  const handleTabKey = ( event: React.KeyboardEvent<HTMLButtonElement>, index: number ) => {
    let nextIndex = index;
    if ( event.key === 'ArrowRight' ) nextIndex = ( index + 1 ) % MODE_ORDER.length;
    else if ( event.key === 'ArrowLeft' ) nextIndex = ( index - 1 + MODE_ORDER.length ) % MODE_ORDER.length;
    else if ( event.key === 'Home' ) nextIndex = 0;
    else if ( event.key === 'End' ) nextIndex = MODE_ORDER.length - 1;
    else return;

    event.preventDefault();
    const nextMode = MODE_ORDER[ nextIndex ];
    changeMode( nextMode );
    window.requestAnimationFrame( () => tabRefs.current[ nextMode ]?.focus() );
  };

  const appendVoice = ( transcript: string ) => {
    setQuery( current => current.trim() ? current.trim() + ' ' + transcript : transcript );
  };

  const checkoutAvailable = ( result: TravelResult ) => {
    if ( responseSource !== 'api' && responseSource !== 'mcp' ) return false;
    const providerIdentity = Boolean( result.providerRef || result.offerId );
    const providerFacts = Boolean( result.price && result.availability && result.cancellationSummary );
    if ( !result.checkoutReady || !providerIdentity || !providerFacts || !quoteIsFresh( result.quoteExpiresAt ) ) return false;
    return Boolean( safeHttpsUrl( result.websiteUrl || result.whatsappUrl ) );
  };

  const continueWith = ( result: TravelResult ) => {
    const safeTarget = safeHttpsUrl( result.websiteUrl || result.whatsappUrl );
    if ( !checkoutAvailable( result ) || !safeTarget ) {
      setContinuationNote( 'Provider confirmation required before checkout.' );
      return;
    }
    window.location.assign( safeTarget );
  };

  const userSummary = [
    query.trim(),
    preferences.length ? 'Preferences: ' + selectedPreferenceText : '',
  ].filter( Boolean ).join( ' · ' );

  return (
    <section className="eta-shell" aria-label="Elsewhere travel assistant">
      <h2 className="eta-sr-only">Plan travel with Elsewhere</h2>

      <nav className="eta-tabs" aria-label="Travel services" role="tablist">
        { MODE_ORDER.map( ( item, index ) => {
          const active = item === mode;
          const itemConfig = MODES[ item ];
          return (
            <button
              key={ item }
              id={ 'elsewhere-travel-tab-' + item }
              ref={ node => { tabRefs.current[ item ] = node; } }
              className={ active ? 'eta-tab active' : 'eta-tab' }
              type="button"
              role="tab"
              aria-selected={ active }
              aria-controls="elsewhere-travel-panel"
              tabIndex={ active ? 0 : -1 }
              onClick={ () => changeMode( item ) }
              onKeyDown={ event => handleTabKey( event, index ) }
            >
              <span className="eta-tab-icon" aria-hidden="true">{ itemConfig.icon }</span>
              <span>{ itemConfig.label }</span>
            </button>
          );
        } ) }
      </nav>

      <div
        id="elsewhere-travel-panel"
        className="eta-panel"
        role="tabpanel"
        aria-labelledby={ 'elsewhere-travel-tab-' + mode }
      >
        <div className="eta-response-view" aria-label="Travel responses" role="log" aria-live="polite" aria-relevant="additions text">
          <div className="eta-conversation">
          { status === 'idle' && (
            <p className="eta-line"><strong>Guide</strong> Tell me where you’re going, when, who is travelling and what matters most.</p>
          ) }

          { status !== 'idle' && userSummary && (
            <p className="eta-line"><strong>You</strong> { userSummary }</p>
          ) }

          { status === 'loading' && (
            <>
              <p className="eta-line"><strong>Guide</strong> { config.understanding }</p>
              <div className="eta-loading" role="status">
                <span className="eta-loading-line" aria-hidden="true" />
                <span>{ publicActionText( 'processing' ) }</span>
              </div>
            </>
          ) }

          { status === 'error' && (
            <p className="eta-line"><strong>Guide</strong> { publicActionText( 'blocked' ) } No booking or payment started.</p>
          ) }

          { status === 'ready' && (
            <>
              <p className="eta-line eta-response-intro"><strong>Guide</strong> { responseSummary || MODE_RESULT_SUMMARIES[ mode ] }</p>
              <div className="eta-results">
                { results.map( ( result, index ) => (
                  <article className={ 'eta-result eta-result-' + mode } key={ result.id }>
                    <div className="eta-result-main">
                      <div className="eta-result-top">
                        <span className="eta-rank">{ index + 1 }</span>
                        <h3>{ result.title }</h3>
                        { index === 0 && <span className="eta-best">Best match</span> }
                        { result.sourceLabel !== 'WECARE.DIGITAL' && <span className="eta-provider">{ result.sourceLabel }</span> }
                      </div>
                      <p className="eta-desc">{ result.description }</p>
                      <div className="eta-meta">
                        { result.meta.map( item => <span key={ item }>{ item }</span> ) }
                        { result.availability && <span>{ result.availability }</span> }
                        { result.cancellationSummary && <span>{ result.cancellationSummary }</span> }
                      </div>
                    </div>
                    <div className="eta-result-side">
                      <div className="eta-price" aria-label={ result.price }>
                        { hasRupeePrice( result.price ) && (
                          <span className="eta-price-icon eta-material" aria-hidden="true">{ symbol( 'currency_rupee' ) }</span>
                        ) }
                        <span>{ hasRupeePrice( result.price ) ? rupeeAmount( result.price ) : result.price }</span>
                      </div>
                      { responseSource === 'demo' && (
                        // Plain anchor, as in ClosingBand: <Link> is a component, so styled-jsx
                        // would not scope `.eta-action` onto the <a> it renders and the action
                        // would lose its styles.
                        // eslint-disable-next-line @next/next/no-html-link-for-pages
                        <a
                          className="eta-action eta-demo-checkout"
                          href="/checkout/"
                          aria-label={ `Checkout ${result.title}` }
                        >
                          <span className="eta-material eta-checkout-icon" aria-hidden="true">{ symbol( 'shopping_cart_checkout' ) }</span>
                          <span className="eta-action-label">Checkout</span>
                        </a>
                      ) }
                      { checkoutAvailable( result ) && (
                        <button
                          type="button"
                          className="eta-action"
                          aria-label={ `Checkout ${result.title} for ${result.price}` }
                          title={ `Checkout · ${result.price}` }
                          onClick={ () => continueWith( result ) }
                        >
                          <span className="eta-material eta-checkout-icon" aria-hidden="true">{ symbol( 'shopping_cart_checkout' ) }</span>
                          <span className="eta-action-label">Checkout</span>
                        </button>
                      ) }
                    </div>
                  </article>
                ) ) }
              </div>
            </>
          ) }
          </div>
        </div>

        <div className="eta-composer">
          <div className="eta-field">
            <textarea
              value={ query }
              onChange={ event => {
                setQuery( event.target.value );
                setContinuationNote( '' );
              } }
              onKeyDown={ event => {
                if ( ( event.metaKey || event.ctrlKey ) && event.key === 'Enter' && canSubmit && status !== 'loading' ) void submit();
              } }
              aria-label="Ask about travel"
              spellCheck={ false }
              data-gramm="false"
              data-gramm_editor="false"
              data-enable-grammarly="false"
              placeholder={ config.placeholder }
            />
          </div>
          <div className="eta-composer-foot">
            <span className="eta-hint">Describe your trip naturally</span>
            <div className="eta-tools">
              <span className="eta-keyhint">⌘ / Ctrl + Enter</span>
              { query.trim() && (
                <button className="eta-clear" type="button" aria-label="Clear message" title="Clear message" onClick={ () => setQuery( '' ) }>
                  <span className="eta-material" aria-hidden="true">{ symbol( 'close' ) }</span>
                </button>
              ) }
              <span className="eta-mic-slot"><VoiceSearchMic onTranscript={ appendVoice } ariaLabel="Search by voice" showUnsupportedState /></span>
              <button
                className="eta-send"
                type="button"
                aria-label="Send"
                title="Send"
                disabled={ !canSubmit || status === 'loading' }
                onClick={ () => { void submit(); } }
              >
                <span className="eta-material" aria-hidden="true">{ symbol( 'arrow_upward' ) }</span>
              </button>
            </div>
          </div>
        </div>

        <div className="eta-chips" aria-label={ config.label + ' preferences' }>
          { config.chips.map( chip => {
            const active = preferences.includes( chip );
            return (
              <button
                key={ chip }
                className={ active ? 'eta-chip active' : 'eta-chip' }
                type="button"
                aria-pressed={ active }
                onClick={ () => togglePreference( chip ) }
              >
                { active && <span aria-hidden="true">✓</span> }
                { chip }
              </button>
            );
          } ) }
        </div>

        { continuationNote && <p className="eta-continuation" role="status">{ continuationNote }</p> }
      </div>

      <style jsx>{`
        .eta-shell{
          width:min(940px,100%);margin:0 auto;min-width:0;overflow:hidden;
          border:1px solid var(--public-hairline);border-radius:24px;
          background:#f4f6f0;box-shadow:0 18px 54px rgba(26,58,42,.08);
          color:var(--public-text);font-family:var(--font-sans);
        }
        .eta-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
        .eta-tabs{
          display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;width:100%;
          padding:5px;background:var(--public-brand-lime);border-bottom:1px solid rgba(26,58,42,.14);
        }
        .eta-tab{
          position:relative;isolation:isolate;display:flex;align-items:center;justify-content:center;gap:9px;
          min-width:0;min-height:48px;padding:6px clamp(8px,1.2vw,14px);border:0;border-radius:13px;
          background:transparent;color:var(--public-heading);white-space:nowrap;
          font-family:var(--font-sans);font-size:16px;font-weight:700;line-height:1.2;letter-spacing:-.15px;
          cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;
          transition:background-color .12s ease;
        }
        .eta-tab::before{content:'';position:absolute;inset:6px 7px;border-radius:10px;background:transparent;transition:background .16s ease;z-index:-1}
        .eta-tab:active::before{background:rgba(239,249,207,.92)}
        .eta-tab.active::after{content:'';position:absolute;left:50%;bottom:4px;width:18px;height:2px;transform:translateX(-50%);border-radius:999px;background:#111512;opacity:.78}
        .eta-tab-icon{
          width:28px;height:28px;flex:0 0 28px;display:grid;place-items:center;border-radius:9px;
          background:rgba(17,21,18,.06);color:#111512;
          font-family:'Material Symbols Rounded';font-size:19px;font-weight:500;line-height:1;
          font-variation-settings:'FILL' 0,'wght' 500,'GRAD' 0,'opsz' 24;
        }
        .eta-tab.active .eta-tab-icon{background:rgba(17,21,18,.09)}
        .eta-panel{min-width:0;padding:28px 30px 26px}
        .eta-response-view{
          min-height:180px;max-height:460px;max-height:min(48dvh,460px);overflow-y:auto;overflow-x:hidden;
          padding-block:2px 8px;padding-inline:0 4px;overscroll-behavior-y:contain;scrollbar-gutter:stable;scrollbar-width:thin;
          -webkit-overflow-scrolling:touch;touch-action:pan-y;
        }
        .eta-conversation{display:flex;flex-direction:column;gap:16px;min-width:0}
        .eta-line{
          margin:0;color:var(--public-body);font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);overflow-wrap:anywhere;
        }
        .eta-line strong{display:inline-block;min-width:58px;color:var(--public-heading);font-size:15px;font-weight:600;line-height:1.3;letter-spacing:-.1px}
        .eta-results{display:flex;flex-direction:column;gap:10px;margin-top:2px}
        .eta-result{
          min-width:0;display:grid;grid-template-columns:minmax(0,1fr) minmax(230px,auto);gap:18px;align-items:start;
          padding:20px;border:1px solid var(--public-hairline);border-radius:14px;background:var(--public-bg);
          touch-action:pan-y;-webkit-tap-highlight-color:transparent;
        }
        .eta-result:first-child{border-color:#c9dc84}
        .eta-result-main{min-width:0}
        .eta-result-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
        .eta-result h3{
          margin:0;color:var(--public-heading);font-size:var(--public-card-size);font-weight:var(--public-card-weight);
          line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);overflow-wrap:anywhere;
        }
        .eta-rank{
          width:32px;height:32px;flex:0 0 32px;display:grid;place-items:center;border-radius:999px;
          background:var(--public-lime-tint);color:var(--public-brand-green);font-size:15px;font-weight:700;line-height:1;
        }
        .eta-provider,.eta-best{font-size:12px;font-weight:700;line-height:1.2;letter-spacing:.01em}
        .eta-provider{color:var(--public-muted)}
        .eta-best{color:var(--public-brand-green)}
        .eta-desc{
          margin:8px 0 0;color:var(--public-body);font-size:17px;font-weight:var(--public-body-weight);
          line-height:1.45;letter-spacing:var(--public-body-tracking);overflow-wrap:anywhere;
        }
        .eta-meta{display:flex;flex-wrap:wrap;gap:0;margin-top:10px;color:var(--public-muted);font-size:14px;font-weight:500;line-height:1.4}
        .eta-meta span{display:inline;padding:0;background:none;color:inherit;font:inherit}
        .eta-meta span:not(:last-child)::after{content:' · ';white-space:pre;color:#9aa196}
        .eta-result-side{display:flex;flex-direction:column;align-items:flex-end;gap:9px;text-align:end}
        .eta-price{
          display:inline-flex;align-items:center;justify-content:flex-end;gap:1px;color:var(--public-heading);
          font-size:17px;font-weight:700;line-height:1.25;letter-spacing:-.2px;white-space:nowrap;
        }
        .eta-price-icon{
          width:18px;height:18px;display:inline-grid;place-items:center;font-size:18px;font-weight:600;
          color:var(--public-brand-green);
        }
        .eta-checkout{display:flex;flex-direction:column;align-items:flex-end;gap:5px}
        .eta-checkout-label{
          color:var(--public-muted);font-size:13px;font-weight:600;line-height:1.3;letter-spacing:-.05px;
        }
        .eta-actions{
          display:flex;flex-direction:column;align-items:flex-end;gap:8px;width:auto;max-width:100%;margin-inline-start:auto;
        }
        .eta-action{
          display:inline-flex;align-items:center;gap:8px;width:max-content;max-width:100%;min-height:var(--tap-min);box-sizing:border-box;
          padding:8px 12px;border:2px solid transparent;border-radius:11px;background:var(--public-accent-amber);color:var(--public-brand-green);
          font-family:inherit;font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);
          line-height:1.4;letter-spacing:-.05px;cursor:pointer;white-space:normal;overflow-wrap:anywhere;text-align:start;
          text-decoration:none;touch-action:manipulation;-webkit-tap-highlight-color:transparent;
          transition:background-color .18s,border-color .18s,color .18s,transform .18s,box-shadow .18s;
        }
        .eta-checkout-icon{flex:0 0 auto}
        .eta-action-icon{
          width:17px;height:17px;flex:0 0 17px;fill:none;stroke:currentColor;stroke-width:1.8;
          stroke-linecap:round;stroke-linejoin:round;opacity:.86;
        }
        .eta-action-icon-whatsapp{opacity:.9}
        .eta-action:active{
          background:var(--public-accent-amber-tint);border-color:var(--public-accent-amber);
          transform:translateY(0) scale(.98);box-shadow:none;
        }
        .eta-live-note,.eta-continuation{margin:0;color:var(--public-muted);font-size:13px;font-weight:500;line-height:1.45}
        .eta-composer{
          margin-top:24px;padding:18px 18px 14px;border:0;border-radius:18px;background:#fff;
          cursor:text;touch-action:manipulation;-webkit-tap-highlight-color:transparent;
          transition:box-shadow .15s ease,background-color .15s ease;
        }
        .eta-composer:focus-within{box-shadow:0 6px 18px rgba(26,58,42,.09)}
        .eta-composer:active{box-shadow:0 4px 12px rgba(26,58,42,.08)}
        .eta-field{position:relative;box-shadow:none}
        .eta-composer:focus-within .eta-field{box-shadow:none}
        .eta-field textarea{
          width:100%;min-height:92px;padding:0 0 14px;border:0!important;border-radius:0!important;outline:0!important;resize:none;
          appearance:none;-webkit-appearance:none;background:transparent!important;box-shadow:none!important;
          -webkit-tap-highlight-color:transparent;touch-action:manipulation;
          color:var(--public-heading);font-family:var(--font-sans);font-size:var(--public-body-size);font-weight:var(--public-body-weight);
          line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
        }
        .eta-field textarea:hover,
        .eta-field textarea:focus,
        .eta-field textarea:focus-visible{
          border:0!important;border-color:transparent!important;border-radius:0!important;outline:0!important;box-shadow:none!important;
        }
        .eta-field textarea::placeholder{color:rgba(0,0,0,.42)}
        .eta-composer-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px}
        .eta-hint{color:var(--public-muted);font-size:15px;font-weight:400;line-height:1.35;letter-spacing:var(--public-body-tracking)}
        .eta-tools{display:flex;align-items:center;gap:2px;margin-inline-start:auto}
        .eta-keyhint{margin-inline-end:4px;color:#8a9288;font-size:12px}
        .eta-clear{
          display:grid;place-items:center;width:46px;height:46px;min-width:46px;min-height:46px;padding:0;border:0;border-radius:0;background:transparent;color:#7a8278;cursor:pointer;
          touch-action:manipulation;-webkit-tap-highlight-color:transparent;transition:background .14s ease,color .14s ease;
        }
        .eta-clear:active{background:var(--public-lime-tint);color:var(--public-brand-green)}
        .eta-material{font-family:'Material Symbols Rounded';font-size:21px;font-weight:500;line-height:1;font-variation-settings:'FILL' 0,'wght' 500,'GRAD' 0,'opsz' 24}
        .eta-mic-slot{position:relative;display:block;width:46px;height:46px;flex:0 0 46px}
        .eta-mic-slot :global(.voice-search-mic){
          border-radius:999px;touch-action:manipulation;-webkit-tap-highlight-color:transparent;
        }
        .eta-send{
          display:grid;place-items:center;width:44px;height:44px;min-width:44px;min-height:44px;padding:0;border:0;border-radius:50%;
          background:var(--public-brand-lime);color:var(--public-brand-green);cursor:pointer;box-shadow:0 4px 18px rgba(209,244,112,.14);
          touch-action:manipulation;-webkit-tap-highlight-color:transparent;transition:background .14s ease,box-shadow .14s ease;
        }
        .eta-send:not(:disabled):active{background:var(--lime-hover);box-shadow:inset 0 0 0 2px rgba(26,58,42,.10)}
        .eta-send:disabled{background:#e4e8dd;color:#8b9288;box-shadow:none;cursor:not-allowed}
        .eta-chips{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:16px}
        .eta-chip{
          flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;gap:6px;
          width:max-content;max-width:100%;min-height:var(--tap-min);box-sizing:border-box;
          padding:0 18px;border:2px solid var(--public-hairline);border-radius:999px;
          background:#fff;color:var(--public-brand-green);font-family:var(--font-sans);
          font-size:14px;font-weight:600;line-height:1.2;letter-spacing:-.125px;text-align:center;
          white-space:normal;overflow-wrap:anywhere;cursor:pointer;
          transition:background-color .2s,border-color .2s,transform .2s,box-shadow .2s;
          touch-action:manipulation;-webkit-tap-highlight-color:transparent;
        }
        .eta-chip:active{border-color:var(--public-brand-green);background:var(--public-lime-tint)}
        .eta-chip.active{border-color:var(--public-brand-green);background:var(--public-brand-lime);color:var(--public-brand-green);box-shadow:none}
        .eta-loading{display:flex;align-items:center;gap:10px;margin-top:6px;color:var(--public-muted);font-size:13px;font-weight:600;line-height:1.4}
        .eta-loading-line{position:relative;width:34px;height:3px;flex:0 0 34px;overflow:hidden;border-radius:999px;background:var(--public-lime-tint)}
        .eta-loading-line::after{content:'';position:absolute;inset:0 auto 0 0;width:45%;border-radius:inherit;background:var(--public-brand-lime);animation:eta-loading 1.15s ease-in-out infinite}
        @keyframes eta-loading{0%{transform:translateX(-120%)}50%{transform:translateX(70%)}100%{transform:translateX(240%)}}
        .eta-tab:focus-visible,.eta-clear:focus-visible,.eta-send:focus-visible,.eta-chip:focus-visible,.eta-action:focus-visible{
          outline:3px solid var(--public-brand-green);outline-offset:3px;
        }
        @media(hover:hover) and (pointer:fine){
          .eta-tab:hover::before{background:rgba(239,249,207,.78)}
          .eta-chip:hover{border-color:var(--public-brand-lime);background:var(--public-lime-tint);transform:translateY(-2px);box-shadow:var(--public-lift-shadow)}
          .eta-action:hover{
            background:#fff;border-color:var(--public-accent-amber);
            transform:translateY(-1px);
            box-shadow:0 5px 14px rgba(240,168,24,.18),0 2px 5px rgba(26,58,42,.08);
          }
          .eta-clear:hover{background:var(--public-lime-tint);color:var(--public-brand-green)}
          .eta-send:not(:disabled):hover{background:var(--lime-hover)}
        }
        @media(hover:none) and (pointer:coarse){
          .eta-composer:focus-within{background:rgba(209,244,112,.055);box-shadow:0 5px 14px rgba(26,58,42,.09)}
          .eta-mic-slot :global(.voice-search-mic:active){background:var(--public-lime-tint)}
          .eta-action:active,.eta-chip:active,.eta-send:not(:disabled):active,.eta-clear:active{
            filter:saturate(1.04);
          }
        }
        @media(max-width:720px){
          .eta-shell{border-radius:22px}
          .eta-tabs{
            display:flex;gap:4px;overflow-x:auto;overflow-y:hidden;scroll-snap-type:x proximity;
            -webkit-overflow-scrolling:touch;overscroll-behavior-inline:contain;scrollbar-width:none;
            touch-action:pan-x;padding:6px;
          }
          .eta-tabs::-webkit-scrollbar{display:none}
          .eta-tab{
            flex:0 0 auto;min-width:max-content;min-height:var(--tap-min);
            padding:8px 14px;gap:8px;scroll-snap-align:center;
            white-space:nowrap;overflow-wrap:normal;text-align:center;
            font-size:var(--public-mobile-cta-font-size);font-weight:var(--public-cta-font-weight);
            line-height:1.2;letter-spacing:-.1px;
          }
          .eta-tab-icon{width:28px;height:28px;flex-basis:28px;font-size:19px}
          .eta-panel{padding-block:20px;padding-inline:var(--public-mobile-page-gutter)}
          /* Phones use the page itself as the vertical scroller, like Home. A capped
             response pane made result cards disappear under the composer and forced a
             second scroll gesture inside the card. Let the conversation take its
             natural height; the desktop/tablet response rail stays capped above. */
          .eta-response-view{min-height:0;max-height:none;overflow:visible;overscroll-behavior-y:auto;scrollbar-gutter:auto;padding-inline-end:0}
          .eta-line{font-size:var(--public-body-size)}
          .eta-field textarea{font-size:var(--public-mobile-form-font-size)}
          .eta-composer-foot{flex-wrap:wrap}.eta-hint{flex:1 1 100%}.eta-tools{width:100%;justify-content:flex-end}
          .eta-result{grid-template-columns:1fr;padding:18px}.eta-result h3{font-size:var(--public-mobile-card-size)}.eta-desc{font-size:16px}.eta-result-side{align-items:flex-start;text-align:start}.eta-checkout{align-items:flex-start}.eta-actions{align-items:flex-start;margin-inline-start:0}
        }
        @media(max-width:380px){
          .eta-tab{padding-inline:12px}
          .eta-keyhint{display:none}
          .eta-panel{padding-inline:var(--public-mobile-page-gutter)}
          .eta-result{padding-inline:16px}
          .eta-actions{gap:6px}
        }
        @media(prefers-reduced-motion:reduce){
          .eta-tab,.eta-tab::before,.eta-result,.eta-chip,.eta-action,.eta-clear,.eta-send,.eta-composer{transition:none}
          .eta-action:hover{transform:none;box-shadow:none}
          .eta-loading-line::after{width:100%;transform:none;animation:none}
        }
        @media(prefers-reduced-motion:reduce) and (hover:none) and (pointer:coarse){
          .eta-composer:focus-within{box-shadow:none}
        }
        @media(horizontal-viewport-segments:2){
          .eta-shell{max-width:calc(env(viewport-segment-width 0 0) - (2 * var(--public-mobile-page-gutter)));margin-inline-start:max(var(--public-mobile-page-gutter),env(viewport-segment-left 0 0));margin-inline-end:auto}
          :global([dir='rtl']) .eta-shell{margin-inline-start:auto;margin-inline-end:max(var(--public-mobile-page-gutter),env(viewport-segment-left 1 0))}
        }
      `}</style>
    </section>
  );
};

export default ElsewhereTravelAssistant;
