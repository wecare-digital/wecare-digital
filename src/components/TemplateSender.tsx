/**
 * Template Sender Component
 * Send template messages (including carousel) to contacts
 * Used when 24-hour window is closed or for marketing campaigns
 */

import React, { useState, useEffect } from 'react';
import * as api from '../api/client';
import { WHATSAPP_PHONES } from '../config/constants';
import { useConfirm } from '../contexts/ConfirmContext';
import Select, { type SelectOption } from './ui/Select';
import DateField from './ui/DateField';
import TimeField from './ui/TimeField';

/* The template category filter's rows, hoisted. 'all' is the filter's own sentinel and was
   its first <option>, so it stays first and keeps its value and its text. */
const CATEGORY_FILTER_OPTIONS: SelectOption[] = [
  { value: 'all', label: 'All Categories' },
  { value: 'UTILITY', label: 'Utility' },
  { value: 'MARKETING', label: 'Marketing' },
  { value: 'AUTHENTICATION', label: 'Authentication' },
];

/* LAYOUT ONLY - what `.category-filter` carried inside the flex `.search-filters` row. */
const CATEGORY_FILTER_STYLE: React.CSSProperties = { flex: '0 0 180px' };

interface TemplateSenderProps {
  contactId?: string;
  contactName: string;
  phoneNumberId: string;
  recipientBsuid?: string;
  recipientPhone?: string;    // Send to phone directly — auto-creates contact if needed
  enableManualRecipient?: boolean;  // Show a phone-number input (new / unsaved contact)
  onClose: () => void;
  onSent: () => void;
  onError: ( msg: string ) => void;
}

interface TemplateVariable {
  index: number;
  value: string;
  placeholder: string;
}

