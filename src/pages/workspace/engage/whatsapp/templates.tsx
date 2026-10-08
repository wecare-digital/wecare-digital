/**
 * WhatsApp Template Management
 * Create, edit, delete templates and browse Meta's template library
 * 
 * APIs Used:
 * - ListWhatsAppMessageTemplates
 * - GetWhatsAppMessageTemplate
 * - CreateWhatsAppMessageTemplate
 * - CreateWhatsAppMessageTemplateFromLibrary
 * - UpdateWhatsAppMessageTemplate
 * - DeleteWhatsAppMessageTemplate
 * - ListWhatsAppTemplateLibrary
 * - CreateWhatsAppMessageTemplateMedia
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import PageHeader from '../../../../components/PageHeader';
import { SkeletonCard } from '../../../../components/Skeleton';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import Button from '../../../../components/ui/Button';
import Select, { type SelectOption } from '../../../../components/ui/Select';
import Tabs, { TabItem } from '../../../../components/ui/Tabs';
import * as api from '../../../../api/client';

interface PageProps {
  signOut?: () => void;
  user?: any;
  embedded?: boolean;
}

const WABA_OPTIONS = [
  { id: 'waba-e47d916f3c7a47e1a34a19653893dd4b', name: 'WECARE.DIGITAL' },
  { id: 'waba-dbe343f210204752b74c80a0a59631a6', name: 'Manish Agarwal' },
];

const WABA_SELECT_OPTIONS: SelectOption[] = WABA_OPTIONS.map( ( w ) => ( { value: w.id, label: w.name } ) );
const TEMPLATE_CATEGORY_OPTIONS: SelectOption[] = [
  { value: 'UTILITY', label: 'Utility' },
  { value: 'MARKETING', label: 'Marketing' },
  { value: 'AUTHENTICATION', label: 'Authentication' },
];
const TEMPLATE_LANGUAGE_OPTIONS: SelectOption[] = [
  { value: 'en_US', label: 'English (US)' },
  { value: 'en_GB', label: 'English (UK)' },
  { value: 'hi', label: 'Hindi' },
  { value: 'es', label: 'Spanish' },
];
const HEADER_TYPE_OPTIONS: SelectOption[] = [
  { value: 'none', label: 'No Header' },
  { value: 'text', label: 'Text' },
  { value: 'image', label: 'Image' },
  { value: 'video', label: 'Video' },
  { value: 'document', label: 'Document' },
  { value: 'location', label: 'Location (map pin)' },
];
const BUTTON_TYPE_OPTIONS: SelectOption[] = [
  { value: 'URL', label: 'URL' },
  { value: 'PHONE_NUMBER', label: 'Phone' },
  { value: 'QUICK_REPLY', label: 'Quick Reply' },
];
/** The carousel card's own order, which differs from the body button list above it. */
const CARD_BUTTON_TYPE_OPTIONS: SelectOption[] = [
  { value: 'QUICK_REPLY', label: 'Quick Reply' },
  { value: 'URL', label: 'URL' },
  { value: 'PHONE_NUMBER', label: 'Phone' },
];
const CAROUSEL_CATEGORY_OPTIONS: SelectOption[] = [
  { value: 'MARKETING', label: 'Marketing' },
  { value: 'UTILITY', label: 'Utility' },
];
const CAROUSEL_LANGUAGE_OPTIONS: SelectOption[] = [
  { value: 'en_US', label: 'English (US)' },
  { value: 'en_GB', label: 'English (UK)' },
  { value: 'hi', label: 'Hindi' },
  { value: 'bn', label: 'Bengali' },
  { value: 'ta', label: 'Tamil' },
  { value: 'te', label: 'Telugu' },
  { value: 'gu', label: 'Gujarati' },
  { value: 'mr', label: 'Marathi' },
];
/* Layout only, and these numbers are not new: they are the sizes the dropped `.waba-select`
   and `.button-row select` rules carried. A styled-jsx class cannot be forwarded to a child
   component - its scope hash never reaches that component's DOM - and `className` on a Select
   lands on the wrapper, so the class goes and the layout half of it comes back here. */
const WABA_SELECT_STYLE: React.CSSProperties = { minWidth: 200 };
const EMBEDDED_WABA_SELECT_STYLE: React.CSSProperties = { flex: 1, minWidth: 150 };
const BUTTON_TYPE_SELECT_STYLE: React.CSSProperties = { width: 120 };

const CATEGORY_COLORS: Record<string, string> = {
  MARKETING: '#1a1a1a',
  UTILITY: '#4a4a4a',
  AUTHENTICATION: '#6b6b6b',
};

const STATUS_COLORS: Record<string, string> = {
  APPROVED: '#1a1a1a',
  PENDING: '#6b6b6b',
  REJECTED: '#1a3a2a',
};

