# KQUANT v2 Week 12 settings extraction

- Moved the active settings and iPhone Web Push workspace to `web/src/features/operations/SettingsPanel.tsx`.
- Preserved read-only data trust, taxonomy, rotation, prediction evidence, leadership evidence, and notification preference behavior.
- The panel receives the existing API fetcher and does not add account, broker, position, or order access.
- Browser smoke found the iPhone notification section after navigation to Settings; console errors were `0`.
- Frontend build passed. The release remains `NO_GO` because Shadow Observation is still `0/20` real trading days and the research OOS gate is not met.
