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
  responseHeaders.location = {value: 'https://wecare.digital/'};
  return {statusCode: 302, statusDescription: 'Found', headers: responseHeaders};
}
