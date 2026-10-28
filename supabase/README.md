# Patchworks Supabase Setup & Database Migrations

This directory contains database migrations and setup instructions for configuring persistent user accounts, encrypted GitHub connections, and cloud-synced repair histories in **Patchworks**.

---

## 1. Supabase Project Setup

1. Create a project at [supabase.com](https://supabase.com).
2. Under **Project Settings -> API**, obtain:
   - `Project URL` (used for `SUPABASE_URL` and `VITE_SUPABASE_URL`)
   - `anon public key` (used for `SUPABASE_ANON_KEY` and `VITE_SUPABASE_ANON_KEY`)
   - `service_role secret` (used for `SUPABASE_SERVICE_ROLE_KEY` — **backend only, never commit or expose**)
3. Under **Authentication -> Providers -> GitHub**, enable GitHub OAuth (optional if using GitHub OAuth through Supabase Auth):
   - Add your GitHub Client ID & Secret.
   - Set Authorization callback URL to: `https://<project-ref>.supabase.co/auth/v1/callback`

---

## 2. Apply Database Migrations

Execute the migration script in [`migrations/001_auth_and_connections.sql`](migrations/001_auth_and_connections.sql):
- **Via Supabase Dashboard:** Navigate to **SQL Editor -> New Query**, paste the contents of `001_auth_and_connections.sql`, and click **Run**.
- **Via Supabase CLI:** Run `supabase db push` or `supabase migration up`.

This provisions:
- `public.github_connections`: Stores user-isolated GitHub connections with encrypted access tokens.
- `public.repair_sessions`: Stores persistent diagnosis records, patches, and verification histories.
- Strict **Row Level Security (RLS)** ensuring users cannot read or modify any other user's credentials or history.

---

## 3. Dedicated Token Encryption Key (`PATCHWORKS_ENCRYPTION_KEY`)

Tokens are encrypted at rest using Fernet authenticated symmetric encryption (AES-128-CBC + HMAC-SHA256).

### Key Generation
Generate a cryptographically secure 256-bit base64-encoded key:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Configure this value in your environment / Render Dashboard as:
`PATCHWORKS_ENCRYPTION_KEY=<generated-key>`

### Key Rotation Procedure
Patchworks supports non-destructive key rotation:
1. To rotate keys without invalidating existing encrypted credentials, configure multiple keys comma-separated in `PATCHWORKS_ENCRYPTION_KEY`:
   ```bash
   PATCHWORKS_ENCRYPTION_KEY="<NEW_KEY>,<OLD_KEY>"
   ```
2. The first key in the list is always used for **encryption** of new tokens.
3. The remaining keys are used as fallback keys for **decryption** of existing tokens.
4. When a user connects or their token is used, it can be re-encrypted under the new primary key.
