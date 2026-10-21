# Elsewhere travel provider contract

The public Elsewhere assistant can render preview/demo recommendations when no live
travel provider is configured. Preview data is never bookable.

## Search request

A live bridge or endpoint receives:

```json
{
  "mode": "activities",
  "query": "Two adults in Jaipur on Saturday...",
  "preferences": ["Food + culture · 4 hours"]
}
```

Supported browser integrations:

- `window.ElsewhereTravelBridge.search(request)`
- `NEXT_PUBLIC_ELSEWHERE_SEARCH_ENDPOINT`

The endpoint must be HTTPS in production and should be backed by a trusted WECARE
service. Provider secrets must not be exposed to the browser.

## Search response

A live response may return up to eight results; the assistant displays the first
three ranked results.

```json
{
  "source": "api",
  "summary": "I found three options that fit your timing and budget.",
  "results": [
    {
      "id": "provider-result-id",
      "provider": "Provider name",
      "providerRef": "provider-reference",
      "offerId": "offer-reference",
      "title": "Old City food + architecture walk",
      "description": "A relaxed afternoon option...",
      "meta": ["3.5 h", "Pickup nearby"],
      "price": "₹1,850",
      "availability": "Available Saturday 2:00 PM",
      "cancellationSummary": "Free cancellation until 24 hours before",
      "quoteExpiresAt": "2026-10-21T12:30:00Z",
      "checkoutReady": true,
      "websiteUrl": "https://provider.example/checkout/...",
      "whatsappUrl": "https://wa.me/..."
    }
  ]
}
```

## Checkout gate

The browser keeps checkout disabled unless all of these are true:

1. the result came from a live API/MCP response, not demo data;
2. `checkoutReady === true`;
3. a provider identity exists (`providerRef` or `offerId`);
4. price, availability and cancellation summary are present;
5. `quoteExpiresAt` parses and is still in the future;
6. the selected checkout channel has a valid HTTPS URL.

`checkoutReady` is a server assertion, not a browser-side reprice. The provider
service remains responsible for revalidating the offer immediately before it
returns a checkout-ready response.

## WhatsApp checkout

A WhatsApp URL is treated only as a continuation target. Payment policy, approved
templates, order-details payloads and any provider-specific payment requirements
remain server-side concerns. The assistant must not construct payment links from
client-supplied price data.
