# otto-social-mcp

Thin multi-tenant MCP server (stdio) for Meta ORGANIC publishing — the one piece of Otto's
connection layer we build ourselves (ads = official Meta/Google MCPs, media = fal.ai MCP).

One process per client agent; tenant = env vars, so tokens stay in per-client secrets dirs.

## Tools
`fb_page_post` (text/link/photo, optional scheduling) · `ig_publish_image` · `ig_publish_carousel` ·
`ig_publish_reel` (async container polling) · `ig_publish_story` · `ig_publishing_limit` · `page_insights`

## Install
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Wire into a client's OpenClaw agent
```json5
mcp: { servers: { "otto-social": {
  command: "/path/otto-social-mcp/.venv/bin/python",
  args: ["/path/otto-social-mcp/server.py"],
  env: { META_ACCESS_TOKEN: "<per-client secret ref>",
         META_PAGE_ID: "<page id>", META_IG_USER_ID: "<ig business id>" }
}}}
```
Then `openclaw mcp doctor otto-social --probe`.

## Token requirements
Long-lived Page token with: `pages_manage_posts`, `pages_read_engagement`, `instagram_basic`,
`instagram_content_publish`. Works in dev mode for app admins/testers (pilot);
public clients need App Review + Business Verification (see research/mcp-connections-m2.md).

## Status
- [x] Scaffold + all 7 tools written (2026-09-27)
- [ ] Live test against Happy Garden page (blocked on: Meta app + page token from Max)
- [ ] Error-path hardening after first live run
