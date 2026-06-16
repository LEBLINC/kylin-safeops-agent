# Reverse Proxy Sidecar

Signature-injecting sidecar. Strips client-forged X-Auth-* headers,
injects HMAC-SHA256 signed identity headers. SSE passthrough.

## Key Generation
`ash
python3 -c "import secrets; print(secrets.token_hex(32))"
`

## Startup
`ash
KYLIN_PROXY_AUTH_SECRET=xxx uvicorn proxy:app --host 0.0.0.0 --port 8080
`

## Shared Secret
Sidecar and app share KYLIN_PROXY_AUTH_SECRET on same machine. NTP sync required (+/-300s).

## Placeholder Auth
Basic Auth placeholder. Replace with Kylin SSO/LDAP before production.