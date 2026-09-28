# Otto — Creative Gen (M3) + Competitor Research (M6) stack
Date: 2026-09-27 | Source: web research pass (Maximus)

## M3 Images — decision
**Primary: fal.ai hosted MCP** — `https://mcp.fal.ai/mcp` (streamable-HTTP, auth: FAL_KEY, pay-per-image ~$0.01–0.08). One endpoint, 1,000+ models (FLUX, Seedream, GPT Image, Recraft), schema+pricing lookup built in. Fits OpenClaw `mcp.servers` directly.
**Keep: Leonardo/GPT Image 2** — working key + prompt pattern already in `funnels/*/fire_ads.py`; best text-in-image for ad copy. Community MCP exists (superdwayne-leonardo-ai-mcp-server).
Fallbacks: OpenAI Images REST, `github.com/shinpr/mcp-image` (multi-provider), Replicate (official MCP).

## M3 Video — decision
**Same fal MCP endpoint** runs video models — no separate contracts:
- Kling 3.0 — volume reels, ~$0.10/sec (character-consistent, practitioner favorite over Runway)
- Veo 3.1 — hero ads with native audio, $0.05–0.40/sec
- Runway Gen-4.5 — premium control, REST only, no MCP
Cost anchor: 30-sec reel ≈ $1.50–$12. Pattern: Kling for volume, Veo for hero spots.

## M6 Competitor research — decision
- **ScrapeCreators** (scrapecreators.com) — unified REST for TikTok/IG/YT/FB/X posts+engagement+ad libraries. 100 free credits, $47/25k. Cheapest for high-frequency polling. ToS risk: medium.
- **Apify actors** (REST + official MCP at mcp.apify.com) — Meta Ad Library scraper (`apify/facebook-ads-scraper`), TikTok Creative Center top-ads. ~$1.30–1.70/1k records. Weekly creative sweeps. ToS risk: medium.
- **Official Meta Ad Library API** — free, zero risk, but commercial ads only in EU/DSA regions. Use where EU coverage suffices (our niche is EU → actually good fit).
Wiring: ScrapeCreators for frequent post/engagement polling; Apify for weekly ad-creative sweeps; official API for EU ad transparency.

## Integration note
All of the above enter client agents via OpenClaw `mcp.servers` config (streamable-http or stdio) — per-client keys in per-client secrets dirs, per ARCHITECTURE.md isolation rules.
