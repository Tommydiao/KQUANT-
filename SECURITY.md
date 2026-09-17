# Security Policy

KQUANT handles market-data credentials and optional notification/provider secrets, so security reports are taken seriously. The project is research-only and must not gain broker, exchange, wallet, private-key or automated order-execution authority.

## Supported versions

Security fixes are maintained on the default branch and the latest tagged release. Older snapshots may not receive backports.

## Reporting a vulnerability

Please **do not disclose vulnerabilities in a public GitHub issue**.

Preferred path:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability** if GitHub private vulnerability reporting is enabled.
3. Include reproduction steps, affected paths/components, impact, and any suggested mitigation.

If private vulnerability reporting is not available, open a public issue containing only a request to establish a private reporting channel. Do not include exploit details, credentials, secret values, account information or sensitive logs in that issue.

## What to include

Helpful reports include:

- affected commit, branch or release;
- concise reproduction steps;
- expected versus actual behavior;
- impact and realistic attack preconditions;
- evidence that does not expose third-party secrets or personal data;
- a proposed fix, if you have one.

## Security boundaries

The following are intentional design constraints:

- market-data access is read-only;
- no broker/exchange account, holdings or order APIs;
- no wallet or private-key signing paths;
- secrets remain environment-only and must not be returned by APIs or logs;
- stale, forming, missing or untrusted evidence fails closed where it affects research gates;
- LLM output is advisory and cannot override deterministic EVAL/safety decisions;
- automated trading is outside the supported project scope.

A change that weakens one of these boundaries should be treated as security-sensitive even if it does not match a traditional vulnerability category.

## Scope examples

Reports are especially useful for authentication/session bypasses, secret leakage, unsafe provider integrations, cross-tenant or unintended data exposure, dependency vulnerabilities with a practical exploit path, prompt/tool paths that bypass deterministic gates, and any route that could create trade-execution authority.

## Disclosure

Please allow reasonable time for validation and remediation before public disclosure. Once a fix is available, the maintainer may publish a security advisory describing affected versions and mitigations.
