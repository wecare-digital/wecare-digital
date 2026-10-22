/**
 * SEO API client — authenticated Admin SEO tools only.
 *
 * Blog Studio and Blog Production were retired. The remaining frontend surfaces use this
 * helper for native blog management and site/page SEO operations.
 */
import { authFetch } from './client';
import { API_BASE } from '../config/constants';

export function seoToolsFetch ( path: string, init: RequestInit = {} ): Promise<Response> {
  const route = path.replace( /^\/+/, '' );
  return authFetch( `${API_BASE}/seo-tools/${route}`, init );
}
