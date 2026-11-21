# Error page leaks stack trace with file paths

Target: https://example-shop.test/checkout

Triggering an error on the checkout page returns a full stack trace in the
response, including internal file paths and library versions. No sensitive
data or credentials in the trace, but it helps an attacker map the stack.
Verbose error, internal paths disclosed.
