# Site ships outdated jQuery 1.12.4

Target: https://example-shop.test/

The homepage loads jQuery 1.12.4, released years ago. I found no reachable
vulnerability: the known XSS issues in that version need attacker-controlled
selectors that this site does not use. Old library version only, no exploit
path demonstrated, no affected sink.
