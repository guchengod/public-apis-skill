# API key acquisition

Read this reference only after selecting an API whose definition requires `apiKey` or `X-Mashape-Key` and credential resolution has failed.

## Decision flow

1. Run `api_client.py show <id>` and check the configured environment variable before acquiring a new key. Reuse an existing credential when available.
2. Prefer an equivalent no-key API when it satisfies the user's quality, freshness, and reliability requirements.
3. Open the selected provider's current official documentation. Verify the signup URL, free-tier status, authentication placement, required fields, rate limits, and whether email verification is sufficient. Do not infer these details from the catalog row.
4. Confirm that the current request explicitly authorizes obtaining and configuring a key. If it does not, identify the provider and ask for authorization immediately before creating the external account.
5. Inspect available capabilities. Mailbox automation is suitable only when the Agent can identify the connected user's email address, search/read verification mail, and safely follow a provider-owned verification link. A send-only mail tool is insufficient.

## Automatic email registration

When authorization and suitable mailbox capability are both present:

1. Register only a free account that requires no payment method, auto-renewing trial, phone number, identity document, organization invitation, custom domain, or CAPTCHA bypass.
2. Use the user's connected mailbox and the minimum required profile data. Never invent personal or organization information, create multiple accounts to evade quotas, or opt into marketing.
3. Prefer passwordless or email-link signup. If the provider requires a password, continue only when an approved password manager or secret store is available; otherwise ask the user to complete that step.
4. Find the verification message by provider domain and expected timestamp. Before following a link, verify that its destination belongs to the provider or its documented identity service.
5. Retrieve the key from the verified provider dashboard or message. Never print the full value in chat, command output, logs, commits, or dry-run results.
6. Store the secret through the environment or an available secret manager. Configure only the environment variable name in the API config through `auth.value_env`; never write the key into the skill or generated definitions.
7. Set the provider-specific `base_url`, `auth.location`, and `auth.name` from official documentation. Run a redacted dry-run before the first real request.
8. Report the provider, account email in masked form, configured environment variable name, free-tier/rate-limit facts, and dry-run result. Do not report the key itself.

Stop and ask the user if registration involves paid terms, a trial, legal or privacy ambiguity, phone/identity verification, CAPTCHA, an existing-account conflict, or any unsupported secret-storage step.

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
