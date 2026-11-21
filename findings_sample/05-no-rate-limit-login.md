# No rate limiting on login attempts

Target: https://example-shop.test/login

I sent 200 failed login attempts for the same account in under a minute from
one IP and never got blocked, throttled, or CAPTCHA-challenged. An attacker
can brute-force passwords indefinitely. Login endpoint, no lockout, no
rate limit, no CAPTCHA after failures.
