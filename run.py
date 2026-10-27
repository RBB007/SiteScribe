"""Start the SiteScribe web app. Run from the repo root:  python run.py

Starting here, not from inside webapp/, is what lets the Flask routes
``import sitescribe`` without any path hacks. The server itself lives in
webapp/server.py (owner: tshoseints); this file only launches it.

Open http://localhost:5000 and enter the PIN (SITESCRIBE_PIN, default 2424).

Debug mode is off unless FLASK_DEBUG=1 is set. Keep it off whenever the app is
reachable from outside the machine (for example through a cloudflared tunnel):
the debug error pages show stack traces to anyone who hits them.
"""

from __future__ import annotations

import os

from webapp.server import app

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
