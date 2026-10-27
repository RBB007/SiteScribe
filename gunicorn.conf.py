"""Gunicorn settings for the live app (see DEPLOY.md).

Gunicorn reads this file on its own when it is started from the repo root
(`gunicorn webapp.server:app`); elsewhere pass `-c /path/to/gunicorn.conf.py`.

timeout: an export renders every pinned plan page and re-encodes every
photo, which takes a minute or more on a big visit. Gunicorn's default is
30 s, after which it kills the worker mid-build and the phone sees
"Export failed: Bad Gateway".

threads: the app keeps one process (its visit.json lock is in-process), so
requests run on threads; a long export then does not stall every other
phone on site.
"""

workers = 1
threads = 4
timeout = 300
graceful_timeout = 60
