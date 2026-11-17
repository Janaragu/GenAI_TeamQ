"""Einmalige Google-Anmeldung im Browser:  python -m mcp_server.auth

Öffnet den Browser, ihr meldet euch mit dem Testkonto an, danach liegt die
Anmeldung in token.json. Läuft bewusst getrennt vom MCP-Server, weil dessen
Ausgabe (stdout) für das MCP-Protokoll reserviert ist.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

from mcp_server.server import CREDENTIALS_FILE, SCOPES, TOKEN_FILE


def main():
    # credentials.json = OAuth-Client aus der Google Cloud Console
    if not CREDENTIALS_FILE.exists():
        raise SystemExit(f"{CREDENTIALS_FILE} fehlt (OAuth-Client aus der Google Cloud Console).")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)  # öffnet Browser, wartet auf Anmeldung
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print(f"Angemeldet, Token gespeichert in {TOKEN_FILE}.")


if __name__ == "__main__":
    main()
