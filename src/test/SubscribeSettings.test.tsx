import React from 'react';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ getSystemConfigResult: vi.fn(), updateSystemConfig: vi.fn(), searchContactsResult: vi.fn() }));
const toast = vi.hoisted(() => ({ success:vi.fn(), error:vi.fn() }));
vi.mock('../api/client',()=>api);
vi.mock('../contexts/ToastContext',()=>({useToastContext:()=>toast}));
vi.mock('../components/workspace/customers/ConsentPanel',()=>({default:({contactId}:{contactId:string})=><div>Consent ledger for {contactId}</div>}));
import SubscribeSettings from '../components/workspace/whatsapp/subscribe-settings';

afterEach(cleanup);
beforeEach(()=>{ vi.clearAllMocks(); api.getSystemConfigResult.mockResolvedValue({ok:true,data:{config:null}}); api.updateSystemConfig.mockResolvedValue(true); api.searchContactsResult.mockResolvedValue({ok:true,data:[]}); });

describe('Subscribe workspace',()=>{
  it('saves separate new and returning copy without granting consent or enabling sends',async()=>{
    render(<SubscribeSettings/>);
    const save=await screen.findByRole('button',{name:'Save Subscribe messages'});
    await waitFor(()=>expect(save).toBeEnabled());
    fireEvent.change(screen.getByLabelText('newCustomer body'),{target:{value:'Hello new customer'}});
    fireEvent.change(screen.getByLabelText('returningCustomer confirmation'),{target:{value:'Your changes are saved'}});
    fireEvent.click(save);
    await waitFor(()=>expect(api.updateSystemConfig).toHaveBeenCalledOnce());
    const [key,value]=api.updateSystemConfig.mock.calls[0];
    expect(key).toBe('subscribe_messages_config');
    expect(value.newCustomer.body).toBe('Hello new customer');
    expect(value.returningCustomer.confirmation).toBe('Your changes are saved');
    expect(Object.keys(value).sort()).toEqual(['newCustomer','returningCustomer']);
    expect(screen.getByText(/Saving profile details does not change consent/)).toBeTruthy();
  });
  it('blocks overwrite when the initial settings read fails',async()=>{
    api.getSystemConfigResult.mockResolvedValue({ok:false,failure:{message:'Settings unavailable'}});
    render(<SubscribeSettings/>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Settings unavailable');
    expect(screen.getByRole('button',{name:'Save Subscribe messages'})).toBeDisabled();
    expect(api.updateSystemConfig).not.toHaveBeenCalled();
  });
  it('retains edits when save cannot be confirmed',async()=>{
    api.updateSystemConfig.mockResolvedValue(false);render(<SubscribeSettings/>);
    const save=screen.getByRole('button',{name:'Save Subscribe messages'});
    await waitFor(()=>expect(save).toBeEnabled());
    fireEvent.change(screen.getByLabelText('newCustomer body'),{target:{value:'Keep this draft'}});fireEvent.click(save);
    await waitFor(()=>expect(toast.error).toHaveBeenCalled());
    expect(screen.getByLabelText('newCustomer body')).toHaveValue('Keep this draft');
  });
  it('reports a failed customer search instead of claiming no matches',async()=>{
    api.searchContactsResult.mockResolvedValue({ok:false,failure:{message:'Customer search unavailable'}});
    render(<SubscribeSettings/>);
    fireEvent.change(screen.getByLabelText('Find customer'),{target:{value:'QA'}});
    fireEvent.click(screen.getByRole('button',{name:'Search customers'}));
    expect(await screen.findByRole('status')).toHaveTextContent('Customer search unavailable');
    expect(screen.queryByText('No matching customers found.')).toBeNull();
  });
  it('shows consent only for an explicitly selected customer and clears it on a new search',async()=>{
    api.searchContactsResult.mockResolvedValue({ok:true,data:[{contactId:'contact-a',name:'QA',phone:'+918100640044',customerDisplayId:'C-TEST'}]});
    render(<SubscribeSettings/>);
    fireEvent.change(screen.getByLabelText('Find customer'),{target:{value:'QA'}});
    fireEvent.click(screen.getByRole('button',{name:'Search customers'}));
    fireEvent.click(await screen.findByRole('button',{name:'QA · C-TEST'}));
    expect(screen.getByText('Consent ledger for contact-a')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Find customer'),{target:{value:'Other'}});
    expect(screen.queryByText('Consent ledger for contact-a')).toBeNull();
  });
});
