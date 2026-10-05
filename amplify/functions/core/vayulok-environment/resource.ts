/**
 * VayuLok environmental gateway — WECARE.DIGITAL
 *
 * Server-side proxy for Google Weather API + Air Quality API. The public
 * NEXT_PUBLIC_GOOGLE_MAPS_KEY remains a browser-only Maps JavaScript credential.
 *
 * Lambda: wecare-vayulok-environment
 * Runtime: Python 3.12
 * Region: us-east-1
 * Route: POST /vayulok/environment
 *
 * First provision:
 *   python scripts/provision_vayulok_environment.py
 *
 * Server Google key:
 *   AWS Secrets Manager: wecare/google-maps-server
 *   API targets: Air Quality API + Weather API (plus the existing server-side
 *   address-capture targets owned by scripts/provision_maps_server_key.py).
 */
export const vayulokEnvironmentLambdaName = 'wecare-vayulok-environment';
export const vayulokEnvironmentRoute = 'POST /vayulok/environment';
