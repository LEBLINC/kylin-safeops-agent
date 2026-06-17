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

## P1 backlog: Replace placeholder Basic Auth with real SSO/LDAP

Current Basic Auth only validates role mapping (USER_ROLE_MAP), does not verify passwords.
Any request with a Basic Auth header passes through. Not acceptable for production.
Stage5 real LLM integration requires user identity authentication.
Recommended: OIDC/SAML/CAS 鈥?whichever has real service dependencies.
X is responsible for frontend whoami identity transition (endpoint already in place).

## Multi-machine Deployment NTP Sync Requirements

HMAC signature verification has a +/-300s replay prevention window. When proxy and app are deployed on separate machines, all nodes must have NTP clock synchronization.
- systemd timer: check drift every 5 minutes with chronyc tracking
- Production check: ntp/chrony configured + NTP port open + all node drift < 5s