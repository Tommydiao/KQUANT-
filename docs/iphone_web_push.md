# iPhone Home Screen notifications

KQUANT uses standards-based Web Push, not iMessage. It requires iOS/iPadOS 16.4 or later and a private HTTPS KQUANT URL.

1. Install project dependencies and run `python -m kquant web-push-config`.
2. Put the generated values in the local `.env`. Never commit the private key.
3. Start KQUANT through the Cloudflare Access protected tunnel.
4. Open the HTTPS address in Safari on the iPhone and choose **Add to Home Screen**.
5. Open KQUANT from the Home Screen, sign in, then use **Settings > iPhone notifications > Enable here**.
6. Send a test notification from the same settings panel.

Routine alerts respect quiet hours and the daily limit. Risk and critical alerts bypass both. Push endpoints returning HTTP 404 or 410 are disabled automatically.
