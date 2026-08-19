# KQUANT v2 Week 12 research extraction

- Moved the active daily research opportunity desk and opportunity columns to `web/src/features/research/ResearchOpportunityDesk.tsx`.
- Preserved the existing data-only report, candidate groups, warning cards, manual symbol navigation, and read-only safety messaging.
- The component does not initiate model requests or change rule conclusions; it only renders the existing report payload.
- Browser smoke found the research desk and four opportunity columns; at 390px the page remained `scrollWidth=375` with zero console errors.
- Production build and frontend tests passed.
