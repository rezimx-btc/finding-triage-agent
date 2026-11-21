# Login page echoes username unsafely

Target: https://example-shop.test/login

When I type a username containing HTML into the sign-in form and submit a
wrong password, the failure message shows my username back on the page and
the browser runs it as code. Tried `<img src=x onerror=alert(2)>` and the
alert popped. Same login error page, same username field, no output encoding.
