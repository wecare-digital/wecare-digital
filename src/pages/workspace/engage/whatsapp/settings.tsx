/**
 * Compatibility redirect for the retired WhatsApp settings hub.
 *
 * Every real capability now lives under Communications → Manage. Preserve old ?tab= deep links
 * because bookmarks, documentation and provider-review instructions may still point here.
 */
import { useEffect } from 'react';
import { useRouter } from 'next/router';

const TAB_TO_TOOL: Record<string, string> = {
  'ai-agent': 'ai-agent',
  'auto-response': 'auto-response',
  'bot-menu': 'bot-menu',
  scripts: 'scripts',
  campaign: 'campaign',
  'send-test': 'send-test',
  lists: 'lists',
  welcome: 'welcome',
  groups: 'groups',
  templates: 'templates',
  'template-builder': 'template-builder',
  flows: 'flows',
  'flow-publish': 'flow-publish',
  'flow-responses': 'flow-responses',
  'catalog-builder': 'catalog-builder',
  'ctwa-ads': 'ctwa-ads',
  'conversions-api': 'conversions-api',
  waba: 'waba',
  'embedded-signup': 'embedded-signup',
  'connected-accounts': 'connected-accounts',
  'my-account': 'my-account',
  profile: 'profile',
  bsuid: 'bsuid',
  migration: 'migration',
  'tech-partner': 'tech-partner',
  webhooks: 'webhooks',
  'cost-controls': 'cost-controls',
  calling: 'calling',
};

const WhatsAppSettingsCompatibilityRedirect = () => {
  const router = useRouter();

  useEffect( () => {
    const rawTab = Array.isArray( router.query.tab ) ? router.query.tab[ 0 ] : router.query.tab;
    if ( rawTab === 'inbox' ) {
      void router.replace( {
        pathname: '/workspace/communications',
        query: { view: 'inbox', channel: 'whatsapp' },
      } );
      return;
    }
    if ( rawTab === 'flow-hub' ) {
      void router.replace( {
        pathname: '/workspace/communications',
        query: { view: 'manage', section: 'flows' },
      } );
      return;
    }
    if ( rawTab === 'logs' ) {
      void router.replace( {
        pathname: '/workspace/communications',
        query: { view: 'manage', section: 'delivery', channel: 'whatsapp' },
      } );
      return;
    }

    const tool = rawTab ? TAB_TO_TOOL[ rawTab ] : undefined;
    void router.replace( {
      pathname: '/workspace/communications',
      query: tool
        ? { view: 'manage', section: 'whatsapp', tool }
        : { view: 'manage', section: 'whatsapp' },
    } );
  }, [ router ] );

  return null;
};

export default WhatsAppSettingsCompatibilityRedirect;
