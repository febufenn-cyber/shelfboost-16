# Shelfboost

> connect Shopify and bulk-generate SEO product titles, descriptions, and meta tags in your brand voice, with one-click publish back.

**Alternative to the product-shape pioneered by Hypotenuse AI (YC S20)** — rank #16 of 500 in the [YC-500 Fable 5 Venture Blueprint](https://github.com/) (score 7.1/10).

## Why this exists
Sellers have thousands of thin product pages; bulk SEO copy lifts organic traffic. The buildable wedge: just bulk product-copy and meta generation for one platform (shopify).

## MVP scope
- [ ] Shopify OAuth
- [ ] brand-voice profile
- [ ] bulk copy generation
- [ ] SEO meta/keywords
- [ ] one-click publish

## Architecture
`Workers+Supabase+Claude; Shopify app` — Cloudflare Workers + Hono API, Supabase (Postgres + RLS + Auth + pgvector), Claude API via Agent SDK (claude-fable-5 for agent reasoning, claude-haiku-4-5 for volume), wrangler deploys.

**Integrations:** Shopify Admin API; Claude; Stripe
**Data:** Product catalog, brand voice profile, generated copy
**Agent core:** Agent writes per-product copy tuned to keywords and brand tone.

## Business
| | |
|---|---|
| Monetization | SaaS $29-199/mo by catalog size |
| First customer | Shopify SMB sellers with large catalogs |
| GTM wedge | Shopify App Store listing plus 'ecommerce SEO' content; no paid ads. |
| Competition risk | High: many AI copy tools |
| Regulatory/trust risk | Low: marketing copy only |
| India angle | Cheap tier for Indian D2C brands and marketplace sellers. |
| Difficulty / build time | Low / 2-3 weeks |

## 30-day plan
- **W1:** core loop — Shopify OAuth + brand-voice profile
- **W2:** bulk copy generation + SEO meta/keywords + one-click publish + auth + billing
- **W3:** polish, instrument events, seed first users via: Shopify App Store listing plus 'ecommerce SEO' content; no paid ads.
- **W4:** launch + first revenue; kill/scale decision

---
*Built with Fable 5 (Claude Code). Blueprint row: inspired by Hypotenuse AI — "AI content platform generating product descriptions and copy for ecommerce brands."*