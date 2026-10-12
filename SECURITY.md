# Security

Please report vulnerabilities privately through GitHub's "Report a vulnerability" button on this repository, not in a
public issue. Include what you found, how to reproduce it, and what an attacker could do with it.

The design notes in [docs/architecture.md](docs/architecture.md) cover the auth model, rate limits and how untrusted
URLs are fetched. If you run your own deployment:

- Generate `ADMIN_BOOTSTRAP_KEY`, `DASHBOARD_PASSWORD`, `DASHBOARD_SESSION_SECRET` and `DASHBOARD_PROXY_SECRET` as long
  random values, and rotate the bootstrap key out once you have created a permanent admin key.
- If your host's edge doesn't set `X-Real-IP`, set `CLIENT_IP_HEADER` to the header it does set, or to an empty string
  to rate limit on the socket address.
- Set a budget alert with your model provider. The spend caps here are computed from `model_prices`, which you have to
  keep current.
