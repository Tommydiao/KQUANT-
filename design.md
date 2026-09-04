# KQUANT Unified Workspace

Locked design system for the Stocks and Crypto workbench. All market pages
share this system; market-specific data and rules remain isolated.

## System
- Genre - modern-minimal
- Macrostructure - Workbench
- Theme - custom: Graphite Signal
- Axes - graphite neutral / restrained blue / semantic status colours

## Tokens
`web/tokens.css` is the source of truth for colour, type, spacing, motion,
radius and focus tokens. Components must consume those tokens instead of
introducing local colours or spacing scales.

## Voice
- Primary - plain Chinese labels that describe the next decision.
- Secondary - source, time, coverage and status in compact metadata.
- Technical details - available under Settings and diagnostics only.

## Motion
- Motion-cut by default; only opacity and transform transitions are allowed.
- Reduced motion removes spatial transitions and all auto-play effects.

## Layout
- Shared task navigation with a persistent Stocks/Crypto market switch.
- Framed work surfaces use thin rules and restrained 4-8px radii.
- Dense tables are preferred to repeated metric cards.
- Research opens in a right drawer on desktop and a full-screen sheet on mobile.

## Constraints
- No gradients, decorative orbs, invented performance claims or marketing
  hero sections.
- The gateway is the only browser entry point for the unified experience.
- The two runtimes and databases remain separate and read-only.
