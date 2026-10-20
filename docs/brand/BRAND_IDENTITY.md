# Agentree brand identity (implementation reference)

Source: *Agentree Master Brand Identity & UI/UX Design Brief v1.0* and logo files, provided by the
Product Owner on 2026-10-20. This file records what the product implements and the PO decisions
taken while applying it. The brief stays the design source of truth; do not change approved
messaging without PO approval.

## Approved messaging (do not rewrite)

| Item | Text |
|---|---|
| Brand name | Agentree (wordmark always lowercase: `agentree`) |
| Slogan | Your AI Team. Always On. |
| Category | AI Workforce Platform |
| Product description | Deploy specialized AI agents for sales, customer service, support, and business operations — all working together in one platform. |

Primary market: United States, US English by default. Tone: clear, confident, professional, warm;
no hype ("revolution", "10x", "fully autonomous"). No unverified security or compliance claims.

## PO decisions (2026-10-20)

- **Logo is final**: the wordmark "agen" + "tree" and the "a" monogram as supplied.
- **Blue comes from the logo** (`#0052FC`), not the brief's preliminary Cobalt `#3659CC`.
- **Font: Inter**, as recommended by the brief, one family for headings and body.

## Color tokens (`apps/web/src/app/globals.css`)

| Token | Hex | Role |
|---|---|---|
| `ink` / `brand-deep` | `#101B2B` | Midnight Ink: text, dark brand panels, theme color |
| `brand` | `#0052FC` | Logo blue: primary actions, active states, links, focus ring (5.8:1 on white) |
| `brand-hover` | `#0044D4` | Primary hover |
| `brand-soft` | `#E8EFFF` | Selected / hover tint, text selection |
| `accent` | `#16B8A6` | Intelligent Teal: restrained accent for agent connections only, never body text or success state |
| `paper` | `#F7F9FC` | Cloud White page background |
| `surface` | `#FFFFFF` | Cards, forms, dialogs |
| `ink-muted` | `#59697B` | Slate secondary text (5.6:1 on white) |
| `line` | `#E3EAF2` | Soft borders |
| `line-strong` | `#7C8B9D` | Input and control borders (3.4:1 on white, WCAG non-text contrast) |
| `danger`, `warn` (+ `-soft`) | | Semantic states; always paired with a label |

The widget loader (`apps/web/public/widget.js`) cannot read the stylesheet and mirrors `brand`.

## Logo assets (`apps/web/public/brand/`)

| File | Use |
|---|---|
| `agentree-logo-slogan.svg` | **App logo** (PO choice, 2026-10-20): wordmark with the slogan, on light backgrounds; use at 40 px tall or more |
| `agentree-logo-slogan-reversed.svg` | Same, on Midnight Ink (auth panel) |
| `agentree-wordmark.svg` | Wordmark on light backgrounds ("agen" ink, "tree" blue), for small placements |
| `agentree-wordmark-reversed.svg` | Wordmark on Midnight Ink ("agen" white) |
| `agentree-mark.svg` | "a" monogram on light backgrounds |
| `agentree-mark-reversed.svg` | Monogram on dark backgrounds |
| `apps/web/src/app/icon.svg`, `apple-icon.png` | Favicon / app icon: reversed monogram on a Midnight Ink tile |

`apps/web/src/app/favicon.ico` (16–256 px, for browsers that skip SVG icons) is the navy
favicon from the PO's *Agentree Brand Assets V1* package (2026-10-20). That package (raster PNG
exports only, no vector master) confirms the working colors: logo blue samples at `#0052FC`
(icons `#0059FA`) and the navy tile at `#101B2B`. It is kept by the PO, not in the repo (12 MB).

The SVGs were vectorized from the supplied raster artwork with colors snapped to the tokens above.
When designer-made vector masters arrive, replace these files in place (same names). The slogan is
part of the app logo lockup (PO decision); below ~40 px tall use the bare wordmark instead, since
the thin slogan stops being legible (e.g. the "Powered by" footer).

Rules from the brief: color split is always "agen" + "tree" (never only "ree"); no gradients on
the logo; no added leaf shapes, swooshes or network nodes.

## Typography

Inter variable (latin subset, committed as `apps/web/src/app/fonts/inter-latin-wght-normal.woff2`,
SIL OFL). No font is fetched from Google at build or run time. Arabic text falls back to the
system Arabic font.

## Not yet applied

- Branded HTML emails (emails are plain text today) — separate change.
- Marketing website, dashboard information architecture, agent status system and component library
  from the brief — future slices, each validated against the MVP scope.
