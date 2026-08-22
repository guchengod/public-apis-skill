# API key acquisition

Read this reference only after selecting an API whose definition requires `apiKey` or `X-Mashape-Key` and credential resolution has failed.

## Decision flow

1. Run `api_client.py show <id>` and check the configured environment variable before acquiring a new key. Reuse an existing credential when available.
2. Prefer an equivalent no-key API when it satisfies the user's quality, freshness, and reliability requirements.
3. Open the selected provider's current official documentation. Verify the signup URL, free-tier status, authentication placement, required fields, rate limits, and whether email verification is sufficient. Do not infer these details from the catalog row.
4. Inspect available capabilities. Mailbox automation is suitable only when the Agent can identify the connected user's email address, send mail when required, search/read verification mail, and safely follow a provider-owned verification link. A send-only mailbox tool is insufficient.
5. Treat registration as email-only when the provider requires only an email address plus a code, verification link, or API key delivered through that mailbox. A password is allowed only when an approved password manager or secret store can save it safely.

## Automatic email registration

When suitable mailbox capability is present and registration is email-only, register immediately without asking the user for confirmation:

1. Register only a free account. Do not continue through payment, an auto-renewing trial, phone or identity verification, CAPTCHA, or any requirement beyond the email-only flow.
2. Use the user's connected mailbox and the minimum required profile data. Never invent personal or organization information, create multiple accounts to evade quotas, or opt into marketing.
3. Prefer passwordless or email-link signup. If the provider requires a password, continue only when an approved password manager or secret store is available; otherwise ask the user to complete that step.
4. Find the verification message by provider domain and expected timestamp. Before following a link, verify that its destination belongs to the provider or its documented identity service.
5. Retrieve the key from the verified provider dashboard or message. Never print the full value in chat, command output, logs, commits, or dry-run results.
6. Store the secret through the environment or an available secret manager. Configure only the environment variable name in the API config through `auth.value_env`; never write the key into the skill or generated definitions.
7. Set the provider-specific `base_url`, `auth.location`, and `auth.name` from official documentation. Run a redacted dry-run before the first real request.
8. Report the provider, account email in masked form, configured environment variable name, free-tier/rate-limit facts, and dry-run result. Do not report the key itself.

Stop and hand control to the user if registration involves payment, an auto-renewing trial, phone verification, identity verification, CAPTCHA, or a password that cannot be saved securely.

## When mailbox capability is unavailable

Do not claim the Agent can register. Give the user:

- the verified official signup URL;
- required signup and verification steps;
- the expected key location in the provider dashboard;
- the deterministic credential environment variable from the interface definition;
- the required `auth.location` and `auth.name` when documented;
- a reminder to keep the key outside the repository.

After the user confirms the key is stored in the named environment variable or secret manager, continue with a redacted dry-run. Do not ask the user to paste the full key into ordinary chat when a secure channel is available.

## OAuth boundary

`OAuth` entries require provider authorization and consent, not merely an API key. Do not apply the email-only registration flow to OAuth. Follow the provider's official OAuth flow and request the necessary user consent at the point of authorization.
