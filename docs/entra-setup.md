# Entra ID App Registration — Setup Checklist

The app is fully built against environment variables; SSO starts working as
soon as the values below are set. Until then, local development uses the
password-based dev login (`DEV_LOGIN_ENABLED`, on by default when `DEBUG=true`).

## 1. Register the application

Entra admin center → **App registrations** → **New registration**:

- **Name:** `MD Opinion Alert`
- **Supported account types:** *Accounts in this organizational directory only*
  (single tenant)
- **Redirect URI:** *Web* → `https://<app>.onrender.com/oidc/callback/`
  - For local testing also add `http://localhost:8000/oidc/callback/`

## 2. Client secret

**Certificates & secrets** → **New client secret**. Record the secret *value*
immediately (it is shown once). Set a calendar reminder for its expiry.

## 3. Token claims

**Token configuration** → **Add optional claim** → *ID* token:

- `acct` — account status (0 = member, 1 = guest). **Required** for guest
  rejection; without it every login falls back to a Graph `/me` call and is
  rejected if that fails (the app fails closed).
- `email` — recommended; the app falls back to `preferred_username` (UPN)
  when absent.

## 4. Admin app role

**App roles** → **Create app role**:

- **Display name:** `Admin`
- **Allowed member types:** Users/Groups
- **Value:** `Admin` (must match the `ADMIN_APP_ROLE` env var)
- **Description:** MD Opinion Alert administrators

Then **Enterprise applications** → *MD Opinion Alert* → **Users and groups** →
assign the admin users (or an existing security group) to the `Admin` role.
Role changes take effect at the user's next sign-in.

## 5. API permissions

The defaults are sufficient: **Microsoft Graph → Delegated → `openid`,
`profile`, `email`, `User.Read`**. `User.Read` powers the defense-in-depth
Graph `userType` check when `acct` is missing. Grant **admin consent** for the
tenant if user consent is restricted.

## 6. Environment variables to set (Render → web service)

| Variable | Value |
|---|---|
| `OIDC_RP_CLIENT_ID` | Application (client) ID |
| `OIDC_RP_CLIENT_SECRET` | Client secret value from step 2 |
| `ENTRA_TENANT_ID` | Directory (tenant) ID |
| `ADMIN_APP_ROLE` | `Admin` (only if a different role value was chosen) |

The OIDC endpoints derive automatically from `ENTRA_TENANT_ID`; the
`OIDC_OP_*` variables only need setting to override them.

## 7. Verify

1. Sign in with a regular member account → lands on the dashboard, not staff.
2. Sign in with an account assigned the `Admin` role → `/admin/` accessible.
3. Sign in with a B2B guest account → login rejected.
