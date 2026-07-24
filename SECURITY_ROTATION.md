# Secret Rotation and Repository Hardening

This workspace has contained local/production database copies, backup artifacts,
and a legacy hardcoded Django secret. Treat credentials present in any historical
copy, archive, workstation backup, shared drive, or chat attachment as exposed.

## Secret storage design after hardening

- `AI API Key` and `SMTP Password` remain manageable from **Pengaturan Aplikasi**.
- The application stores only Fernet ciphertext in `AppSetting.ai_api_key` and
  `AppSetting.email_host_password`.
- Plaintext is decrypted only in memory at the moment an integration needs it.
- Admin forms are write-only for secret values: opening an existing setting never
  renders the saved plaintext back into the HTML form.
- The single master key `APP_ENCRYPTION_KEY` is stored only in the server
  environment/secret manager. Never store it in the database or repository.

> Losing `APP_ENCRYPTION_KEY` means existing encrypted AI/SMTP secrets cannot be
> recovered. Back it up in an approved secret manager, not in the source ZIP.

## Rotate before/with the next production deployment

1. **Django `SECRET_KEY`**
   - Generate a new production-only value.
   - Store it only in the server environment/secret manager.
   - Restart the application after updating it. Existing signed sessions may be invalidated.

2. **Master encryption key `APP_ENCRYPTION_KEY`**
   - Generate once with:
     `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - Configure it in production **before** running migration `risk.0065_encrypt_integration_secrets`.
   - Keep it stable; do not casually replace it after secrets have been encrypted.

3. **AI API keys**
   - Revoke/rotate every OpenAI, Gemini, or other provider key that was ever present
     in old database copies/backups.
   - Enter the replacement through **Pengaturan Aplikasi** after hardening is deployed.
   - The replacement will be stored encrypted in the database.

4. **SMTP credentials**
   - Rotate any SMTP/mailbox password that was ever present in old database copies/backups.
   - Enter the replacement through **Pengaturan Aplikasi** after hardening is deployed.
   - The replacement will be stored encrypted in the database.

5. **Other credentials**
   - Rotate DB passwords, LDAP bind credentials, seeded/local-user passwords, or any
     other secret if it ever appeared in `.env`, database backups, shell history,
     exported archives, or shared files.

## Repository rules

- Never commit or distribute `db.sqlite3`, `*.sqlite3`, database dumps, `backups/`,
  `.env`, virtual environments, or production exports.
- Build shareable source archives with `scripts/build_clean_zip.sh`.
- Run `scripts/security_preflight.sh` before pushing or sharing an archive.
- Deleting a secret from the current branch does **not** remove it from existing Git
  history or old archives. Rotate first; history cleanup is a separate operation.
