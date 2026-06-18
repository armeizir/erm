# Secret Rotation Notice

This workspace previously contained local databases, backup artifacts, and hardcoded development credentials. Treat any secret or password that may have existed in those artifacts as compromised.

Before production use:

- Rotate `SECRET_KEY`.
- Rotate LDAP bind or integration credentials if they were ever stored locally.
- Rotate AI API keys and email credentials.
- Reset any seeded local user passwords that were created before the secure seed command.
- Rebuild production deployment artifacts from a clean checkout.
