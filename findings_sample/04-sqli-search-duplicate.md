# Search box lets me read the whole database

Target: https://example-shop.test/search?q=

Typing `' OR 1=1 --` into the search box lists every product instead of
erroring. With a UNION payload I could pull rows from the users table. The
q query string goes straight into the database query with no sanitizing or
parameters. Search endpoint SQL injection, full read access.
