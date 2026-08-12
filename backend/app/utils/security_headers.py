"""Response headers that harden the API in production.

Deliberately three headers, not a framework. This is a JSON API behind a
separately-hosted SPA, so most of the classic header surface (HSTS, frame
options, permissions policy) is either the platform's job or belongs on the
frontend host, not here.

* **X-Content-Type-Options: nosniff** — stops a browser guessing a different
  content type than we declared. Relevant because uploaded document text is
  echoed back in JSON; sniffing could otherwise reinterpret a crafted payload.

* **Referrer-Policy: no-referrer** — API URLs carry conversation and document
  ids in the path. Without this, following a link out could leak those ids to
  a third party in the Referer header.

* **Content-Security-Policy** — applied only to non-documentation routes.
  A JSON response has no scripts, so `default-src 'none'` is exactly right and
  costs nothing. Swagger at /docs loads its bundle from a CDN and would break
  under that policy, so it is exempt; the trade-off is documented below.

HSTS is left to the hosting platform. Render and Vercel both terminate TLS and
set it themselves, and a wrong max-age set here would be hard to undo.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Paths that render HTML and load their own assets. A strict CSP would blank
# them, so they keep the other two headers but not the policy.
DOCUMENTATION_PATHS = ("/docs", "/redoc", "/openapi.json")

BASE_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"no-referrer",
}

# Nothing is allowed to load: a JSON API never legitimately needs to.
API_CSP = b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


class SecurityHeadersMiddleware:
    """Adds security headers to every response.

    Written as raw ASGI rather than BaseHTTPMiddleware so it adds no buffering
    and cannot interfere with the streaming upload path.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_documentation = path.startswith(DOCUMENTATION_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {name.lower() for name, _ in headers}

                for name, value in BASE_HEADERS.items():
                    if name not in existing:
                        headers.append((name, value))

                if not is_documentation and b"content-security-policy" not in existing:
                    headers.append((b"content-security-policy", API_CSP))

            await send(message)

        await self.app(scope, receive, send_with_headers)
