"""Einmalige Google-Anmeldung im Browser: python -m mcp_server.auth

Läuft bewusst getrennt vom MCP-Server, weil dessen stdout für das Protokoll reserviert ist.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

from mcp_server.google_api import CREDENTIALS_FILE, SCOPES, TOKEN_FILE


def main() -> None:
    if not CREDENTIALS_FILE.exists():
        raise SystemExit(f"{CREDENTIALS_FILE} fehlt (OAuth-Client aus der Google Cloud Console).")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print(f"Angemeldet, Token gespeichert in {TOKEN_FILE}.")


if __name__ == "__main__":
    main()
