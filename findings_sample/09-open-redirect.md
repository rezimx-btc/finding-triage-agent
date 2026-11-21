# Open redirect via next parameter after login

Target: https://example-shop.test/login?next=

After login the site redirects to whatever URL is in the `next` parameter
with no allowlist check. `?next=https://evil.example/phish` sends the user
to an attacker page. Useful for phishing, but no token or session is leaked
by the redirect itself. Open redirect, unvalidated next parameter.
