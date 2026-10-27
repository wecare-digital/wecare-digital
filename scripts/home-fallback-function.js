function handler(event) {
  var request = event.request || {};
  var headers = request.headers || {};
  var host = (headers.host && headers.host.value || '').toLowerCase();
  host = host.replace(/:\d+$/, '').replace(/\.$/, '');
  var responseHeaders = {
    'cache-control': {value: 'no-store'},
    'x-content-type-options': {value: 'nosniff'},
    'referrer-policy': {value: 'no-referrer'},
    'content-security-policy': {value: "default-src 'none'; frame-ancestors 'none'"}
  };
  // www is the historical canonical host, so its deep links are the ones search engines and old
  // backlinks still hold: move each to the same path on the apex, permanently. Every other
  // wildcard host is not a site of its own and still lands on the home page.
  if (host === 'www.wecare.digital') {
    var uri = (typeof request.uri === 'string' && request.uri.charAt(0) === '/') ? request.uri : '/';
    responseHeaders.location = {value: 'https://wecare.digital' + uri};
    return {statusCode: 301, statusDescription: 'Moved Permanently', headers: responseHeaders};
  }
  responseHeaders.location = {value: 'https://wecare.digital/'};
  return {statusCode: 302, statusDescription: 'Found', headers: responseHeaders};
}
