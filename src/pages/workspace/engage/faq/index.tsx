/**
 * FAQ Management Page — [retired public path]/faq
 * CRUD for FAQ entries with categories, sort order, active/inactive toggle
 */
import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../../../components/Layout';
import SEO, { PAGE_SEO } from '../../../../components/SEO';
import Table from '../../../../components/ui/Table';
import Modal from '../../../../components/ui/Modal';
import Button from '../../../../components/ui/Button';
import EmptyState from '../../../../components/ui/EmptyState';
import { useToastContext } from '../../../../contexts/ToastContext';
import { useConfirm } from '../../../../contexts/ConfirmContext';
import * as api from '../../../../api/client';
import Select, { type SelectOption } from '../../../../components/ui/Select';

const CATEGORIES = [ 'General', 'Payments', 'Shipping', 'Returns', 'Account', 'Products', 'Technical', 'Other' ];

/* The option lists, hoisted. Same order, same values, same visible text as the rows they
   replaced, including the two '' placeholder rows the filters read as "no filter". */
const CATEGORY_OPTIONS: SelectOption[] = CATEGORIES.map( c => ( { value: c, label: c } ) );
const CATEGORY_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All Categories' },
  ...CATEGORY_OPTIONS,
];
const ACTIVE_FILTER_OPTIONS: SelectOption[] = [
  { value: '', label: 'All' },
  { value: 'true', label: 'Active' },
  { value: 'false', label: 'Inactive' },
];

/* LAYOUT ONLY - the two filters are flex children, and a native select sized itself to its
   widest option while the trigger shows the selected one. */
const FILTER_STYLE: React.CSSProperties = { width: 170 };

interface PageProps { signOut?: () => void; user?: any; embedded?: boolean; }

