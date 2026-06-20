"""gbrain · add a Gmail mailbox (OAuth user token).

Mints an OAuth token (with refresh token) for ONE mailbox and saves it to
the token dir the connector reads (GMAIL_TOKEN_DIR, default /opt/gbrain/tokens),
named <email>.json. No Workspace admin / domain-wide delegation needed.
Re-run once per mailbox to add more.

Prereq: a Desktop OAuth client downloaded to /opt/gbrain/client_secret.json
(Google Cloud → APIs & Services → Credentials → OAuth client ID → Desktop app),
and the mailbox added as a Test user on the OAuth consent screen.

Headless usage (this VPS):
  # 1) print the consent URL
  sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.connectors.gmail_auth
  #    → open the URL in a browser, sign in as the mailbox, Allow.
  #    → the browser lands on a 'localhost' page that fails to load; copy its
  #      full address-bar URL (contains ?code=...).
  # 2) exchange it (paste when prompted, OR pass as an argument):
  sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.connectors.gmail_auth "<pasted-localhost-url-or-code>"

Interactive shells can do both in one run: it prints the URL then waits for
you to paste the response.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse, parse_qs

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT = os.environ.get("GMAIL_CLIENT_SECRET", "/opt/gbrain/client_secret.json")
TOKEN_DIR = os.environ.get("GMAIL_TOKEN_DIR", "/opt/gbrain/tokens")
REDIRECT = "http://localhost"


def _flow():
    from google_auth_oauthlib.flow import InstalledAppFlow
    f = InstalledAppFlow.from_client_secrets_file(CLIENT, SCOPES, autogenerate_code_verifier=False)
    f.redirect_uri = REDIRECT
    return f


def _code_from(s: str) -> str:
    s = s.strip()
    if s.startswith("http"):
        return parse_qs(urlparse(s).query)["code"][0]
    return s


def auth_url() -> str:
    url, _ = _flow().authorization_url(access_type="offline", prompt="consent",
                                       include_granted_scopes="false")
    return url


def exchange(response: str) -> str:
    from googleapiclient.discovery import build
    flow = _flow()
    flow.fetch_token(code=_code_from(response))
    creds = flow.credentials
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    email = svc.users().getProfile(userId="me").execute()["emailAddress"]
    os.makedirs(TOKEN_DIR, exist_ok=True)
    path = os.path.join(TOKEN_DIR, f"{email}.json")
    with open(path, "w") as fh:
        fh.write(creds.to_json())
    os.chmod(path, 0o600)
    return f"{email} → {path}"


def main() -> None:
    if not os.path.exists(CLIENT):
        sys.exit(f"client secret not found at {CLIENT} (set GMAIL_CLIENT_SECRET)")
    if len(sys.argv) > 1:                       # arg = pasted response/code
        print("saved token:", exchange(sys.argv[1]))
        return
    print("\nOpen this URL in a browser signed in as the mailbox, approve, then\n"
          "copy the localhost URL it redirects to:\n\n" + auth_url() + "\n")
    try:
        resp = input("paste the localhost URL (or just the code) here: ")
    except EOFError:
        print("\n(no stdin) — re-run with the pasted URL as an argument.")
        return
    print("saved token:", exchange(resp))


if __name__ == "__main__":
    main()