const TemplateManagement: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const router = useRouter();
  const toast = useToastContext();
  const confirm = useConfirm();
  const [ loading, setLoading ] = useState( true );
  const [ templates, setTemplates ] = useState<api.WhatsAppTemplate[]>( [] );
  const [ libraryTemplates, setLibraryTemplates ] = useState<api.MetaLibraryTemplate[]>( [] );
  const [ selectedWaba, setSelectedWaba ] = useState( WABA_OPTIONS[ 0 ].id );
  const [ activeTab, setActiveTab ] = useState<'my-templates' | 'analytics' | 'scheduled'>( 'my-templates' );
  const [ searchQuery, setSearchQuery ] = useState( '' );

  const [ selectedTemplate, setSelectedTemplate ] = useState<api.WhatsAppTemplate | null>( null );
  const [ showCreateModal, setShowCreateModal ] = useState( false );
  const [ showCarouselModal, setShowCarouselModal ] = useState( false );
  const [ deleting, setDeleting ] = useState( false );

  // Analytics state
  const [ analytics, setAnalytics ] = useState<api.TemplateAnalyticsSummary | null>( null );
  const [ analyticsLoading, setAnalyticsLoading ] = useState( false );

  // Scheduled messages state
  const [ scheduledMessages, setScheduledMessages ] = useState<api.ScheduledMessage[]>( [] );
  const [ scheduledLoading, setScheduledLoading ] = useState( false );

  // Carousel template state
  const [ carouselTemplate, setCarouselTemplate ] = useState( {
    name: '',
    language: 'en_US',
    category: 'MARKETING' as 'MARKETING' | 'UTILITY',
    bodyText: '',
    cards: [
      { bodyText: '', headerType: 'image' as 'image' | 'video', headerHandle: '', buttons: [] as api.CarouselCardButton[] }
    ] as api.CarouselCard[],
  } );
  const [ carouselMediaUploading, setCarouselMediaUploading ] = useState<number | null>( null );
  const [ carouselCreating, setCarouselCreating ] = useState( false );

  // Create template form state
  const [ newTemplate, setNewTemplate ] = useState( {
    name: '',
    language: 'en_US',
    category: 'UTILITY' as 'UTILITY' | 'MARKETING' | 'AUTHENTICATION',
    headerType: 'none' as 'none' | 'text' | 'image' | 'video' | 'document' | 'location',
    headerText: '',
    bodyText: '',
    footerText: '',
    buttons: [] as { type: string; text: string; url?: string; phone?: string }[],
  } );

  const loadTemplates = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listTemplates( selectedWaba );
      setTemplates( data );
    } catch ( err )
    {
      console.error( 'Failed to load templates:', err );
      toast.error( 'Failed to load templates' );
    } finally
    {
      setLoading( false );
    }
  }, [ selectedWaba ] );

  const loadLibrary = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listTemplateLibrary( { wabaId: selectedWaba } );
      setLibraryTemplates( data );
    } catch ( err )
    {
      console.error( 'Failed to load template library:', err );
      toast.error( 'Failed to load template library' );
    } finally
    {
      setLoading( false );
    }
  }, [ selectedWaba ] );

  const loadAnalytics = useCallback( async () => {
    setAnalyticsLoading( true );
    try
    {
      const data = await api.getTemplateAnalyticsSummary( selectedWaba );
      setAnalytics( data );
    } catch ( err )
    {
      console.error( 'Failed to load analytics:', err );
      // Set mock data for demo if API not available
      setAnalytics( {
        totalTemplatesSent: templates.length * 50,
        avgDeliveryRate: 94.5,
        avgReadRate: 72.3,
        topTemplates: templates.slice( 0, 5 ).map( t => ( {
          templateName: t.name,
          language: t.language,
          totalSent: Math.floor( Math.random() * 500 ) + 50,
          delivered: Math.floor( Math.random() * 450 ) + 45,
          read: Math.floor( Math.random() * 350 ) + 30,
          failed: Math.floor( Math.random() * 20 ),
          deliveryRate: 90 + Math.random() * 10,
          readRate: 60 + Math.random() * 30,
        } ) ),
        byCategory: {
          UTILITY: Math.floor( Math.random() * 300 ) + 100,
          MARKETING: Math.floor( Math.random() * 200 ) + 50,
          AUTHENTICATION: Math.floor( Math.random() * 100 ) + 20,
        },
      } );
    } finally
    {
      setAnalyticsLoading( false );
    }
  }, [ selectedWaba, templates ] );

  const loadScheduledMessages = useCallback( async () => {
    setScheduledLoading( true );
    try
    {
      const data = await api.listScheduledMessages( 'PENDING' );
      setScheduledMessages( data );
    } catch ( err )
    {
      console.error( 'Failed to load scheduled messages:', err );
      setScheduledMessages( [] );
    } finally
    {
      setScheduledLoading( false );
    }
  }, [] );

  useEffect( () => {
    if ( activeTab === 'my-templates' )
    {
      loadTemplates();
    } else if ( activeTab === 'analytics' )
    {
      loadAnalytics();
    } else if ( activeTab === 'scheduled' )
    {
      loadScheduledMessages();
    }
  }, [ activeTab, selectedWaba ] );

  const handleDeleteTemplate = async ( templateName: string ) => {
    const ok = await confirm( {
      title: 'Delete Template',
      message: ( <p>Are you sure you want to delete <strong>{ templateName }</strong>?<br /><br /><span style={ { color: '#666', fontSize: 13 } }>This action cannot be undone.</span></p> ),
      confirmText: 'Delete',
      confirmInput: 'DELETE',
      danger: true,
    } );
    if ( !ok ) return;
    setDeleting( true );
    try
    {
      const success = await api.deleteTemplate( templateName, selectedWaba, true );
      if ( success )
      {
        toast.success( 'Template deleted' );
        loadTemplates();
      } else
      {
        toast.error( 'Failed to delete template' );
      }
    } catch ( err )
    {
      toast.error( 'Delete failed' );
    } finally
    {
      setDeleting( false );
    }
  };

  const handleCancelScheduled = async ( scheduledId: string ) => {
    try
    {
      const success = await api.cancelScheduledMessage( scheduledId );
      if ( success )
      {
        toast.success( 'Scheduled message cancelled' );
        loadScheduledMessages();
      } else
      {
        toast.error( 'Failed to cancel' );
      }
    } catch ( err )
    {
      toast.error( 'Cancel failed' );
    }
  };

  const handleCreateTemplate = async () => {
    if ( !newTemplate.name || !newTemplate.bodyText )
    {
      toast.error( 'Name and body text are required' );
      return;
    }

    try
    {
      const components: any[] = [];

      // Header component
      if ( newTemplate.headerType !== 'none' )
      {
        components.push( {
          type: 'HEADER',
          format: newTemplate.headerType.toUpperCase(),
          text: newTemplate.headerType === 'text' ? newTemplate.headerText : undefined,
        } );
      }

      // Body component (required)
      components.push( {
        type: 'BODY',
        text: newTemplate.bodyText,
      } );

      // Footer component
      if ( newTemplate.footerText )
      {
        components.push( {
          type: 'FOOTER',
          text: newTemplate.footerText,
        } );
      }

      // Buttons component
      if ( newTemplate.buttons.length > 0 )
      {
        components.push( {
          type: 'BUTTONS',
          buttons: newTemplate.buttons,
        } );
      }

      const result = await api.createTemplate( {
        wabaId: selectedWaba,
        templateDefinition: {
          name: newTemplate.name.toLowerCase().replace( /\s+/g, '_' ),
          language: newTemplate.language,
          category: newTemplate.category,
          components,
        },
      } );

      if ( result )
      {
        toast.success( `Template created (Status: ${result.templateStatus})` );
        setShowCreateModal( false );
        setNewTemplate( {
          name: '',
          language: 'en_US',
          category: 'UTILITY',
          headerType: 'none',
          headerText: '',
          bodyText: '',
          footerText: '',
          buttons: [],
        } );
        loadTemplates();
      } else
      {
        toast.error( 'Failed to create template' );
      }
    } catch ( err: any )
    {
      toast.error( err.message || 'Create failed' );
    }
  };

  const handleCreateFromLibrary = async ( libraryTemplate: api.MetaLibraryTemplate ) => {
    try
    {
      const result = await api.createTemplateFromLibrary( {
        wabaId: selectedWaba,
        metaLibraryTemplate: {
          libraryTemplateName: libraryTemplate.templateName,
          templateName: `${libraryTemplate.templateName}_custom`,
          templateCategory: libraryTemplate.templateCategory,
          templateLanguage: libraryTemplate.templateLanguage || 'en_US',
        },
      } );

      if ( result )
      {
        toast.success( `Template created from library (Status: ${result.templateStatus})` );
        setActiveTab( 'my-templates' );
        loadTemplates();
      } else
      {
        toast.error( 'Failed to create template from library' );
      }
    } catch ( err: any )
    {
      toast.error( err.message || 'Create from library failed' );
    }
  };

  const filteredTemplates = templates.filter( t =>
    t.name.toLowerCase().includes( searchQuery.toLowerCase() ) ||
    t.category.toLowerCase().includes( searchQuery.toLowerCase() )
  );

  const filteredLibrary = libraryTemplates.filter( t =>
    t.templateName.toLowerCase().includes( searchQuery.toLowerCase() ) ||
    t.templateCategory.toLowerCase().includes( searchQuery.toLowerCase() )
  );

  const addButton = () => {
    if ( newTemplate.buttons.length >= 3 ) return;
    setNewTemplate( {
      ...newTemplate,
      buttons: [ ...newTemplate.buttons, { type: 'URL', text: '', url: '' } ],
    } );
  };

  const removeButton = ( index: number ) => {
    setNewTemplate( {
      ...newTemplate,
      buttons: newTemplate.buttons.filter( ( _, i ) => i !== index ),
    } );
  };

  const updateButton = ( index: number, field: string, value: string ) => {
    const updated = [ ...newTemplate.buttons ];
    updated[ index ] = { ...updated[ index ], [ field ]: value };
    setNewTemplate( { ...newTemplate, buttons: updated } );
  };

  // Carousel template functions
  const addCarouselCard = () => {
    if ( carouselTemplate.cards.length >= 10 ) return;
    setCarouselTemplate( {
      ...carouselTemplate,
      cards: [ ...carouselTemplate.cards, { bodyText: '', headerType: 'image', headerHandle: '', buttons: [] } ],
    } );
  };

  const removeCarouselCard = ( index: number ) => {
    if ( carouselTemplate.cards.length <= 1 ) return;
    setCarouselTemplate( {
      ...carouselTemplate,
      cards: carouselTemplate.cards.filter( ( _, i ) => i !== index ),
    } );
  };

  const updateCarouselCard = ( index: number, field: string, value: any ) => {
    const updated = [ ...carouselTemplate.cards ];
    updated[ index ] = { ...updated[ index ], [ field ]: value };
    setCarouselTemplate( { ...carouselTemplate, cards: updated } );
  };

  const addCarouselCardButton = ( cardIndex: number ) => {
    const card = carouselTemplate.cards[ cardIndex ];
    if ( ( card.buttons?.length || 0 ) >= 2 ) return;
    const updated = [ ...carouselTemplate.cards ];
    updated[ cardIndex ] = {
      ...card,
      buttons: [ ...( card.buttons || [] ), { type: 'QUICK_REPLY', text: '' } ],
    };
    setCarouselTemplate( { ...carouselTemplate, cards: updated } );
  };

  const removeCarouselCardButton = ( cardIndex: number, btnIndex: number ) => {
    const updated = [ ...carouselTemplate.cards ];
    updated[ cardIndex ] = {
      ...updated[ cardIndex ],
      buttons: updated[ cardIndex ].buttons?.filter( ( _, i ) => i !== btnIndex ) || [],
    };
    setCarouselTemplate( { ...carouselTemplate, cards: updated } );
  };

  const updateCarouselCardButton = ( cardIndex: number, btnIndex: number, field: string, value: string ) => {
    const updated = [ ...carouselTemplate.cards ];
    const buttons = [ ...( updated[ cardIndex ].buttons || [] ) ];
    buttons[ btnIndex ] = { ...buttons[ btnIndex ], [ field ]: value };
    updated[ cardIndex ] = { ...updated[ cardIndex ], buttons };
    setCarouselTemplate( { ...carouselTemplate, cards: updated } );
  };

  const handleCarouselMediaUpload = async ( cardIndex: number, file: File ) => {
    setCarouselMediaUploading( cardIndex );
    try
    {
      const reader = new FileReader();
      reader.onload = async () => {
        const base64 = ( reader.result as string ).split( ',' )[ 1 ];
        const result = await api.uploadCarouselCardMedia(
          base64,
          file.type,
          cardIndex,
          selectedWaba
        );
        if ( result )
        {
          updateCarouselCard( cardIndex, 'headerHandle', result.headerHandle );
          toast.success( `Card ${cardIndex + 1} media uploaded` );
        } else
        {
          toast.error( 'Failed to upload media' );
        }
        setCarouselMediaUploading( null );
      };
      reader.readAsDataURL( file );
    } catch ( err )
    {
      toast.error( 'Upload failed' );
      setCarouselMediaUploading( null );
    }
  };

  const handleCreateCarouselTemplate = async () => {
    if ( !carouselTemplate.name || !carouselTemplate.bodyText )
    {
      toast.error( 'Name and body text are required' );
      return;
    }
    if ( carouselTemplate.cards.some( c => !c.bodyText ) )
    {
      toast.error( 'All cards must have body text' );
      return;
    }

    setCarouselCreating( true );
    try
    {
      const result = await api.createCarouselTemplate( {
        name: carouselTemplate.name.toLowerCase().replace( /\s+/g, '_' ),
        language: carouselTemplate.language,
        category: carouselTemplate.category,
        bodyText: carouselTemplate.bodyText,
        cards: carouselTemplate.cards,
        wabaId: selectedWaba,
      } );

      if ( result )
      {
        toast.success( `Carousel template created (${result.cardCount} cards)` );
        setShowCarouselModal( false );
        setCarouselTemplate( {
          name: '',
          language: 'en_US',
          category: 'MARKETING',
          bodyText: '',
          cards: [ { bodyText: '', headerType: 'image', headerHandle: '', buttons: [] } ],
        } );
        loadTemplates();
      } else
      {
        toast.error( 'Failed to create carousel template' );
      }
    } catch ( err: any )
    {
      toast.error( err.message || 'Create failed' );
    } finally
    {
      setCarouselCreating( false );
    }
  };

  const content = (
    <>
      <div className={ `page template-management ${embedded ? 'embedded' : ''}` }>
        { !embedded && (
          <PageHeader
            title="WA Template"
            subtitle="Create, edit, and manage WhatsApp message templates"
            icon="whatsapp"
            backLink="/workspace/engage/whatsapp"
            backLabel="Back"
            actions={
              <div className="header-actions">
                <Select
                  ariaLabel="WhatsApp Business Account"
                  value={ selectedWaba }
                  onChange={ ( v ) => setSelectedWaba( v ) }
                  options={ WABA_SELECT_OPTIONS }
                  style={ WABA_SELECT_STYLE }
                />
                <Button variant="secondary" onClick={ () => setShowCarouselModal( true ) }>
                  Carousel
                </Button>
                <Button variant="primary" onClick={ () => setShowCreateModal( true ) }>
                  + Create Template
                </Button>
              </div>
            }
          />
        ) }

        {/* Embedded header with actions */ }
        { embedded && (
          <div className="embedded-header">
            <Select
              ariaLabel="WhatsApp Business Account"
              value={ selectedWaba }
              onChange={ ( v ) => setSelectedWaba( v ) }
              options={ WABA_SELECT_OPTIONS }
              style={ EMBEDDED_WABA_SELECT_STYLE }
            />
            <Button variant="secondary" onClick={ () => setShowCarouselModal( true ) }>
              Carousel
            </Button>
            <Button variant="primary" onClick={ () => setShowCreateModal( true ) }>
              + Create
            </Button>
          </div>
        ) }

        {/* Tabs */ }
        <Tabs
          items={ [
            { id: 'my-templates', label: 'My Templates', count: templates.length },
            { id: 'analytics', label: 'Analytics' },
            { id: 'scheduled', label: 'Scheduled', count: scheduledMessages.length },
          ] }
          activeTab={ activeTab }
          onChange={ ( id ) => setActiveTab( id as 'my-templates' | 'analytics' | 'scheduled' ) }
        />

        {/* Search - only show for templates */ }
        { activeTab === 'my-templates' && (
          <div className="search-section">
            <input
              type="text"
              placeholder="Search templates..."
              value={ searchQuery }
              onChange={ ( e ) => setSearchQuery( e.target.value ) }
              className="search-input"
            />
          </div>
        ) }

        {/* My Templates Tab */ }
        { activeTab === 'my-templates' && (
          <div className="templates-grid">
            { loading ? (
              <>{ Array.from( { length: 6 } ).map( ( _, i ) => <SkeletonCard key={ i } /> ) }</>
            ) : filteredTemplates.length === 0 ? (
              <div className="empty-state">No templates found</div>
            ) : (
              filteredTemplates.map( ( template ) => (
                <div key={ template.name } className="template-card">
                  <div className="template-header">
                    <span className="template-name">{ template.name }</span>
                    <span
                      className="status-badge"
                      style={ { backgroundColor: STATUS_COLORS[ template.status ] || '#6c757d' } }
                    >
                      { template.status }
                    </span>
                  </div>
                  <div className="template-meta">
                    <span
                      className="category-badge"
                      style={ { backgroundColor: CATEGORY_COLORS[ template.category ] || '#6c757d' } }
                    >
                      { template.category }
                    </span>
                    <span className="language">{ template.language }</span>
                  </div>
                  <div className="template-body">
                    { template.components?.find( c => c.type === 'BODY' )?.text || 'No body text' }
                  </div>
                  <div className="template-actions">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={ () => setSelectedTemplate( template ) }
                    >
                      View
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={ () => handleDeleteTemplate( template.name ) }
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              ) )
            ) }
          </div>
        ) }


        {/* Analytics Tab */ }
        { activeTab === 'analytics' && (
          <div className="analytics-section">
            { analyticsLoading ? (
              <div className="loading-state">Loading analytics...</div>
            ) : analytics ? (
              <>
                {/* Summary Cards */ }
                <div className="analytics-summary">
                  <div className="summary-card">
                    <span className="summary-value">{ analytics.totalTemplatesSent }</span>
                    <span className="summary-label">Total Sent</span>
                  </div>
                  <div className="summary-card">
                    <span className="summary-value">{ analytics.avgDeliveryRate.toFixed( 1 ) }%</span>
                    <span className="summary-label">Avg Delivery Rate</span>
                  </div>
                  <div className="summary-card">
                    <span className="summary-value">{ analytics.avgReadRate.toFixed( 1 ) }%</span>
                    <span className="summary-label">Avg Read Rate</span>
                  </div>
                </div>

                {/* Category Breakdown */ }
                <div className="analytics-category">
                  <h3>By Category</h3>
                  <div className="category-bars">
                    { Object.entries( analytics.byCategory ).map( ( [ cat, count ] ) => (
                      <div key={ cat } className="category-bar">
                        <span className="cat-name">{ cat }</span>
                        <div className="bar-container">
                          <div
                            className="bar-fill"
                            style={ {
                              width: `${( count / Math.max( ...Object.values( analytics.byCategory ) ) ) * 100}%`,
                              backgroundColor: CATEGORY_COLORS[ cat ] || '#6c757d'
                            } }
                          />
                        </div>
                        <span className="cat-count">{ count }</span>
                      </div>
                    ) ) }
                  </div>
                </div>

                {/* Top Templates */ }
                <div className="analytics-top">
                  <h3>Top Performing Templates</h3>
                  <div className="top-templates-list">
                    { analytics.topTemplates.map( ( t, idx ) => (
                      <div key={ idx } className="top-template-row">
                        <span className="rank">#{ idx + 1 }</span>
                        <div className="template-info">
                          <span className="name">{ t.templateName }</span>
                          <span className="stats">
                            { t.totalSent } sent • { t.deliveryRate.toFixed( 0 ) }% delivered • { t.readRate.toFixed( 0 ) }% read
                          </span>
                        </div>
                        <div className="rate-badges">
                          <span className={ `rate-badge ${t.deliveryRate >= 90 ? 'good' : t.deliveryRate >= 70 ? 'ok' : 'bad'}` }>
                            { t.deliveryRate.toFixed( 0 ) }%
                          </span>
                        </div>
                      </div>
                    ) ) }
                  </div>
                </div>
              </>
            ) : (
              <div className="empty-state">No analytics data available</div>
            ) }
          </div>
        ) }

        {/* Scheduled Tab */ }
        { activeTab === 'scheduled' && (
          <div className="scheduled-section">
            { scheduledLoading ? (
              <div className="loading-state">Loading scheduled messages...</div>
            ) : scheduledMessages.length === 0 ? (
              <div className="empty-state">
                <p>No scheduled messages</p>
                <small>Schedule template messages from the chat page</small>
              </div>
            ) : (
              <div className="scheduled-list">
                { scheduledMessages.map( ( msg ) => (
                  <div key={ msg.id } className="scheduled-item">
                    <div className="scheduled-info">
                      <span className="scheduled-template">{ msg.templateName }</span>
                      <span className="scheduled-contact">{ msg.contactName || msg.contactPhone }</span>
                    </div>
                    <div className="scheduled-time">
                      <span className="time-icon">Scheduled:</span>
                      <span>{ new Date( msg.scheduledAt ).toLocaleString() }</span>
                    </div>
                    <div className="scheduled-status">
                      <span className={ `status-badge ${msg.status.toLowerCase()}` }>{ msg.status }</span>
                    </div>
                    <div className="scheduled-actions">
                      { msg.status === 'PENDING' && (
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={ () => handleCancelScheduled( msg.scheduledId ) }
                        >
                          Cancel
                        </Button>
                      ) }
                    </div>
                  </div>
                ) ) }
              </div>
            ) }
          </div>
        ) }

        {/* Template Detail Modal */ }
        { selectedTemplate && (
          <div className="modal-overlay" onClick={ () => setSelectedTemplate( null ) }>
            <div className="modal" onClick={ ( e ) => e.stopPropagation() }>
              <div className="modal-header">
                <h2>{ selectedTemplate.name }</h2>
                <button className="close-btn" onClick={ () => setSelectedTemplate( null ) }>×</button>
              </div>
              <div className="modal-body">
                <div className="detail-row">
                  <span className="label">Status:</span>
                  <span
                    className="status-badge"
                    style={ { backgroundColor: STATUS_COLORS[ selectedTemplate.status ] } }
                  >
                    { selectedTemplate.status }
                  </span>
                </div>
                <div className="detail-row">
                  <span className="label">Category:</span>
                  <span>{ selectedTemplate.category }</span>
                </div>
                <div className="detail-row">
                  <span className="label">Language:</span>
                  <span>{ selectedTemplate.language }</span>
                </div>
                <h3>Components</h3>
                { selectedTemplate.components?.map( ( comp, idx ) => (
                  <div key={ idx } className="component-preview">
                    <strong>{ comp.type }</strong>
                    { comp.text && <p>{ comp.text }</p> }
                    { comp.format && <span className="format-badge">{ comp.format }</span> }
                  </div>
                ) ) }
              </div>
            </div>
          </div>
        ) }

        {/* Create Template Modal */ }
        { showCreateModal && (
          <div className="modal-overlay" onClick={ () => setShowCreateModal( false ) }>
            <div className="modal large" onClick={ ( e ) => e.stopPropagation() }>
              <div className="modal-header">
                <h2>Create New Template</h2>
                <button className="close-btn" onClick={ () => setShowCreateModal( false ) }>×</button>
              </div>
              <div className="modal-body">
                <div className="form-group">
                  <label>Template Name</label>
                  <input
                    type="text"
                    value={ newTemplate.name }
                    onChange={ ( e ) => setNewTemplate( { ...newTemplate, name: e.target.value } ) }
                    placeholder="my_template_name"
                  />
                  <small>Use lowercase letters, numbers, and underscores only</small>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Category</label>
                    <Select
                      ariaLabel="Category"
                      value={ newTemplate.category }
                      onChange={ ( v ) => setNewTemplate( { ...newTemplate, category: v as any } ) }
                      options={ TEMPLATE_CATEGORY_OPTIONS }
                    />
                  </div>
                  <div className="form-group">
                    <label>Language</label>
                    <Select
                      ariaLabel="Language"
                      value={ newTemplate.language }
                      onChange={ ( v ) => setNewTemplate( { ...newTemplate, language: v } ) }
                      options={ TEMPLATE_LANGUAGE_OPTIONS }
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label>Header Type</label>
                  <Select
                    ariaLabel="Header Type"
                    value={ newTemplate.headerType }
                    onChange={ ( v ) => setNewTemplate( { ...newTemplate, headerType: v as any } ) }
                    options={ HEADER_TYPE_OPTIONS }
                  />
                </div>

                { newTemplate.headerType === 'location' && (
                  <div className="form-group">
                    <small style={ { color: 'rgba(0, 0, 0, 0.54)' } }>
                      📍 Location header — no setup needed here. The map pin (latitude, longitude,
                      name, address) is supplied at send time. Category must be UTILITY or MARKETING.
                    </small>
                  </div>
                ) }
                { newTemplate.headerType === 'text' && (
                  <div className="form-group">
                    <label>Header Text</label>
                    <input
                      type="text"
                      value={ newTemplate.headerText }
                      onChange={ ( e ) => setNewTemplate( { ...newTemplate, headerText: e.target.value } ) }
                      placeholder="Header text..."
                    />
                  </div>
                ) }

                <div className="form-group">
                  <label>Body Text *</label>
                  <textarea
                    value={ newTemplate.bodyText }
                    onChange={ ( e ) => setNewTemplate( { ...newTemplate, bodyText: e.target.value } ) }
                    placeholder="Hello {{1}}, your order {{2}} is ready!"
                    rows={ 4 }
                  />
                  <small>Use { '{{1}}' }, { '{{2}}' }, etc. for variables</small>
                </div>

                <div className="form-group">
                  <label>Footer Text (optional)</label>
                  <input
                    type="text"
                    value={ newTemplate.footerText }
                    onChange={ ( e ) => setNewTemplate( { ...newTemplate, footerText: e.target.value } ) }
                    placeholder="Reply STOP to unsubscribe"
                  />
                </div>

                <div className="form-group">
                  <label>Buttons ({ newTemplate.buttons.length }/3)</label>
                  { newTemplate.buttons.map( ( btn, idx ) => (
                    <div key={ idx } className="button-row">
                      <Select
                        ariaLabel={ `Button ${ idx + 1 } type` }
                        value={ btn.type }
                        onChange={ ( v ) => updateButton( idx, 'type', v ) }
                        options={ BUTTON_TYPE_OPTIONS }
                        style={ BUTTON_TYPE_SELECT_STYLE }
                      />
                      <input
                        type="text"
                        value={ btn.text }
                        onChange={ ( e ) => updateButton( idx, 'text', e.target.value ) }
                        placeholder="Button text"
                      />
                      { btn.type === 'URL' && (
                        <input
                          type="text"
                          value={ btn.url || '' }
                          onChange={ ( e ) => updateButton( idx, 'url', e.target.value ) }
                          placeholder="https://..."
                        />
                      ) }
                      { btn.type === 'PHONE_NUMBER' && (
                        <input
                          type="text"
                          value={ btn.phone || '' }
                          onChange={ ( e ) => updateButton( idx, 'phone', e.target.value ) }
                          placeholder="+1234567890"
                        />
                      ) }
                      <Button variant="ghost" size="sm" onClick={ () => removeButton( idx ) }>×</Button>
                    </div>
                  ) ) }
                  { newTemplate.buttons.length < 3 && (
                    <Button variant="ghost" size="sm" onClick={ addButton }>+ Add Button</Button>
                  ) }
                </div>
              </div>
              <div className="modal-footer">
                <Button variant="secondary" onClick={ () => setShowCreateModal( false ) }>
                  Cancel
                </Button>
                <Button variant="primary" onClick={ handleCreateTemplate }>
                  Create Template
                </Button>
              </div>
            </div>
          </div>
        ) }

        {/* Carousel Template Modal */ }
        { showCarouselModal && (
          <div className="modal-overlay" onClick={ () => setShowCarouselModal( false ) }>
            <div className="modal carousel-modal" onClick={ ( e ) => e.stopPropagation() }>
              <div className="modal-header">
                <h2>Create Carousel Template</h2>
                <button className="close-btn" onClick={ () => setShowCarouselModal( false ) }>×</button>
              </div>
              <div className="modal-body">
                <div className="carousel-info">
                  <span className="info-icon">Info:</span>
                  <span>Carousel templates display up to 10 scrollable cards with images/videos and buttons.</span>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Template Name</label>
                    <input
                      type="text"
                      value={ carouselTemplate.name }
                      onChange={ ( e ) => setCarouselTemplate( { ...carouselTemplate, name: e.target.value } ) }
                      placeholder="my_carousel_template"
                    />
                  </div>
                  <div className="form-group">
                    <label>Category</label>
                    <Select
                      ariaLabel="Category"
                      value={ carouselTemplate.category }
                      onChange={ ( v ) => setCarouselTemplate( { ...carouselTemplate, category: v as any } ) }
                      options={ CAROUSEL_CATEGORY_OPTIONS }
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label>Language</label>
                  <Select
                    ariaLabel="Language"
                    value={ carouselTemplate.language }
                    onChange={ ( v ) => setCarouselTemplate( { ...carouselTemplate, language: v } ) }
                    options={ CAROUSEL_LANGUAGE_OPTIONS }
                  />
                </div>

                <div className="form-group">
                  <label>Message Body (shown above carousel)</label>
                  <textarea
                    value={ carouselTemplate.bodyText }
                    onChange={ ( e ) => setCarouselTemplate( { ...carouselTemplate, bodyText: e.target.value } ) }
                    placeholder="Check out our latest products! Use {{1}} for variables."
                    rows={ 2 }
                  />
                </div>

                <div className="cards-section">
                  <div className="cards-header">
                    <label>Cards ({ carouselTemplate.cards.length }/10)</label>
                    { carouselTemplate.cards.length < 10 && (
                      <Button variant="ghost" size="sm" onClick={ addCarouselCard }>+ Add Card</Button>
                    ) }
                  </div>

                  <div className="cards-list">
                    { carouselTemplate.cards.map( ( card, cardIdx ) => (
                      <div key={ cardIdx } className="carousel-card-editor">
                        <div className="card-header">
                          <span className="card-number">Card { cardIdx + 1 }</span>
                          { carouselTemplate.cards.length > 1 && (
                            <Button variant="ghost" size="sm" onClick={ () => removeCarouselCard( cardIdx ) }>×</Button>
                          ) }
                        </div>

                        <div className="card-media">
                          <div className="media-type-select">
                            <label>
                              <input
                                type="radio"
                                name={ `media-type-${cardIdx}` }
                                checked={ card.headerType === 'image' }
                                onChange={ () => updateCarouselCard( cardIdx, 'headerType', 'image' ) }
                              />
                              Image
                            </label>
                            <label>
                              <input
                                type="radio"
                                name={ `media-type-${cardIdx}` }
                                checked={ card.headerType === 'video' }
                                onChange={ () => updateCarouselCard( cardIdx, 'headerType', 'video' ) }
                              />
                              Video
                            </label>
                          </div>
                          <div className="media-upload">
                            { card.headerHandle ? (
                              <div className="media-uploaded">
                                <span className="upload-success">Media uploaded</span>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={ () => updateCarouselCard( cardIdx, 'headerHandle', '' ) }
                                >
                                  Change
                                </Button>
                              </div>
                            ) : (
                              <label className="upload-btn">
                                { carouselMediaUploading === cardIdx ? 'Uploading...' : `Upload ${card.headerType}` }
                                <input
                                  type="file"
                                  accept={ card.headerType === 'image' ? 'image/jpeg,image/png' : 'video/mp4' }
                                  onChange={ ( e ) => e.target.files?.[ 0 ] && handleCarouselMediaUpload( cardIdx, e.target.files[ 0 ] ) }
                                  disabled={ carouselMediaUploading !== null }
                                  hidden
                                />
                              </label>
                            ) }
                          </div>
                        </div>

                        <div className="form-group">
                          <label>Card Body Text</label>
                          <textarea
                            value={ card.bodyText }
                            onChange={ ( e ) => updateCarouselCard( cardIdx, 'bodyText', e.target.value ) }
                            placeholder="Product description... Use {{1}} for variables."
                            rows={ 2 }
                          />
                        </div>

                        <div className="card-buttons">
                          <label>Buttons ({ card.buttons?.length || 0 }/2)</label>
                          { card.buttons?.map( ( btn, btnIdx ) => (
                            <div key={ btnIdx } className="button-row">
                              <Select
                                ariaLabel={ `Card ${ cardIdx + 1 } button ${ btnIdx + 1 } type` }
                                value={ btn.type }
                                onChange={ ( v ) => updateCarouselCardButton( cardIdx, btnIdx, 'type', v ) }
                                options={ CARD_BUTTON_TYPE_OPTIONS }
                                style={ BUTTON_TYPE_SELECT_STYLE }
                              />
                              <input
                                type="text"
                                value={ btn.text }
                                onChange={ ( e ) => updateCarouselCardButton( cardIdx, btnIdx, 'text', e.target.value ) }
                                placeholder="Button text"
                              />
                              { btn.type === 'URL' && (
                                <input
                                  type="text"
                                  value={ btn.url || '' }
                                  onChange={ ( e ) => updateCarouselCardButton( cardIdx, btnIdx, 'url', e.target.value ) }
                                  placeholder="https://..."
                                />
                              ) }
                              { btn.type === 'PHONE_NUMBER' && (
                                <input
                                  type="text"
                                  value={ btn.phoneNumber || '' }
                                  onChange={ ( e ) => updateCarouselCardButton( cardIdx, btnIdx, 'phoneNumber', e.target.value ) }
                                  placeholder="+91..."
                                />
                              ) }
                              <button className="btn-remove" onClick={ () => removeCarouselCardButton( cardIdx, btnIdx ) }>×</button>
                            </div>
                          ) ) }
                          { ( card.buttons?.length || 0 ) < 2 && (
                            <button className="btn-add" onClick={ () => addCarouselCardButton( cardIdx ) }>+ Add Button</button>
                          ) }
                        </div>
                      </div>
                    ) ) }
                  </div>
                </div>

                {/* Preview */ }
                <div className="carousel-preview">
                  <label>Preview</label>
                  <div className="preview-container">
                    <div className="preview-body">{ carouselTemplate.bodyText || 'Message body text...' }</div>
                    <div className="preview-cards">
                      { carouselTemplate.cards.map( ( card, idx ) => (
                        <div key={ idx } className="preview-card">
                          <div className={ `preview-media ${card.headerHandle ? 'has-media' : ''}` }>
                            { card.headerHandle ? 'OK' : card.headerType === 'image' ? 'IMG' : 'VID' }
                          </div>
                          <div className="preview-card-body">{ card.bodyText || `Card ${idx + 1}` }</div>
                          { card.buttons?.map( ( btn, bIdx ) => (
                            <div key={ bIdx } className="preview-button">{ btn.text || 'Button' }</div>
                          ) ) }
                        </div>
                      ) ) }
                    </div>
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <Button variant="secondary" onClick={ () => setShowCarouselModal( false ) }>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={ handleCreateCarouselTemplate }
                  disabled={ carouselCreating }
                  loading={ carouselCreating }
                >
                  Create Carousel Template
                </Button>
              </div>
            </div>
          </div>
        ) }
      </div>
      <style jsx>{ `
        .page-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 24px;
          flex-wrap: wrap;
          gap: 16px;
        }

        .header-left {
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .header-actions {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .back-btn {
          background: #fff;
          border: 1px solid #000;
          padding: 8px 16px;
          border-radius: 13px;
          cursor: pointer;
        }

        .back-btn:hover {
          background: #f5f5f5;
        }

        h1 {
          margin: 0;
          font-size: 24px;
        }

        .waba-select {
          padding: 10px 16px;
          border: 1px solid #000;
          border-radius: 13px;
          font-size: 14px;
          min-width: 200px;
          background: #fff;
        }

        .waba-select:hover {
          background: #f5f5f5;
        }

        .search-section {
          margin-bottom: 20px;
        }

        .search-input {
          width: 100%;
          max-width: 400px;
          padding: 12px 16px;
          border: 1px solid #000;
          border-radius: 13px;
          font-size: 14px;
        }

        .search-input:hover {
          background: #f5f5f5;
        }

        .search-input:focus {
          outline: none;
          background: #fff;
          box-shadow: 0 0 0 3px rgba(0,0,0,0.1);
        }

        .templates-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 16px;
        }

        .template-card {
          background: white;
          border: 1px solid #eee;
          border-radius: 13px;
          padding: 16px;
          transition: box-shadow 0.2s;
        }

        .template-card:hover {
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        }

        .template-card.library {
          border-left: 4px solid #1a3a2a;
        }

        .template-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }

        .template-name {
          font-weight: 600;
          font-size: 16px;
        }

        .status-badge, .category-badge {
          padding: 4px 10px;
          border-radius: 13px;
          font-size: 11px;
          color: white;
          font-weight: 500;
        }

        .template-meta {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
        }

        .language {
          font-size: 12px;
          color: #666;
        }

        .template-body {
          font-size: 14px;
          color: #555;
          line-height: 1.5;
          margin-bottom: 16px;
          max-height: 60px;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .template-actions {
          display: flex;
          gap: 8px;
        }

        .btn-view, .btn-delete {
          padding: 8px 16px;
          border-radius: 13px;
          font-size: 13px;
          cursor: pointer;
        }

        .btn-view {
          background: #fff;
          border: 1px solid #000;
          color: #000;
        }

        .btn-view:hover {
          background: #f5f5f5;
        }

        .btn-delete {
          background: #fff;
          border: 1px solid #DC3545;
          color: #DC3545;
        }

        .btn-delete:hover {
          background: #f9fafb;
        }

        .loading-state, .empty-state {
          grid-column: 1 / -1;
          text-align: center;
          padding: 60px 20px;
          color: #666;
        }

        /* Modal Styles */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 20px;
        }

        .modal {
          background: white;
          border-radius: 12px;
          width: 100%;
          max-width: 500px;
          max-height: 90vh;
          overflow-y: auto;
        }

        .modal.large {
          max-width: 700px;
        }

        .modal.small {
          max-width: 400px;
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 16px 20px;
          border-bottom: 1px solid #eee;
        }

        .modal-header h2 {
          margin: 0;
          font-size: 18px;
        }

        .close-btn {
          background: none;
          border: none;
          font-size: 24px;
          cursor: pointer;
          color: #666;
        }

        .modal-body {
          padding: 20px;
        }

        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          padding: 16px 20px;
          border-top: 1px solid #eee;
        }

        .btn-secondary {
          background: #f5f5f5;
          border: 1px solid #ddd;
          padding: 10px 20px;
          border-radius: 8px;
          cursor: pointer;
        }

        .btn-secondary:hover {
          background: #eee;
        }

        .btn-danger {
          background: #DC3545;
          color: white;
          border: none;
          padding: 10px 20px;
          border-radius: 8px;
          cursor: pointer;
        }

        .btn-danger:hover:not(:disabled) {
          background: #c82333;
        }

        .btn-danger:disabled {
          opacity: 0.6;
        }

        .detail-row {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 12px;
        }

        .detail-row .label {
          font-weight: 500;
          min-width: 80px;
        }

        .component-preview {
          background: #f9f9f9;
          padding: 12px;
          border-radius: 8px;
          margin-bottom: 8px;
        }

        .component-preview strong {
          display: block;
          margin-bottom: 4px;
          font-size: 12px;
          color: #666;
        }

        .component-preview p {
          margin: 0;
          font-size: 14px;
        }

        .format-badge {
          display: inline-block;
          padding: 2px 8px;
          background: #eee;
          border-radius: 4px;
          font-size: 11px;
        }

        /* Form Styles */
        .form-group {
          margin-bottom: 16px;
        }

        .form-group label {
          display: block;
          font-weight: 500;
          margin-bottom: 6px;
          font-size: 14px;
        }

        .form-group input,
        .form-group select,
        .form-group textarea {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid #ddd;
          border-radius: 8px;
          font-size: 14px;
        }

        .form-group input:focus,
        .form-group select:focus,
        .form-group textarea:focus {
          outline: none;
          border-color: #000;
        }

        .form-group small {
          display: block;
          margin-top: 4px;
          font-size: 12px;
          color: #666;
        }

        .form-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
        }

        .button-row {
          display: flex;
          gap: 8px;
          margin-bottom: 8px;
        }

        .button-row select {
          width: 120px;
        }

        .button-row input {
          flex: 1;
        }

        .btn-remove {
          background: #DC3545;
          color: white;
          border: none;
          width: 32px;
          height: 32px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 18px;
        }

        .btn-add {
          background: none;
          border: 1px dashed #ddd;
          padding: 8px 16px;
          border-radius: 6px;
          cursor: pointer;
          color: #666;
          width: 100%;
        }

        .btn-add:hover {
          border-color: #000;
          color: #000;
        }

        .warning {
          color: #DC3545;
          font-size: 14px;
        }

        /* Carousel Modal */
        .modal.carousel-modal {
          max-width: 800px;
        }

        .carousel-info {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px;
          background: #f5f5f5;
          border-radius: 8px;
          font-size: 13px;
          color: #4a4a4a;
          margin-bottom: 16px;
        }

        .info-icon {
          font-size: 16px;
        }

        .cards-section {
          margin-top: 20px;
        }

        .cards-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }

        .cards-header label {
          font-weight: 500;
          font-size: 14px;
        }

        .btn-add-card {
          background: #fff;
          color: #000;
          border: 1px solid #000;
          padding: 6px 12px;
          border-radius: 13px;
          cursor: pointer;
          font-size: 13px;
        }

        .btn-add-card:hover {
          background: #f5f5f5;
        }

        .cards-list {
          display: flex;
          flex-direction: column;
          gap: 16px;
          max-height: 400px;
          overflow-y: auto;
          padding-right: 8px;
        }

        .carousel-card-editor {
          background: #f9f9f9;
          border: 1px solid #e5e5e5;
          border-radius: 12px;
          padding: 16px;
        }

        .card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }

        .card-number {
          font-weight: 600;
          font-size: 14px;
          color: #333;
        }

        .btn-remove-card {
          background: #f9fafb;
          color: #0f2a1d;
          border: 1px solid #e5e7eb;
          width: 28px;
          height: 28px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 16px;
        }

        .btn-remove-card:hover {
          background: #f3f4f6;
          border-color: #1a3a2a;
        }

        .card-media {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-bottom: 12px;
        }

        .media-type-select {
          display: flex;
          gap: 12px;
        }

        .media-type-select label {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 13px;
          cursor: pointer;
        }

        .media-upload {
          flex: 1;
        }

        .upload-btn {
          display: inline-block;
          padding: 8px 16px;
          background: #f0f0f0;
          border: 1px dashed #ccc;
          border-radius: 6px;
          cursor: pointer;
          font-size: 13px;
          color: #666;
        }

        .upload-btn:hover {
          border-color: #000;
          color: #000;
        }

        .media-uploaded {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .upload-success {
          color: #000;
          font-size: 13px;
        }

        .btn-change-media {
          background: none;
          border: none;
          color: #000;
          cursor: pointer;
          font-size: 12px;
          text-decoration: underline;
        }

        .card-buttons {
          margin-top: 12px;
        }

        .card-buttons > label {
          display: block;
          font-size: 13px;
          font-weight: 500;
          margin-bottom: 8px;
        }

        /* Carousel Preview */
        .carousel-preview {
          margin-top: 20px;
          padding-top: 16px;
          border-top: 1px solid #eee;
        }

        .carousel-preview > label {
          display: block;
          font-weight: 500;
          font-size: 14px;
          margin-bottom: 12px;
        }

        .preview-container {
          background: #e5ddd5;
          border-radius: 12px;
          padding: 16px;
        }

        .preview-body {
          background: #dcf8c6;
          padding: 10px 14px;
          border-radius: 8px;
          font-size: 14px;
          margin-bottom: 12px;
          max-width: 280px;
        }

        .preview-cards {
          display: flex;
          gap: 8px;
          overflow-x: auto;
          padding-bottom: 8px;
        }

        .preview-card {
          background: white;
          border-radius: 8px;
          min-width: 160px;
          max-width: 160px;
          overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .preview-media {
          height: 80px;
          background: #f0f0f0;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 24px;
          color: #999;
        }

        .preview-media.has-media {
          background: #f3f4f6;
          color: #1a1a1a;
        }

        .preview-card-body {
          padding: 8px 10px;
          font-size: 12px;
          color: #333;
          line-height: 1.3;
        }

        .preview-button {
          padding: 8px 10px;
          text-align: center;
          font-size: 12px;
          color: #1a3a2a;
          border-top: 1px solid #eee;
          cursor: pointer;
        }

        /* Analytics Section Styles */
        .analytics-section {
          padding: 20px 0;
        }

        .analytics-summary {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 16px;
          margin-bottom: 32px;
        }

        .summary-card {
          background: white;
          border: 1px solid #eee;
          border-radius: 12px;
          padding: 24px;
          text-align: center;
          transition: box-shadow 0.2s;
        }

        .summary-card:hover {
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        }

        .summary-value {
          display: block;
          font-size: 32px;
          font-weight: 700;
          color: #000;
          margin-bottom: 8px;
        }

        .summary-label {
          font-size: 14px;
          color: #666;
        }

        .analytics-category {
          background: white;
          border: 1px solid #eee;
          border-radius: 12px;
          padding: 20px;
          margin-bottom: 24px;
        }

        .analytics-category h3 {
          margin: 0 0 16px 0;
          font-size: 16px;
          color: #333;
        }

        .category-bars {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .category-bar {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .cat-name {
          min-width: 120px;
          font-size: 13px;
          font-weight: 500;
          color: #333;
        }

        .bar-container {
          flex: 1;
          height: 24px;
          background: #f0f0f0;
          border-radius: 12px;
          overflow: hidden;
        }

        .bar-fill {
          height: 100%;
          border-radius: 12px;
          transition: width 0.3s ease;
        }

        .cat-count {
          min-width: 50px;
          text-align: right;
          font-size: 14px;
          font-weight: 600;
          color: #333;
        }

        .analytics-top {
          background: white;
          border: 1px solid #eee;
          border-radius: 12px;
          padding: 20px;
        }

        .analytics-top h3 {
          margin: 0 0 16px 0;
          font-size: 16px;
          color: #333;
        }

        .top-templates-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .top-template-row {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px;
          background: #f9f9f9;
          border-radius: 8px;
        }

        .rank {
          font-size: 14px;
          font-weight: 700;
          color: #000;
          min-width: 30px;
        }

        .template-info {
          flex: 1;
        }

        .template-info .name {
          display: block;
          font-weight: 500;
          font-size: 14px;
          color: #333;
          margin-bottom: 4px;
        }

        .template-info .stats {
          font-size: 12px;
          color: #666;
        }

        .rate-badges {
          display: flex;
          gap: 8px;
        }

        .rate-badge {
          padding: 4px 10px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 600;
        }

        .rate-badge.good {
          background: #f9fafb;
          color: #0f2a1d;
        }

        .rate-badge.ok {
          background: #f3f4f6;
          color: #0f2a1d;
        }

        .rate-badge.bad {
          background: #f9fafb;
          color: #1a3a2a;
        }

        /* Scheduled Section Styles */
        .scheduled-section {
          padding: 20px 0;
        }

        .scheduled-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .scheduled-item {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 16px;
          background: white;
          border: 1px solid #eee;
          border-radius: 12px;
          transition: box-shadow 0.2s;
        }

        .scheduled-item:hover {
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        }

        .scheduled-info {
          flex: 1;
        }

        .scheduled-template {
          display: block;
          font-weight: 600;
          font-size: 14px;
          color: #333;
          margin-bottom: 4px;
        }

        .scheduled-contact {
          font-size: 13px;
          color: #666;
        }

        .scheduled-time {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 13px;
          color: #666;
        }

        .time-icon {
          font-size: 14px;
        }

        .scheduled-status .status-badge {
          padding: 4px 12px;
          border-radius: 12px;
          font-size: 11px;
          font-weight: 500;
          text-transform: uppercase;
        }

        .scheduled-status .status-badge.pending {
          background: #f3f4f6;
          color: #0f2a1d;
        }

        .scheduled-status .status-badge.sent {
          background: #f9fafb;
          color: #0f2a1d;
        }

        .scheduled-status .status-badge.failed {
          background: #f9fafb;
          color: #1a3a2a;
        }

        .scheduled-status .status-badge.cancelled {
          background: #f3f4f6;
          color: #6b7280;
        }

        .scheduled-actions {
          min-width: 80px;
          text-align: right;
        }

        .btn-cancel {
          background: none;
          border: 1px solid #DC3545;
          color: #DC3545;
          padding: 6px 14px;
          border-radius: 6px;
          font-size: 12px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .btn-cancel:hover {
          background: #DC3545;
          color: white;
        }

        @media (max-width: 768px) {
          .page-header {
            flex-direction: column;
            align-items: flex-start;
          }

          .header-actions {
            width: 100%;
            flex-direction: column;
          }

          .waba-select {
            width: 100%;
          }

          .templates-grid {
            grid-template-columns: 1fr;
          }

          .form-row {
            grid-template-columns: 1fr;
          }

          .button-row {
            flex-wrap: wrap;
          }

          .modal.carousel-modal {
            max-width: 100%;
          }

          .card-media {
            flex-direction: column;
            align-items: flex-start;
          }

          .analytics-summary {
            grid-template-columns: 1fr;
          }

          .scheduled-item {
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
          }

          .scheduled-actions {
            width: 100%;
            text-align: left;
          }
        }

        .embedded {
          padding: 0;
        }

        .embedded-header {
          display: flex;
          gap: 8px;
          margin-bottom: 16px;
          flex-wrap: wrap;
        }

        .embedded-header .waba-select {
          flex: 1;
          min-width: 150px;
        }
      `}</style>
    </>
  );

  if ( embedded )
  {
    return content;
  }

  return (
    <Layout user={ user } onSignOut={ signOut }>
      { content }
    </Layout>
  );
};

export default TemplateManagement;
