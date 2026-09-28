# Otto M2 — Meta + Google connections via MCP: decisions
Date: 2026-09-27 | Source: web research pass (Maximus) | Status: approved direction, building

## Decisions (build vs reuse)

| Layer | Decision | Why |
|---|---|---|
| Meta ADS | **Reuse — official `mcp.facebook.com/ads`** (Meta Ads AI Connectors, open beta since 04.2026) | Meta-hosted remote MCP, per-user Meta Business OAuth, NO app review needed. 29 tools (campaign/adset/ad CRUD + insights), everything created lands PAUSED (safety). Free. |
| Meta ADS multi-tenant (later, M7 scale) | Fork/self-host **pipeboard-co/meta-ads-mcp** (BUSL 1.1, 42 tools, active) behind our OAuth broker | Official MCP binds interactive sessions; product-embedded automation at scale needs our own app + tokens. |
| Meta ORGANIC (FB posts, IG feed/reels/stories) | **Build thin custom MCP** (`otto-social-mcp`, ~6-8 tools) | No existing server is multi-tenant. Graph surface is small (container→publish). Crib from bmachek/social-mcp + IvanBBaev/instagram-mcp. |
| Google Ads | **Reuse — official `googleads/google-ads-mcp`** (Apache-2.0, active) | Big 2026 change: developer tokens retired 09.09.2026; access level lives on the Google Cloud project. Basic-access approval = form, days. Wrap per-client refresh tokens. |
| Images/Video | fal.ai hosted MCP + Leonardo fallback | See creative-and-competitor-stack.md |

## Meta auth reality (the critical path item)
Our own Meta app (type Business) needed for client OAuth. Scopes:
`ads_management, ads_read, business_management` (ads) · `pages_show_list, pages_read_engagement, pages_manage_posts` (FB) · `instagram_basic, instagram_content_publish` (IG).

**Dev mode = full functionality NOW** for users with a role on the app (admins/developers/testers). Pilot clients (Happy Garden = our own) work without any review.

**Advanced Access (public launch)** = App Review per permission + **Business Verification** (~20-day queues; `pages_manage_posts` + `instagram_content_publish` are most-rejected; screencast + justification each).

### Action sequence
1. ✅ Now: build `otto-social-mcp` + wire pilot in dev mode (Happy Garden assets as app admin/tester).
2. 🔜 Max: start **Business Verification** in Business Manager (legal docs) — the long pole; start early.
3. Later: one combined App Review with clean screencasts, before opening to paying clients.

## Per-client wiring (OpenClaw)
Each client agent gets `mcp.servers` entries: `meta-ads` (official remote, `openclaw mcp login`), `otto-social` (stdio, per-client token env from per-client secrets dir), `google-ads` (official, per-client refresh token), `fal` (FAL_KEY). Isolation per ARCHITECTURE.md: tokens never in shared workspace.
