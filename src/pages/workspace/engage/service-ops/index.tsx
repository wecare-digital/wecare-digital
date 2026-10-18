/**
 * Service Operations Hub — WECARE.DIGITAL
 *
 * One PageShell hub for the WhatsApp-Flow-driven service cluster (all /wa-business/*):
 * Orders (orchestrator) + Service Requests + Bookings + Drop Docs + Enterprise + Reviews + FAQ.
 * Mirrors the WhatsApp Settings hub pattern. Each tab embeds an existing page
 * (via its `embedded` prop) so those routes still work standalone too.
 */
import React, { Suspense } from 'react';
import { useRouter } from 'next/router';
import Layout from '../../../../components/Layout';
import SEO from '../../../../components/SEO';
import PageShell, { ShellTab } from '../../../../components/PageShell';

// FEAT-005: the embedded tab bodies moved OUT of src/pages/workspace/** into
// src/components/workspace/service/** so each stops being its own route. request/responses
// stays a real route and is still imported from the pages tree.
import OrdersPage from '../../../../components/workspace/service/Orders';
import AppointmentsPage from '../../../../components/workspace/service/Appointments';
import RxSlotsPage from '../../../../components/workspace/service/RxSlots';
import DocumentsPage from '../../../../components/workspace/service/Documents';
import EnterprisePage from '../../../../components/workspace/service/Enterprise';
import ReviewsPage from '../../../../components/workspace/service/Reviews';
import FaqPage from '../../../../components/workspace/service/Faq';
import SubmitRequestPage from '../../../../components/workspace/service/SubmitRequest';
import TrackRequestPage from '../../../../components/workspace/service/TrackRequest';
import AmendRequestPage from '../../../../components/workspace/service/AmendRequest';
import SecureFilesPage from '../../../../components/workspace/service/SecureFiles';
// Former Forms destinations — Service absorbs Forms. Each is `embedded`-ready so its
// api/client.ts calls are unchanged.
import FormResponsesPage from '../../../../components/workspace/service/FormResponses';
import CustomerServiceHubPage from '../../../../components/workspace/service/CustomerServiceHub';
import RequestResponsesPage from '../../../../components/workspace/service/RequestResponses';

interface PageProps { signOut?: () => void; user?: any; }

const TABS: ShellTab[] = [
    { id: 'orders', label: 'Orders' },
    { id: 'submit', label: 'Submit Request', divider: true },
    { id: 'track', label: 'Track Request' },
    { id: 'amend', label: 'Amend Request' },
    { id: 'responses', label: 'Responses', divider: true },
    { id: 'form-responses', label: 'Form responses' },
    { id: 'selfservice', label: 'Customer Service Hub' },
    { id: 'appointments', label: 'Appointments', divider: true },
    { id: 'rx-slots', label: 'RX Slots' },
    { id: 'documents', label: 'Drop Docs', divider: true },
    { id: 'secure-files', label: 'Secure Files' },
    { id: 'enterprise', label: 'Enterprise', divider: true },
    { id: 'reviews', label: 'Reviews' },
    { id: 'faq', label: 'FAQ' },
];

// FEAT-005: /workspace/engage/service-ops?tab=<id> deep-links open the matching tab.
function resolveDefaultTab ( raw: string | string[] | undefined ): string {
    const id = Array.isArray( raw ) ? raw[ 0 ] : raw;
    return id && TABS.some( ( t ) => t.id === id ) ? id : 'orders';
}

const ServiceOpsPage: React.FC<PageProps> = ( { signOut, user } ) => {
    const router = useRouter();
    const defaultTab = resolveDefaultTab( router.query.tab );
    return (
    <Layout user={ user } onSignOut={ signOut }>
        <SEO title="Service Operations | WECARE.DIGITAL" description="Orders, service requests, bookings, documents, enterprise, reviews & FAQ" noindex={ true } />
        <PageShell
            key={ defaultTab }
            title="Service Operations"
            subtitle="Orders, requests, bookings, documents & support — all WhatsApp-Flow driven"
            tabs={ TABS }
            defaultTab={ defaultTab }
        >
            { ( activeTab ) => (
                <Suspense fallback={ <div style={ { padding: 40, textAlign: 'center' } }>Loading…</div> }>
                    { activeTab === 'orders' && <OrdersPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'submit' && <SubmitRequestPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'track' && <TrackRequestPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'amend' && <AmendRequestPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'responses' && <RequestResponsesPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'form-responses' && <FormResponsesPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'selfservice' && <CustomerServiceHubPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'appointments' && <AppointmentsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'rx-slots' && <RxSlotsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'documents' && <DocumentsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'secure-files' && <SecureFilesPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'enterprise' && <EnterprisePage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'reviews' && <ReviewsPage signOut={ signOut } user={ user } embedded /> }
                    { activeTab === 'faq' && <FaqPage signOut={ signOut } user={ user } embedded /> }
                </Suspense>
            ) }
        </PageShell>
    </Layout>
    );
};

export default ServiceOpsPage;
