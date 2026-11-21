# Reflected XSS in login error page

Target: https://example-shop.test/login

Steps:
1. Go to the login page and submit username `<script>alert(1)</script>` with any password.
2. The error page reflects the submitted username inside the HTML without encoding.
3. The script executes in the victim's browser.

Impact: an attacker can craft a login link that runs JavaScript in a victim's
session and steal the session cookie. Reflected input, no encoding, error page.