const TemplateSender: React.FC<TemplateSenderProps> = ( {
  contactId,
  contactName,
  phoneNumberId,
  recipientBsuid,
  recipientPhone,
  enableManualRecipient,
  onClose,
  onSent,
  onError,
} ) => {
  const confirm = useConfirm();
  const [ loading, setLoading ] = useState( true );
  const [ sending, setSending ] = useState( false );
  const [ manualPhone, setManualPhone ] = useState( '' );
  // True when we have no contact/phone context and must collect a number.
  const manualMode = !!enableManualRecipient && !contactId && !recipientPhone;
  // Bulk CSV broadcast (only offered in manual / new-template mode).
  const [ bulkMode, setBulkMode ] = useState( false );
  const [ bulkRecipients, setBulkRecipients ] = useState<{ phone: string; params: string[] }[]>( [] );
  const [ bulkFileName, setBulkFileName ] = useState( '' );
  const [ bulkHasParams, setBulkHasParams ] = useState( false );
  const [ bulkProgress, setBulkProgress ] = useState<{ sent: number; failed: number; total: number } | null>( null );
  const [ bulkFailed, setBulkFailed ] = useState<string[]>( [] );
  const [ bulkErrors, setBulkErrors ] = useState<Record<string, string>>( {} );
  const [ templates, setTemplates ] = useState<api.WhatsAppTemplate[]>( [] );
  const [ selectedTemplate, setSelectedTemplate ] = useState<api.WhatsAppTemplate | null>( null );
  const [ variables, setVariables ] = useState<TemplateVariable[]>( [] );
  const [ cardVariables, setCardVariables ] = useState<TemplateVariable[][]>( [] );
  const [ searchQuery, setSearchQuery ] = useState( '' );
  const [ filterCategory, setFilterCategory ] = useState<string>( 'all' );
  const [ scheduleMode, setScheduleMode ] = useState( false );
  const [ scheduledDate, setScheduledDate ] = useState( '' );
  const [ scheduledTime, setScheduledTime ] = useState( '' );
  // Media header (IMAGE/VIDEO/DOCUMENT) support — Meta requires a header
  // parameter at send time for media-header templates (e.g. wecare_pdf).
  const [ headerType, setHeaderType ] = useState<'image' | 'video' | 'document' | 'location' | null>( null );
  const [ headerMedia, setHeaderMedia ] = useState<string>( '' );   // S3 key or https link
  const [ headerFilename, setHeaderFilename ] = useState<string>( '' );
  const [ headerUploading, setHeaderUploading ] = useState( false );
  // Location header inputs (when the template header format is LOCATION)
  const [ locLat, setLocLat ] = useState( '' );
  const [ locLng, setLocLng ] = useState( '' );
  const [ locName, setLocName ] = useState( '' );
  const [ locAddress, setLocAddress ] = useState( '' );
  // Flow button: templates with a FLOW button need a button component (sub_type
  // 'flow') at send time, else Meta rejects (error 131008/131009). We detect the
  // flow button's index from the template definition and pass it through.
  const [ flowButtonIndex, setFlowButtonIndex ] = useState<number | null>( null );
  // Media library (reusable wa-tpl/ files) — search, pick, permanently delete.
  const [ showLibrary, setShowLibrary ] = useState( false );
  const [ libraryItems, setLibraryItems ] = useState<any[]>( [] );
  const [ libraryLoading, setLibraryLoading ] = useState( false );
  const [ librarySearch, setLibrarySearch ] = useState( '' );
  const [ libraryDeleting, setLibraryDeleting ] = useState<string | null>( null );
  // Address autocomplete (Google Places via backend proxy)
  const [ placeQuery, setPlaceQuery ] = useState( '' );
  const [ placePredictions, setPlacePredictions ] = useState<{ description: string; placeId: string }[]>( [] );
  const [ placeSearching, setPlaceSearching ] = useState( false );
  const [ placeSession, setPlaceSession ] = useState( '' );

  const loadTemplates = async () => {
    setLoading( true );
    try
    {
      // Resolve the WABA for the selected phone so we fetch THAT WABA's templates
      // (templates are per-WABA; supports both WABA 1 and WABA 2).
      const phone = Object.values( WHATSAPP_PHONES ).find(
        ( p: any ) => p.id === phoneNumberId || p.metaPhoneId === phoneNumberId || p.wabaId === phoneNumberId
      ) as any;
      const wabaId = phone?.wabaId;
      const data = await api.listTemplates( wabaId );
      // Only show approved templates
      setTemplates( data.filter( t => t.status === 'APPROVED' ) );
    } catch ( err )
    {
      console.error( 'Failed to load templates:', err );
      onError( 'Failed to load templates' );
    } finally
    {
      setLoading( false );
    }
  };

  // Load templates on mount / when the target phone (WABA) changes
  useEffect( () => {
    loadTemplates();
  }, [ phoneNumberId ] );

  // Extract variables from template when selected
  useEffect( () => {
    if ( !selectedTemplate )
    {
      setVariables( [] );
      setCardVariables( [] );
      setHeaderType( null );
      setHeaderMedia( '' );
      setHeaderFilename( '' );
      setFlowButtonIndex( null );
      return;
    }

    // Detect a media header (IMAGE / VIDEO / DOCUMENT) or LOCATION header.
    const headerComp = selectedTemplate.components?.find( c => c.type === 'HEADER' );
    const fmt = ( headerComp?.format || '' ).toUpperCase();
    if ( fmt === 'IMAGE' || fmt === 'VIDEO' || fmt === 'DOCUMENT' )
    {
      setHeaderType( fmt.toLowerCase() as 'image' | 'video' | 'document' );
    } else if ( fmt === 'LOCATION' )
    {
      setHeaderType( 'location' );
    } else
    {
      setHeaderType( null );
    }

    // Detect a FLOW button — its component must be sent at send time.
    const buttonsComp = selectedTemplate.components?.find( c => c.type === 'BUTTONS' );
    const flowIdx = ( buttonsComp as any )?.buttons?.findIndex(
      ( b: any ) => ( b?.type || '' ).toUpperCase() === 'FLOW'
    );
    setFlowButtonIndex( typeof flowIdx === 'number' && flowIdx >= 0 ? flowIdx : null );

    setHeaderMedia( '' );
    setHeaderFilename( '' );
    setLocLat( '' );
    setLocLng( '' );
    setLocName( '' );
    setLocAddress( '' );

    const vars: TemplateVariable[] = [];
    const cardVars: TemplateVariable[][] = [];

    // Check if it's a carousel template
    const carouselComponent = selectedTemplate.components?.find( c => c.type === 'CAROUSEL' );

    if ( carouselComponent )
    {
      // Extract body variables
      const bodyComponent = selectedTemplate.components?.find( c => c.type === 'BODY' );
      if ( bodyComponent?.text )
      {
        const matches = bodyComponent.text.match( /\{\{(\d+)\}\}/g ) || [];
        matches.forEach( ( match, idx ) => {
          const num = parseInt( match.replace( /[{}]/g, '' ) );
          vars.push( {
            index: num,
            value: '',
            placeholder: `Variable ${num}`,
          } );
        } );
      }

      // Extract card variables (simplified - each card may have body variables)
      const cards = ( carouselComponent as any ).cards || [];
      cards.forEach( ( card: any, cardIdx: number ) => {
        const cardBodyVars: TemplateVariable[] = [];
        const cardBody = card.components?.find( ( c: any ) => c.type === 'BODY' );
        if ( cardBody?.text )
        {
          const matches = cardBody.text.match( /\{\{(\d+)\}\}/g ) || [];
          matches.forEach( ( match: string ) => {
            const num = parseInt( match.replace( /[{}]/g, '' ) );
            cardBodyVars.push( {
              index: num,
              value: '',
              placeholder: `Card ${cardIdx + 1} - Variable ${num}`,
            } );
          } );
        }
        cardVars.push( cardBodyVars );
      } );
    } else
    {
      // Standard template - extract all variables
      selectedTemplate.components?.forEach( comp => {
        if ( comp.text )
        {
          const matches = comp.text.match( /\{\{(\d+)\}\}/g ) || [];
          matches.forEach( match => {
            const num = parseInt( match.replace( /[{}]/g, '' ) );
            if ( !vars.find( v => v.index === num ) )
            {
              vars.push( {
                index: num,
                value: '',
                placeholder: `Variable ${num}`,
              } );
            }
          } );
        }
      } );
    }

    // Sort by index
    vars.sort( ( a, b ) => a.index - b.index );

    // Pre-fill first variable with contact name if available
    if ( vars.length > 0 && contactName )
    {
      vars[ 0 ].value = contactName;
    }

    setVariables( vars );
    setCardVariables( cardVars );
  }, [ selectedTemplate, contactName ] );

  const updateVariable = ( index: number, value: string ) => {
    setVariables( vars => vars.map( ( v, i ) => i === index ? { ...v, value } : v ) );
  };

  const updateCardVariable = ( cardIdx: number, varIdx: number, value: string ) => {
    setCardVariables( cards => cards.map( ( card, ci ) =>
      ci === cardIdx
        ? card.map( ( v, vi ) => vi === varIdx ? { ...v, value } : v )
        : card
    ) );
  };

  // Upload a header media file (image/video/document) to the reusable public
  // wa-tpl/ folder → returns a stable public CDN URL. WhatsApp fetches the URL
  // directly so every attachment type (PDF/DOCX/XLSX/PPTX/TXT/PNG/JPEG/MP4/3GP)
  // sends with the correct content type, and the URL can be reused across sends.
  const handleHeaderUpload = async ( e: React.ChangeEvent<HTMLInputElement> ) => {
    const file = e.target.files?.[ 0 ];
    if ( !file ) return;
    setHeaderUploading( true );
    try
    {
      const mime = file.type || 'application/octet-stream';
      const url = await api.uploadReusableHeaderMedia( file, mime, file.name );
      if ( url )
      {
        setHeaderMedia( url );
        setHeaderFilename( file.name );
      } else
      {
        onError( 'Header upload failed' );
      }
    } catch ( err: any )
    {
      onError( err?.message || 'Header upload failed' );
    } finally
    {
      setHeaderUploading( false );
    }
  };

  const headerAccept = headerType === 'image'
    ? 'image/*'
    : headerType === 'video'
      ? 'video/*'
      : '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,application/pdf';

  // ── Media library (reusable wa-tpl/ files) ──
  const loadLibrary = async ( search?: string ) => {
    if ( !headerType || headerType === 'location' ) return;
    setLibraryLoading( true );
    try
    {
      const items = await api.listSendMedia( {
        category: headerType as 'document' | 'image' | 'video',
        search: search ?? librarySearch,
      } );
      setLibraryItems( items );
    } catch ( err: any )
    {
      onError( err?.message || 'Failed to load media library' );
    } finally
    {
      setLibraryLoading( false );
    }
  };

  const toggleLibrary = () => {
    const next = !showLibrary;
    setShowLibrary( next );
    if ( next ) loadLibrary( '' );
  };

  const pickFromLibrary = ( item: any ) => {
    setHeaderMedia( item.mediaUrl );           // public URL → sent as a reusable link
    setHeaderFilename( item.filename || '' );
    setShowLibrary( false );
  };

  const deleteLibraryItem = async ( item: any ) => {
    // The `typeof window !== 'undefined'` guard went with the call: it existed because
    // window.confirm is undefined during a build-time render, and a context hook has no
    // such hazard.
    const ok = await confirm( {
      title: `Permanently delete "${item.filename}"?`,
      message: (
        <>
          <p style={ { margin: '0 0 8px' } }>This removes the file from storage for everyone.</p>
          <p style={ { margin: 0 } }>This cannot be undone.</p>
        </>
      ),
      confirmText: 'Delete',
      danger: true,
    } );
    if ( !ok ) return;
    setLibraryDeleting( item.s3Key );
    try
    {
      const success = await api.deleteSendMedia( item.s3Key );
      if ( success )
      {
        setLibraryItems( prev => prev.filter( i => i.s3Key !== item.s3Key ) );
        // If the deleted file was selected, clear it.
        if ( headerMedia === item.mediaUrl ) { setHeaderMedia( '' ); setHeaderFilename( '' ); }
      } else
      {
        onError( 'Failed to delete media' );
      }
    } catch ( err: any )
    {
      onError( err?.message || 'Failed to delete media' );
    } finally
    {
      setLibraryDeleting( null );
    }
  };

  const formatSize = ( bytes: number ) => bytes >= 1024 * 1024
    ? `${( bytes / ( 1024 * 1024 ) ).toFixed( 1 )}MB`
    : `${Math.max( 1, Math.round( bytes / 1024 ) )}KB`;

  // ── CSV helpers (bulk) ──
  const downloadCsv = ( filename: string, rows: ( string | number )[][] ) => {
    const csv = rows.map( r => r.map( c => {
      const s = String( c ?? '' );
      return /[",\n]/.test( s ) ? `"${s.replace( /"/g, '""' )}"` : s;
    } ).join( ',' ) ).join( '\r\n' );
    const blob = new Blob( [ '\uFEFF' + csv ], { type: 'text/csv;charset=utf-8;' } ); // BOM → Excel-friendly
    const url = URL.createObjectURL( blob );
    const a = document.createElement( 'a' );
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL( url );
  };

  // Sample CSV matching the selected template's variable count, ready to fill in.
  const downloadSampleCsv = () => {
    const n = variables.length;
    const header = [ 'phone', ...Array.from( { length: n }, ( _, i ) => `var${i + 1}` ) ];
    const ex = ( p: string ) => [ p, ...Array.from( { length: n }, ( _, i ) => `value${i + 1}` ) ];
    downloadCsv(
      `recipients-sample${selectedTemplate ? '-' + selectedTemplate.name : ''}.csv`,
      [ header, ex( '+919876543210' ), ex( '+918100640044' ) ]
    );
  };

  // Per-recipient results after a bulk run (phone + status + failure reason).
  const downloadResultsCsv = () => {
    if ( bulkRecipients.length === 0 ) return;
    const failedSet = new Set( bulkFailed );
    downloadCsv(
      `bulk-send-results-${new Date().toISOString().slice( 0, 19 ).replace( /[:T]/g, '-' )}.csv`,
      [
        [ 'phone', 'status', 'reason' ],
        ...bulkRecipients.map( r => {
          const isFailed = failedSet.has( r.phone );
          return [ r.phone, isFailed ? 'failed' : 'sent', isFailed ? ( bulkErrors[ r.phone ] || '' ) : '' ];
        } ),
      ]
    );
  };


  // Debounced Google Places autocomplete for location-header templates.
  useEffect( () => {
    if ( headerType !== 'location' ) return;
    if ( !placeQuery || placeQuery.trim().length < 3 ) { setPlacePredictions( [] ); return; }
    let active = true;
    setPlaceSearching( true );
    // One session token per search session bundles autocomplete + details billing.
    let token = placeSession;
    if ( !token )
    {
      token = ( typeof crypto !== 'undefined' && crypto.randomUUID ) ? crypto.randomUUID() : String( Date.now() ) + Math.random().toString( 36 ).slice( 2 );
      setPlaceSession( token );
    }
    const t = setTimeout( async () => {
      try
      {
        const preds = await api.placesAutocomplete( placeQuery, token );
        if ( active ) setPlacePredictions( preds );
      } catch { /* ignore */ }
      finally { if ( active ) setPlaceSearching( false ); }
    }, 350 );
    return () => { active = false; clearTimeout( t ); };
  }, [ placeQuery, headerType ] );

  const selectPlace = async ( placeId: string, description: string ) => {
    setPlacePredictions( [] );
    setPlaceQuery( description );
    try
    {
      const d = await api.placeDetails( placeId, placeSession );
      if ( d )
      {
        setLocLat( String( d.latitude ?? '' ) );
        setLocLng( String( d.longitude ?? '' ) );
        setLocName( d.name || '' );
        setLocAddress( d.address || '' );
      }
    } catch ( err: any )
    {
      onError( err?.message || 'Failed to resolve place' );
    } finally
    {
      setPlaceSession( '' );  // close the billing session; next search starts a new one
    }
  };

  // Parse a CSV/TXT of recipients. Column 1 = phone (country code + number).
  // Any extra columns map to template variables {{1}},{{2}}… for that row.
  // Strips a header row, non-digits in the phone, and duplicate numbers.
  const parseRecipientsCsv = ( text: string ): { phone: string; params: string[] }[] => {
    const out: { phone: string; params: string[] }[] = [];
    const seen = new Set<string>();
    text.split( /\r?\n/ ).forEach( ( line ) => {
      const cells = line.split( ',' ).map( c => c.trim() );
      const digits = ( cells[ 0 ] || '' ).replace( /[^\d]/g, '' );
      if ( digits.length < 10 ) return;        // skips header row / junk
      if ( seen.has( digits ) ) return;
      seen.add( digits );
      out.push( { phone: digits, params: cells.slice( 1 ).filter( c => c !== '' ) } );
    } );
    return out;
  };

  const handleBulkCsv = async ( e: React.ChangeEvent<HTMLInputElement> ) => {
    const file = e.target.files?.[ 0 ];
    if ( !file ) return;
    try
    {
      const text = await file.text();
      const recipients = parseRecipientsCsv( text );
      if ( recipients.length === 0 )
      {
        onError( 'No valid numbers found. Use one number per line or a CSV with numbers in the first column.' );
        return;
      }
      setBulkRecipients( recipients );
      setBulkHasParams( recipients.some( r => r.params.length > 0 ) );
      setBulkFailed( [] );
      setBulkFileName( file.name );
    } catch ( err: any )
    {
      onError( err?.message || 'Failed to read CSV file' );
    }
  };

  const sendBulk = async () => {
    if ( !selectedTemplate ) return;
    setSending( true );
    setBulkProgress( { sent: 0, failed: 0, total: bulkRecipients.length } );
    setBulkFailed( [] );
    setBulkErrors( {} );
    let sent = 0;
    let failed = 0;
    const failedNums: string[] = [];
    const rowErrors: Record<string, string> = {};
    for ( let i = 0; i < bulkRecipients.length; i++ )
    {
      const row = bulkRecipients[ i ];
      // Per-row variables from the CSV when present; otherwise the shared values.
      const rowParams = ( bulkHasParams && row.params.length > 0 ) ? row.params : variables.map( v => v.value );
      try
      {
        const result = await api.sendWhatsAppTemplateMessage( {
          recipientPhone: row.phone,
          templateName: selectedTemplate.name,
          language: selectedTemplate.language,
          templateParams: rowParams,
          phoneNumberId,
          headerMedia: headerType ? headerMedia : undefined,
          headerType: headerType || undefined,
          headerFilename: headerType === 'document' ? ( headerFilename || undefined ) : undefined,
          headerLocation: headerType === 'location' ? { latitude: locLat.trim(), longitude: locLng.trim(), name: locName.trim() || undefined, address: locAddress.trim() || undefined } : undefined,
          flowButton: flowButtonIndex !== null ? { index: flowButtonIndex } : undefined,
          content: getPreviewText() || undefined,
        } );
        if ( result ) sent++; else
        {
          failed++; failedNums.push( row.phone );
          // Capture this row's specific Meta reason (sends are sequential).
          rowErrors[ row.phone ] = api.getConnectionStatus().lastError || 'Send failed';
        }
      } catch ( err: any )
      {
        failed++;
        failedNums.push( row.phone );
        rowErrors[ row.phone ] = err?.message || 'Send failed';
      }
      setBulkProgress( { sent, failed, total: bulkRecipients.length } );
      // Gentle pacing to avoid Meta rate limits on large lists.
      if ( ( i + 1 ) % 10 === 0 ) await new Promise( r => setTimeout( r, 250 ) );
    }
    setBulkFailed( failedNums );
    setBulkErrors( rowErrors );
    setSending( false );
    if ( sent > 0 ) onSent();
    onError( `Bulk send complete: ${sent} sent, ${failed} failed (of ${bulkRecipients.length}).` );
    if ( failed === 0 ) onClose();
  };

  const handleSend = async () => {
    if ( !selectedTemplate )
    {
      onError( 'Please select a template' );
      return;
    }

    // Validate required variables
    const emptyVars = variables.filter( v => !v.value.trim() );
    if ( emptyVars.length > 0 )
    {
      onError( `Please fill in all variables (${emptyVars.length} empty)` );
      return;
    }

    // Media-header templates require a header file/link at send time.
    if ( headerType && headerType !== 'location' && !headerMedia )
    {
      onError( `This template has a ${headerType} header — upload a ${headerType} or paste a link first.` );
      return;
    }
    // Location-header templates require coordinates at send time.
    if ( headerType === 'location' && ( !locLat.trim() || !locLng.trim() ) )
    {
      onError( 'This template has a location header — enter latitude and longitude.' );
      return;
    }

    // Bulk CSV broadcast path.
    if ( manualMode && bulkMode )
    {
      if ( bulkRecipients.length === 0 )
      {
        onError( 'Upload a CSV with at least one valid number first.' );
        return;
      }
      await sendBulk();
      return;
    }

    // Resolve the recipient. In manual mode validate the typed number.
    let manualDigits = '';
    if ( manualMode )
    {
      manualDigits = manualPhone.replace( /[^\d]/g, '' );
      if ( manualDigits.length < 10 )
      {
        onError( 'Enter a valid recipient number with country code (e.g. 919876543210).' );
        return;
      }
    }
    const effectiveRecipientPhone = manualMode ? manualDigits : recipientPhone;

    setSending( true );
    try
    {
      // Check if scheduling
      if ( scheduleMode && scheduledDate && scheduledTime )
      {
        if ( manualMode )
        {
          onError( 'Scheduling requires a saved contact. Send now, or open the contact first.' );
          return;
        }
        const scheduledAt = new Date( `${scheduledDate}T${scheduledTime}` ).toISOString();
        const result = await api.scheduleTemplateMessage( {
          contactId: contactId || '',
          templateName: selectedTemplate.name,
          templateParams: variables.map( v => v.value ),
          phoneNumberId,
          scheduledAt,
        } );

        if ( result )
        {
          onSent();
          onClose();
        } else
        {
          onError( 'Failed to schedule message' );
        }
      } else
      {
        // Send immediately
        const isCarousel = selectedTemplate.components?.some( c => c.type === 'CAROUSEL' );

        let result;
        if ( isCarousel )
        {
          result = await api.sendCarouselTemplateMessage( {
            contactId: contactId || '',
            templateName: selectedTemplate.name,
            language: selectedTemplate.language,
            phoneNumberId,
            recipientBsuid,
            bodyParams: variables.map( v => v.value ),
            cardParams: cardVariables.map( card => card.map( v => v.value ) ),
          } );
        } else
        {
          result = await api.sendWhatsAppTemplateMessage( {
            contactId: contactId || '',
            recipientPhone: effectiveRecipientPhone,
            templateName: selectedTemplate.name,
            language: selectedTemplate.language,
            templateParams: variables.map( v => v.value ),
            phoneNumberId,
            recipientBsuid,
            headerMedia: headerType ? headerMedia : undefined,
            headerType: headerType || undefined,
            headerFilename: headerType === 'document' ? ( headerFilename || undefined ) : undefined,
            headerLocation: headerType === 'location' ? { latitude: locLat.trim(), longitude: locLng.trim(), name: locName.trim() || undefined, address: locAddress.trim() || undefined } : undefined,
            flowButton: flowButtonIndex !== null ? { index: flowButtonIndex } : undefined,
            content: getPreviewText() || undefined,
          } );
        }

        if ( result )
        {
          onSent();
          onClose();
        } else
        {
          const detail = api.getConnectionStatus().lastError;
          onError( detail ? `Failed to send: ${detail}` : 'Failed to send template message' );
        }
      }
    } catch ( err: any )
    {
      onError( err.message || 'Send failed' );
    } finally
    {
      setSending( false );
    }
  };

  // Filter templates
  const filteredTemplates = templates.filter( t => {
    const matchesSearch = t.name.toLowerCase().includes( searchQuery.toLowerCase() );
    const matchesCategory = filterCategory === 'all' || t.category === filterCategory;
    return matchesSearch && matchesCategory;
  } );

  // Get preview text with variables filled in
  const getPreviewText = () => {
    if ( !selectedTemplate ) return '';

    let preview = '';
    selectedTemplate.components?.forEach( comp => {
      if ( comp.type === 'HEADER' && comp.text )
      {
        preview += `*${comp.text}*\n\n`;
      } else if ( comp.type === 'BODY' && comp.text )
      {
        let bodyText = comp.text;
        variables.forEach( v => {
          bodyText = bodyText.replace( `{{${v.index}}}`, v.value || `[${v.placeholder}]` );
        } );
        preview += bodyText + '\n';
      } else if ( comp.type === 'FOOTER' && comp.text )
      {
        preview += `\n_${comp.text}_`;
      }
    } );
    return preview;
  };

  // Check if template is carousel
  const isCarouselTemplate = selectedTemplate?.components?.some( c => c.type === 'CAROUSEL' );

  return (
    <div className="template-sender">
      <div className="sender-header">
        <h3>Send Template Message</h3>
        <button className="close-btn" onClick={ onClose }>×</button>
      </div>

      <div className="sender-body">
        {/* Manual recipient entry — single new number OR bulk CSV broadcast */ }
        { manualMode && (
          <div className="manual-recipient">
            <div className="recip-mode-toggle">
              <button
                type="button"
                className={ `mode-pill ${!bulkMode ? 'active' : ''}` }
                onClick={ () => setBulkMode( false ) }
              >Single number</button>
              <button
                type="button"
                className={ `mode-pill ${bulkMode ? 'active' : ''}` }
                onClick={ () => setBulkMode( true ) }
              >Bulk (CSV)</button>
            </div>

            { !bulkMode ? (
              <>
                <label>Send to (new number)</label>
                <input
                  type="tel"
                  inputMode="numeric"
                  className="manual-phone-input"
                  placeholder="Country code + number e.g. 919876543210"
                  value={ manualPhone }
                  onChange={ ( e ) => setManualPhone( e.target.value ) }
                />
                <span className="manual-hint">No saved contact needed — a contact is created automatically. Template messages can open a new conversation outside the 24-hour window.</span>
              </>
            ) : (
              <>
                <label>Upload recipients (CSV)</label>
                <label className="csv-upload-btn">
                  { bulkFileName ? `Replace CSV (${bulkFileName})` : 'Choose CSV / TXT file' }
                  <input
                    type="file"
                    accept=".csv,.txt,text/csv,text/plain"
                    onChange={ handleBulkCsv }
                    style={ { display: 'none' } }
                  />
                </label>
                <button type="button" className="btn btn-secondary btn-sm" style={ { marginLeft: 8 } } onClick={ downloadSampleCsv }>
                  ⬇ Download sample CSV
                </button>
                { bulkRecipients.length > 0 && (
                  <div className="bulk-count">
                    ✓ { bulkRecipients.length } recipient{ bulkRecipients.length > 1 ? 's' : '' } loaded
                    { bulkHasParams && <span className="bulk-pers"> · per-row variables detected</span> }
                    <button className="clear-header" onClick={ () => { setBulkRecipients( [] ); setBulkFileName( '' ); setBulkProgress( null ); setBulkFailed( [] ); setBulkHasParams( false ); } }>×</button>
                  </div>
                ) }
                { bulkProgress && (
                  <div className="bulk-progress">Sending… { bulkProgress.sent + bulkProgress.failed } / { bulkProgress.total } ({ bulkProgress.failed } failed)</div>
                ) }
                { bulkProgress && bulkProgress.sent + bulkProgress.failed >= bulkProgress.total && bulkRecipients.length > 0 && (
                  <button type="button" className="btn btn-secondary btn-sm" style={ { marginTop: 8 } } onClick={ downloadResultsCsv }>
                    ⬇ Download results CSV
                  </button>
                ) }
                { bulkFailed.length > 0 && (
                  <div className="bulk-failed">
                    { bulkFailed.length } failed: { bulkFailed.slice( 0, 20 ).map( n => n.replace( /^(\d{2})\d+(\d{4})$/, '$1******$2' ) ).join( ', ' ) }{ bulkFailed.length > 20 ? '…' : '' }
                  </div>
                ) }
                <span className="manual-hint">One number per line, or a CSV with numbers (country code first column). Extra CSV columns become template variables { '{{1}}' },{ '{{2}}' }… per row; otherwise the variables above apply to everyone. Each number auto-creates a contact.</span>
              </>
            ) }
          </div>
        ) }

        {/* Template Selection */ }
        { !selectedTemplate ? (
          <div className="template-selection">
            <div className="search-filters">
              <input
                type="text"
                placeholder="Search templates..."
                value={ searchQuery }
                onChange={ ( e ) => setSearchQuery( e.target.value ) }
                className="search-input"
              />
              { /* `.category-filter` is dropped rather than forwarded: it SKINNED the native
                   control, a styled-jsx scope hash never reaches a child component's DOM, and
                   className on a Select lands on the wrapper. Only its width survives, as
                   layout, because `.search-filters` is a flex row. The rule itself is left in
                   the stylesheet below, dead and harmless. */ }
              <Select
                ariaLabel="Template category"
                value={ filterCategory }
                onChange={ v => setFilterCategory( v ) }
                options={ CATEGORY_FILTER_OPTIONS }
                style={ CATEGORY_FILTER_STYLE }
              />
            </div>

            { loading ? (
              <div className="loading">Loading templates...</div>
            ) : filteredTemplates.length === 0 ? (
              <div className="empty">No approved templates found</div>
            ) : (
              <div className="template-list">
                { filteredTemplates.map( template => (
                  <div
                    key={ template.id }
                    className="template-item"
                    onClick={ () => setSelectedTemplate( template ) }
                  >
                    <div className="template-info">
                      <span className="template-name">{ template.name }</span>
                      <span className={ `category-badge ${template.category.toLowerCase()}` }>
                        { template.category }
                      </span>
                      { template.components?.some( c => c.type === 'CAROUSEL' ) && (
                        <span className="carousel-badge">Carousel</span>
                      ) }
                    </div>
                    <div className="template-preview">
                      { template.components?.find( c => c.type === 'BODY' )?.text?.substring( 0, 80 ) || 'No preview' }...
                    </div>
                    <div className="template-lang">{ template.language }</div>
                  </div>
                ) ) }
              </div>
            ) }
          </div>
        ) : (
          <div className="template-config">
            <button className="back-btn" onClick={ () => setSelectedTemplate( null ) }>
              ← Back to templates
            </button>

            <div className="selected-template">
              <div className="template-header-info">
                <span className="template-name">{ selectedTemplate.name }</span>
                <span className={ `category-badge ${selectedTemplate.category.toLowerCase()}` }>
                  { selectedTemplate.category }
                </span>
                { isCarouselTemplate && <span className="carousel-badge">Carousel</span> }
              </div>
            </div>

            {/* Media Header (IMAGE / VIDEO / DOCUMENT) upload — required by Meta */ }
            { headerType && headerType !== 'location' && (
              <div className="header-media-section">
                <label>
                  { headerType === 'document' ? '📄 Document Header' : headerType === 'video' ? '🎬 Video Header' : '🖼️ Image Header' }
                  <span className="required-tag">required</span>
                </label>
                <div className="header-media-controls">
                  <label className="upload-btn">
                    { headerUploading ? 'Uploading…' : `Upload ${headerType}` }
                    <input
                      type="file"
                      accept={ headerAccept }
                      onChange={ handleHeaderUpload }
                      disabled={ headerUploading }
                      style={ { display: 'none' } }
                    />
                  </label>
                  <span className="or-sep">or</span>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={ toggleLibrary }>
                    { showLibrary ? 'Hide library' : '📁 Choose from library' }
                  </button>
                  <span className="or-sep">or</span>
                  <input
                    type="url"
                    className="header-url-input"
                    placeholder={ `Paste public ${headerType} URL` }
                    value={ headerMedia.startsWith( 'http' ) ? headerMedia : '' }
                    onChange={ ( e ) => { setHeaderMedia( e.target.value ); setHeaderFilename( '' ); } }
                  />
                </div>

                { showLibrary && (
                  <div className="media-library" style={ { marginTop: 10, border: '1.5px solid var(--lime)', borderRadius: 12, padding: 12, background: 'var(--bg-secondary)' } }>
                    <div style={ { display: 'flex', gap: 8, marginBottom: 10 } }>
                      <input
                        type="search"
                        className="header-url-input"
                        placeholder={ `🔍 Search ${headerType}s…` }
                        value={ librarySearch }
                        onChange={ ( e ) => setLibrarySearch( e.target.value ) }
                        onKeyDown={ ( e ) => { if ( e.key === 'Enter' ) loadLibrary(); } }
                        style={ { flex: 1 } }
                      />
                      <button type="button" className="btn btn-secondary btn-sm" onClick={ () => loadLibrary() } disabled={ libraryLoading }>
                        { libraryLoading ? '…' : 'Search' }
                      </button>
                    </div>
                    <div style={ { maxHeight: 220, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 } }>
                      { libraryLoading && <div style={ { fontSize: 13, color: 'var(--text-muted)', padding: 8 } }>Loading…</div> }
                      { !libraryLoading && libraryItems.length === 0 && (
                        <div style={ { fontSize: 13, color: 'var(--text-muted)', padding: 8 } }>No saved { headerType } files yet. Upload one above — it&apos;ll appear here for reuse.</div>
                      ) }
                      { libraryItems.map( ( item ) => (
                        <div key={ item.s3Key } style={ {
                          display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px',
                          background: headerMedia === item.mediaUrl ? 'var(--lime)' : '#fff',
                          border: '1px solid var(--border)', borderRadius: 8,
                        } }>
                          <span style={ { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13, fontWeight: 500 } } title={ item.filename }>
                            { item.filename }
                          </span>
                          <span style={ { fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' } }>{ formatSize( item.sizeBytes ) }</span>
                          <button type="button" className="btn btn-primary btn-sm" onClick={ () => pickFromLibrary( item ) }>Use</button>
                          <button
                            type="button"
                            className="btn btn-danger btn-sm"
                            aria-label={ `Permanently delete ${item.filename}` }
                            title="Permanently delete"
                            onClick={ () => deleteLibraryItem( item ) }
                            disabled={ libraryDeleting === item.s3Key }
                          >
                            { libraryDeleting === item.s3Key ? '…' : '🗑' }
                          </button>
                        </div>
                      ) ) }
                    </div>
                  </div>
                ) }
                { headerMedia && (
                  <div className="header-media-status">
                    ✓ { headerMedia.startsWith( 'http' ) ? 'Using link' : `Attached: ${headerFilename || 'file'}` }
                    <button className="clear-header" onClick={ () => { setHeaderMedia( '' ); setHeaderFilename( '' ); } }>×</button>
                  </div>
                ) }
              </div>
            ) }

            {/* Location Header — coordinates supplied at send time */ }
            { headerType === 'location' && (
              <div className="header-media-section">
                <label>📍 Location Header<span className="required-tag">required</span></label>
                <div className="place-search">
                  <input
                    className="header-url-input"
                    placeholder="Search address or place…"
                    value={ placeQuery }
                    onChange={ ( e ) => setPlaceQuery( e.target.value ) }
                  />
                  { placeSearching && <span className="manual-hint">Searching…</span> }
                  { placePredictions.length > 0 && (
                    <div className="place-dropdown">
                      { placePredictions.map( ( p ) => (
                        <button
                          key={ p.placeId }
                          type="button"
                          className="place-option"
                          onClick={ () => selectPlace( p.placeId, p.description ) }
                        >{ p.description }</button>
                      ) ) }
                    </div>
                  ) }
                </div>
                <div className="loc-grid">
                  <input className="header-url-input" placeholder="Latitude e.g. 37.4421" value={ locLat } onChange={ ( e ) => setLocLat( e.target.value ) } />
                  <input className="header-url-input" placeholder="Longitude e.g. -122.1615" value={ locLng } onChange={ ( e ) => setLocLng( e.target.value ) } />
                  <input className="header-url-input" placeholder="Place name (optional)" value={ locName } onChange={ ( e ) => setLocName( e.target.value ) } />
                  <input className="header-url-input" placeholder="Address (optional)" value={ locAddress } onChange={ ( e ) => setLocAddress( e.target.value ) } />
                </div>
                <span className="manual-hint">Search to auto-fill, or enter coordinates manually. Latitude & longitude are required.</span>
              </div>
            ) }

            {/* Variables Input */ }
            { variables.length > 0 && (
              <div className="variables-section">
                <label>Template Variables</label>
                { variables.map( ( v, idx ) => (
                  <div key={ idx } className="variable-row">
                    <span className="var-label">{ `{{${v.index}}}` }</span>
                    <input
                      type="text"
                      value={ v.value }
                      onChange={ ( e ) => updateVariable( idx, e.target.value ) }
                      placeholder={ v.placeholder }
                    />
                  </div>
                ) ) }
              </div>
            ) }

            {/* Card Variables for Carousel */ }
            { isCarouselTemplate && cardVariables.length > 0 && (
              <div className="card-variables-section">
                <label>Card Variables</label>
                { cardVariables.map( ( card, cardIdx ) => (
                  card.length > 0 && (
                    <div key={ cardIdx } className="card-vars">
                      <span className="card-label">Card { cardIdx + 1 }</span>
                      { card.map( ( v, varIdx ) => (
                        <div key={ varIdx } className="variable-row">
                          <span className="var-label">{ `{{${v.index}}}` }</span>
                          <input
                            type="text"
                            value={ v.value }
                            onChange={ ( e ) => updateCardVariable( cardIdx, varIdx, e.target.value ) }
                            placeholder={ v.placeholder }
                          />
                        </div>
                      ) ) }
                    </div>
                  )
                ) ) }
              </div>
            ) }

            {/* Preview */ }
            <div className="preview-section">
              <label>Preview</label>
              <div className="preview-box">
                <div className="preview-recipient">To: { manualMode ? ( manualPhone || 'new number' ) : contactName }</div>
                <div className="preview-content">{ getPreviewText() }</div>
                { isCarouselTemplate && (
                  <div className="carousel-indicator">
                    + { cardVariables.length } carousel cards
                  </div>
                ) }
              </div>
            </div>

            {/* Schedule Option */ }
            <div className="schedule-section">
              <label className="schedule-toggle">
                <input
                  type="checkbox"
                  checked={ scheduleMode }
                  onChange={ ( e ) => setScheduleMode( e.target.checked ) }
                />
                <span>Schedule for later</span>
              </label>

              { /* The schedule pair, ours now. Both were unlabelled - two bare inputs in a
                   row - so each takes an `ariaLabel` and the schedule finally reads as
                   "Scheduled date" and "Scheduled time" rather than two blank fields. `min`
                   is the same expression as before and is now enforced in the grid AND on
                   type-in, which a native input does neither of. ISO / HH:MM in and out, so
                   `scheduledDate` and `scheduledTime` reach the send call unchanged. */ }
              { scheduleMode && (
                <div className="schedule-inputs">
                  <DateField
                    ariaLabel="Scheduled date"
                    value={ scheduledDate }
                    onChange={ setScheduledDate }
                    min={ new Date().toISOString().split( 'T' )[ 0 ] }
                  />
                  <TimeField
                    ariaLabel="Scheduled time"
                    value={ scheduledTime }
                    onChange={ setScheduledTime }
                  />
                </div>
              ) }
            </div>
          </div>
        ) }
      </div>

      <div className="sender-footer">
        <button className="cancel-btn" onClick={ onClose }>Cancel</button>
        <button
          className="send-btn"
          onClick={ handleSend }
          disabled={ !selectedTemplate || sending || headerUploading || ( !!headerType && headerType !== 'location' && !headerMedia ) || ( headerType === 'location' && ( !locLat.trim() || !locLng.trim() ) ) || ( manualMode && !bulkMode && manualPhone.replace( /[^\d]/g, '' ).length < 10 ) || ( manualMode && bulkMode && bulkRecipients.length === 0 ) }
        >
          { sending ? 'Sending...' : ( manualMode && bulkMode ) ? `Send to ${bulkRecipients.length || ''}` : scheduleMode ? 'Schedule' : 'Send Now' }
        </button>
      </div>

      <style jsx>{ `
        .template-sender {
          position: fixed;
          bottom: 80px;
          right: 20px;
          width: 450px;
          max-height: 85vh;
          background: white;
          border-radius: 12px;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
          display: flex;
          flex-direction: column;
          z-index: 1000;
        }
        .sender-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 14px 18px;
          border-bottom: 1px solid #eee;
        }
        .sender-header h3 {
          margin: 0;
          font-size: 16px;
        }
        .close-btn {
          background: none;
          border: none;
          font-size: 24px;
          cursor: pointer;
          color: #666;
        }
        .sender-body {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }
        .manual-recipient {
          display: flex;
          flex-direction: column;
          gap: 6px;
          margin-bottom: 14px;
          padding: 12px;
          border: 1px solid #d1fae5;
          border-radius: 8px;
          background: #f0fdf4;
        }
        .manual-recipient > label {
          font-size: 13px;
          font-weight: 600;
          color: #1a3a2a;
        }
        .manual-phone-input {
          padding: 10px 12px;
          border: 1px solid #ddd;
          border-radius: 8px;
          font-size: 14px;
        }
        .manual-phone-input:focus { outline: none; border-color: #1a3a2a; }
        .manual-hint { font-size: 11px; color: #6b7280; line-height: 1.4; }
        .recip-mode-toggle { display: flex; gap: 6px; margin-bottom: 4px; }
        .mode-pill {
          flex: 1;
          padding: 7px 10px;
          font-size: 12px;
          font-weight: 600;
          border: 1px solid #cbd5d0;
          border-radius: 8px;
          background: #fff;
          color: #1a3a2a;
          cursor: pointer;
        }
        .mode-pill.active { background: #1a3a2a; color: #fff; border-color: #1a3a2a; }
        .csv-upload-btn {
          display: inline-block;
          padding: 9px 12px;
          border: 1px dashed #1a3a2a;
          border-radius: 8px;
          font-size: 13px;
          font-weight: 600;
          color: #1a3a2a;
          background: #fff;
          cursor: pointer;
          text-align: center;
        }
        .csv-upload-btn:hover { background: #f0f5f2; }
        .bulk-count {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12px;
          color: #166534;
          font-weight: 600;
        }
        .bulk-progress { font-size: 12px; color: #1a3a2a; font-weight: 600; }
        .bulk-pers { font-size: 11px; color: rgba(0, 0, 0, 0.54); font-weight: 500; }
        .bulk-failed { font-size: 11px; color: #b91c1c; margin-top: 4px; word-break: break-word; }
        .loc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .place-search { position: relative; margin-bottom: 8px; }
        .place-dropdown {
          position: absolute;
          top: 100%;
          left: 0;
          right: 0;
          z-index: 20;
          background: #fff;
          border: 1px solid #d1d5db;
          border-radius: 8px;
          box-shadow: 0 4px 16px rgba(0,0,0,0.12);
          max-height: 200px;
          overflow-y: auto;
        }
        .place-option {
          display: block;
          width: 100%;
          text-align: left;
          padding: 8px 12px;
          font-size: 13px;
          border: none;
          background: #fff;
          cursor: pointer;
          border-bottom: 1px solid #f0f0f0;
        }
        .place-option:hover { background: #f0f5f2; }
        .search-filters {
          display: flex;
          gap: 8px;
          margin-bottom: 12px;
        }
        .search-input {
          flex: 1;
          padding: 10px 12px;
          border: 1px solid #ddd;
          border-radius: 8px;
          font-size: 14px;
        }
        .category-filter {
          padding: 10px 12px;
          border: 1px solid #ddd;
          border-radius: 8px;
          font-size: 14px;
          min-width: 120px;
        }
        .loading, .empty {
          text-align: center;
          padding: 40px 20px;
          color: #666;
        }
        .template-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          max-height: 400px;
          overflow-y: auto;
        }
        .template-item {
          padding: 12px;
          border: 1px solid #eee;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s;
        }
        .template-item:hover {
          border-color: #000;
          background: #f5f5f5;
        }
        .template-info {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 6px;
        }
        .template-name {
          font-weight: 500;
          font-size: 14px;
        }
        .category-badge {
          font-size: 10px;
          padding: 2px 8px;
          border-radius: 10px;
          color: white;
        }
        .category-badge.utility { background: #1a3a2a; }
        .category-badge.marketing { background: #1a3a2a; }
        .category-badge.authentication { background: #0f2a1d; }
        .carousel-badge {
          font-size: 10px;
          padding: 2px 8px;
          background: #f9fafb;
          color: #0f2a1d;
          border-radius: 10px;
        }
        .template-preview {
          font-size: 12px;
          color: #666;
          line-height: 1.4;
        }
        .template-lang {
          font-size: 11px;
          color: #999;
          margin-top: 4px;
        }
        .back-btn {
          background: none;
          border: none;
          color: #1a3a2a;
          cursor: pointer;
          font-size: 13px;
          padding: 0;
          margin-bottom: 12px;
        }
        .back-btn:hover {
          text-decoration: underline;
        }
        .selected-template {
          padding: 12px;
          background: #f9f9f9;
          border-radius: 8px;
          margin-bottom: 16px;
        }
        .template-header-info {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .variables-section, .card-variables-section {
          margin-bottom: 16px;
        }
        .variables-section > label, .card-variables-section > label {
          display: block;
          font-size: 13px;
          font-weight: 500;
          margin-bottom: 8px;
          color: #333;
        }
        .header-media-section {
          margin-bottom: 16px;
          padding: 12px;
          border: 1px dashed #c7d2cc;
          border-radius: 8px;
          background: #f8faf9;
        }
        .header-media-section > label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          font-weight: 600;
          margin-bottom: 10px;
          color: #1a3a2a;
        }
        .required-tag {
          font-size: 10px;
          font-weight: 500;
          color: #b91c1c;
          background: #fee2e2;
          padding: 1px 6px;
          border-radius: 8px;
        }
        .header-media-controls {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .upload-btn {
          padding: 8px 12px;
          border: 1px solid #1a3a2a;
          border-radius: 6px;
          font-size: 13px;
          cursor: pointer;
          background: #fff;
          white-space: nowrap;
        }
        .upload-btn:hover { background: #f0f5f2; }
        .or-sep { font-size: 12px; color: #999; }
        .header-url-input {
          flex: 1;
          padding: 8px 10px;
          border: 1px solid #ddd;
          border-radius: 6px;
          font-size: 13px;
        }
        .header-media-status {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 8px;
          font-size: 12px;
          color: #166534;
        }
        .clear-header {
          background: none;
          border: none;
          color: #b91c1c;
          font-size: 16px;
          cursor: pointer;
          line-height: 1;
        }
        .variable-row {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
        }
        .var-label {
          font-size: 12px;
          color: #666;
          min-width: 50px;
          font-family: monospace;
        }
        .variable-row input {
          flex: 1;
          padding: 8px 12px;
          border: 1px solid #ddd;
          border-radius: 6px;
          font-size: 14px;
        }
        .variable-row input:focus {
          outline: none;
          border-color: #000;
        }
        .card-vars {
          background: #f5f5f5;
          padding: 10px;
          border-radius: 6px;
          margin-bottom: 8px;
        }
        .card-label {
          display: block;
          font-size: 12px;
          font-weight: 500;
          color: #666;
          margin-bottom: 8px;
        }
        .preview-section {
          margin-bottom: 16px;
        }
        .preview-section > label {
          display: block;
          font-size: 13px;
          font-weight: 500;
          margin-bottom: 8px;
          color: #333;
        }
        .preview-box {
          background: #e5ddd5;
          padding: 12px;
          border-radius: 8px;
        }
        .preview-recipient {
          font-size: 11px;
          color: #666;
          margin-bottom: 8px;
        }
        .preview-content {
          background: #dcf8c6;
          padding: 10px 12px;
          border-radius: 8px;
          font-size: 14px;
          line-height: 1.5;
          white-space: pre-wrap;
        }
        .carousel-indicator {
          margin-top: 8px;
          font-size: 12px;
          color: #0f2a1d;
          background: #f9fafb;
          padding: 6px 10px;
          border-radius: 6px;
          text-align: center;
        }
        .schedule-section {
          margin-top: 16px;
          padding-top: 16px;
          border-top: 1px solid #eee;
        }
        .schedule-toggle {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
          font-size: 14px;
        }
        .schedule-toggle input {
          width: 18px;
          height: 18px;
        }
        .schedule-inputs {
          display: flex;
          gap: 8px;
          margin-top: 12px;
        }
        /* The .schedule-inputs input rule is gone with the two native controls it skinned. It
           could not be kept even as dead CSS: styled-jsx scopes a selector to the DOM tags it
           can see in this file, and the inputs are now inside DateField and TimeField, which
           never receive that hash. The pickers' own flex: 1 1 0 in form-controls.css replaces
           the flex: 1 this rule supplied; the 1px #ddd / 6px radius it declared is replaced by
           the shared control tokens, which is the point of the batch.
           NO BACKTICK IN A styled-jsx COMMENT - this block is a template literal, so a
           backtick around a property name terminates it and the parser reports a cascade of
           JSX errors 400 lines later. */
        .schedule-inputs > :global(.ui-field) {
          flex: 1 1 0;
          min-width: 0;
        }
        .sender-footer {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          padding: 14px 18px;
          border-top: 1px solid #eee;
        }
        .cancel-btn {
          padding: 10px 18px;
          border: 1px solid #ddd;
          background: white;
          border-radius: 8px;
          cursor: pointer;
          font-size: 14px;
        }
        .cancel-btn:hover {
          background: #f5f5f5;
        }
        .send-btn {
          padding: 10px 24px;
          border: 1px solid #000;
          background: #fff;
          color: #000;
          border-radius: 13px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 500;
        }
        .send-btn:hover:not(:disabled) {
          background: #f5f5f5;
        }
        .send-btn:disabled {
          background: #9ca3af;
          cursor: not-allowed;
        }
        @media (max-width: 500px) {
          .template-sender {
            width: calc(100vw - 40px);
            right: 20px;
            left: 20px;
          }
        }
      `}</style>
    </div>
  );
};

export default TemplateSender;