const FaqPage: React.FC<PageProps> = ( { signOut, user, embedded = false } ) => {
  const toast = useToastContext();
  const confirm = useConfirm();
  const [ faqs, setFaqs ] = useState<api.FaqEntry[]>( [] );
  const [ loading, setLoading ] = useState( true );
  const [ categoryFilter, setCategoryFilter ] = useState( '' );
  const [ activeFilter, setActiveFilter ] = useState<'' | 'true' | 'false'>( '' );
  const [ showModal, setShowModal ] = useState( false );
  const [ editing, setEditing ] = useState<api.FaqEntry | null>( null );
  const [ saving, setSaving ] = useState( false );
  const [ form, setForm ] = useState( { question: '', answer: '', category: 'General', sortOrder: 0, active: true } );

  const loadFaqs = useCallback( async () => {
    setLoading( true );
    try
    {
      const data = await api.listFaqs( {
        category: categoryFilter || undefined,
        active: activeFilter ? activeFilter === 'true' : undefined,
      } );
      setFaqs( ( data.faqs || [] ).sort( ( a, b ) => a.sortOrder - b.sortOrder ) );
    } catch
    {
      toast.error( 'Failed to load FAQs' );
    }
    setLoading( false );
  }, [ categoryFilter, activeFilter, toast ] );

  useEffect( () => { loadFaqs(); }, [ loadFaqs ] );

  const openCreate = () => {
    setEditing( null );
    setForm( { question: '', answer: '', category: 'General', sortOrder: faqs.length, active: true } );
    setShowModal( true );
  };

  const openEdit = ( faq: api.FaqEntry ) => {
    setEditing( faq );
    setForm( { question: faq.question, answer: faq.answer, category: faq.category, sortOrder: faq.sortOrder, active: faq.active } );
    setShowModal( true );
  };

  const handleSave = async () => {
    if ( !form.question.trim() || !form.answer.trim() ) { toast.error( 'Question and answer are required' ); return; }
    setSaving( true );
    if ( editing )
    {
      const ok = await api.updateFaq( editing.faqId, form );
      if ( ok ) { toast.success( 'FAQ updated' ); setShowModal( false ); loadFaqs(); }
      else toast.error( 'Failed to update FAQ' );
    } else
    {
      const created = await api.createFaq( form );
      if ( created ) { toast.success( 'FAQ created' ); setShowModal( false ); loadFaqs(); }
      else toast.error( 'Failed to create FAQ' );
    }
    setSaving( false );
  };

  const handleDelete = async ( faq: api.FaqEntry ) => {
    const ok = await confirm( { title: 'Delete FAQ', message: `Delete "${faq.question.slice( 0, 50 )}..."?`, confirmText: 'Delete', danger: true } );
    if ( !ok ) return;
    const deleted = await api.deleteFaq( faq.faqId );
    if ( deleted ) { toast.success( 'FAQ deleted' ); loadFaqs(); }
    else toast.error( 'Failed to delete FAQ' );
  };

  const handleToggleActive = async ( faq: api.FaqEntry ) => {
    const ok = await api.updateFaq( faq.faqId, { active: !faq.active } );
    if ( ok ) { toast.success( faq.active ? 'FAQ deactivated' : 'FAQ activated' ); loadFaqs(); }
    else toast.error( 'Failed to toggle FAQ' );
  };

  const columns = [
    { key: 'sortOrder', header: '#', width: '50px', render: ( f: api.FaqEntry ) => f.sortOrder },
    {
      key: 'question', header: 'Question', render: ( f: api.FaqEntry ) => (
        <div style={ { maxWidth: 400 } }>
          <div style={ { fontWeight: 500, fontSize: 14 } }>{ f.question }</div>
          <div style={ { fontSize: 12, color: '#6b7280', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const } }>{ f.answer }</div>
        </div>
      )
    },
    {
      key: 'category', header: 'Category', width: '110px', render: ( f: api.FaqEntry ) => (
        <span style={ { padding: '2px 8px', borderRadius: 9999, fontSize: 12, fontWeight: 500, background: '#f3f4f6', color: '#374151' } }>{ f.category }</span>
      )
    },
    {
      key: 'active', header: 'Active', width: '70px', render: ( f: api.FaqEntry ) => (
        <button onClick={ () => handleToggleActive( f ) } style={ { background: 'none', border: 'none', cursor: 'pointer', fontSize: 18 } } title={ f.active ? 'Active — click to deactivate' : 'Inactive — click to activate' }>
          { f.active ? '✅' : '⬜' }
        </button>
      )
    },
    {
      key: 'actions', header: '', width: '100px', render: ( f: api.FaqEntry ) => (
        <div style={ { display: 'flex', gap: 4 } }>
          <Button variant="ghost" size="sm" icon="edit" iconOnly ariaLabel="Edit" onClick={ () => openEdit( f ) } />
          <Button variant="ghost" size="sm" icon="delete" iconOnly ariaLabel="Delete" onClick={ () => handleDelete( f ) } />
        </div>
      )
    },
  ];

  const body = (
    <>
      { !embedded && <SEO { ...PAGE_SEO.faq } /> }
      <div style={ { padding: '24px 32px', maxWidth: 1200 } }>
        <div style={ { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 } }>
          <div>
            <h1 style={ { fontSize: 24, fontWeight: 700, color: '#1a3a2a', margin: 0 } }>FAQ Management</h1>
            <p style={ { fontSize: 14, color: '#6b7280', margin: '4px 0 0' } }>{ faqs.length } entries</p>
          </div>
          <Button variant="primary" icon="create" onClick={ openCreate }>Add FAQ</Button>
        </div>

        <div style={ { display: 'flex', gap: 12, marginBottom: 16 } }>
          <Select ariaLabel="Category" value={ categoryFilter }
            onChange={ v => setCategoryFilter( v ) }
            options={ CATEGORY_FILTER_OPTIONS } style={ FILTER_STYLE } />
          { /* The cast is preserved verbatim: activeFilter is '' | 'true' | 'false', and the
               option values are exactly those three strings. */ }
          <Select ariaLabel="Active" value={ activeFilter }
            onChange={ v => setActiveFilter( v as any ) }
            options={ ACTIVE_FILTER_OPTIONS } style={ FILTER_STYLE } />
        </div>

        { faqs.length === 0 && !loading ? (
          <EmptyState icon="default" title="No FAQs yet" description="Add your first FAQ entry" action={ { label: 'Add FAQ', onClick: openCreate } } />
        ) : (
          <Table columns={ columns } data={ faqs } keyField="faqId" loading={ loading } />
        ) }
      </div>

      <Modal isOpen={ showModal } onClose={ () => setShowModal( false ) } title={ editing ? 'Edit FAQ' : 'Add FAQ' } size="lg" footer={
        <><Button variant="secondary" onClick={ () => setShowModal( false ) }>Cancel</Button><Button variant="primary" loading={ saving } onClick={ handleSave }>{ editing ? 'Update' : 'Create' }</Button></>
      }>
        <div style={ { display: 'flex', flexDirection: 'column', gap: 14 } }>
          <label style={ { fontSize: 14 } }>Question *<input type="text" value={ form.question } onChange={ e => setForm( f => ( { ...f, question: e.target.value } ) ) } style={ inputStyle } /></label>
          <label style={ { fontSize: 14 } }>Answer *<textarea value={ form.answer } onChange={ e => setForm( f => ( { ...f, answer: e.target.value } ) ) } rows={ 5 } style={ { ...inputStyle, resize: 'vertical' } } /></label>
          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 } }>
            { /* SHAPE (a), design 5.2 - the wrapping <label> is gone and Select owns the pair. */ }
            <Select label="Category" value={ form.category }
              onChange={ v => setForm( f => ( { ...f, category: v } ) ) }
              options={ CATEGORY_OPTIONS } />
            <label style={ { fontSize: 14 } }>Sort Order<input type="number" value={ form.sortOrder } onChange={ e => setForm( f => ( { ...f, sortOrder: Number( e.target.value ) } ) ) } style={ inputStyle } /></label>
            <label style={ { fontSize: 14, display: 'flex', alignItems: 'center', gap: 8, marginTop: 22 } }>
              <input type="checkbox" checked={ form.active } onChange={ e => setForm( f => ( { ...f, active: e.target.checked } ) ) } style={ { accentColor: '#1a3a2a' } } /> Active
            </label>
          </div>
        </div>
      </Modal>
    </>
  );
  return embedded ? body : <Layout user={ user } onSignOut={ signOut }>{ body }</Layout>;
};

const inputStyle: React.CSSProperties = { display: 'block', width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 14, marginTop: 4 };
/* `selectStyle` went with the last native select in this file - it only ever skinned those. */

export default FaqPage;
