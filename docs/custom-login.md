# Navigan custom Cognito login

Navigan now presents its own email/username, password, recovery and MFA forms using the existing UI styles.
Cognito remains the identity provider. The frontend uses AWS Amplify Auth's USER_SRP_AUTH flow;
Amplify is a client library here, not an additional hosting service. ECS Fargate still hosts Next.js.
There is no redirect to Managed Login and no OAuth callback/token exchange in this flow.

## Configure the existing user pool

1. In `ap-south-1_PD9mv4fkd`, create a **public app client without a client secret**.
   Enable **ALLOW_USER_SRP_AUTH** and **ALLOW_REFRESH_TOKEN_AUTH** under authentication flows.
   Enable user-existence error prevention. Do not enable client credentials for browser sign-in.
2. Use your existing password policy, recovery contacts and MFA settings. Users need a verified recovery
   email or phone number for password resets. Account creation is administrator-managed; no public sign-up form is supplied.
3. Allow the app client to read normal profile attributes needed by your application. Never grant clients
   write access to custom authorization attributes. This implementation derives permissions only from
   administrator-managed Cognito group membership.
4. Authorization code grant, OAuth scopes, callback URLs and a Managed Login style are **not required**
   for this custom SRP flow. They may remain configured for other clients, but `NEXT_PUBLIC_OIDC_SCOPE`
   and `NEXT_PUBLIC_COGNITO_DOMAIN` no longer control Navigan authentication.

Changing the page does not make a confidential client usable in the browser. Use the new client ID,
never a client secret. Creating an app client in the same pool preserves its users. If you switch pools,
users and their group assignments must exist in the selected pool.

## Preserve API authorization

Cognito's direct SDK authentication does not add custom API scopes by default. The separate
`infrastructure/auth/template.yaml` stack creates a Python pre-token-generation Lambda and grants
only the existing user pool permission to invoke it. It does not recreate or modify the pool.
The Lambda adds `navigan/api` and the existing backend's trusted claims based on Cognito groups,
only for the specified new app client. It runs on sign-in and token refresh. Other clients pass through unchanged.

Access-token customization requires a compatible Cognito plan (Essentials or Plus for a new setup)
and a **V2_0** pre-token-generation trigger. Check the pool plan before enabling it; AWS pricing may change.
Do not remove API Gateway scope checks to work around a missing scope.

Before deploying, edit `scripts/frontend/config.env` and explicitly set all three matching values:

```bash
export COGNITO_USER_POOL_ID='ap-south-1_PD9mv4fkd'
export NEXT_PUBLIC_OIDC_AUTHORITY='https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_PD9mv4fkd'
export NEXT_PUBLIC_OIDC_CLIENT_ID='REPLACE_WITH_PUBLIC_CLIENT_ID_FROM_THIS_POOL'
```

`COGNITO_USER_POOL_ID` selects the pool allowed to invoke the token Lambda.
`NEXT_PUBLIC_OIDC_AUTHORITY` selects the frontend's authentication pool, and the client ID must
belong to that same pool. If `COGNITO_USER_POOL_ID` is omitted, the deployment script still defaults
to the **old pool, `ap-south-1_GtWAW9Owz`**. Set it explicitly for the current pool.
Pulling updated code does not update your ignored local `config.env`; add these lines manually
and preserve your existing VPC, subnet and ECS values.

From the repository root, reload the edited configuration and deploy:

```bash
source scripts/frontend/config.env
bash scripts/frontend/deploy-auth.sh
```

Optional variables: `AUTH_STACK_NAME` (default `navigan-auth`) and `NAVIGAN_API_SCOPE`
(default `navigan/api`). The scope must match the
actual API Gateway route requirement. The existing backend template defaults to `navigan/api`.

In Cognito, select pool **`ap-south-1_PD9mv4fkd`**, open **Extensions → Lambda triggers**, add the output Lambda as **Pre token generation**,
and select the event version that customizes access tokens (**V2_0**). If a pre-token trigger is
already attached, review and merge the logic with it before changing the association: a pool has one
pre-token-generation trigger and replacing it can affect other applications. The script intentionally
leaves that association to the administrator and does not reset any user-pool settings.

Update the existing API Gateway JWT authorizer audience to accept the **new app client ID**. Preserve
other clients that are still in use, and persist this change in the backend deployment parameters
(`JwtAudience`) so the next SAM deployment does not overwrite it. When switching pools, also update
the authorizer issuer and backend `JwtIssuer` parameter to the new `NEXT_PUBLIC_OIDC_AUTHORITY`.
Rebuild and redeploy the frontend after changing its authority or client ID, then sign in again.

### Administrator-managed group mapping

Create groups in Cognito and assign users deliberately. These names are exact and case-sensitive.
No user receives a role merely because they can sign in or request a role-named OAuth scope.

| Cognito group | Access-token effect |
|---|---|
| `NAVIGAN_CLOUD_ENGINEER` | `roles` includes `CLOUD_ENGINEER` |
| `NAVIGAN_PLATFORM_ARCHITECT` | `roles` includes `PLATFORM_ARCHITECT` |
| `NAVIGAN_CUSTOMER_CREATOR` | `customer_create=true`, only with the Cloud Engineer role |
| `NAVIGAN_PLATFORM_SCOPE` | `platform_scope=true`, only with a supported role; grants visibility across customers |
| `NAVIGAN_CUSTOMER_CUS-<actual-id>` | Adds the exact `CUS-<actual-id>` to `customer_ids`, only with a supported role |

Example: an onboarding engineer needs `NAVIGAN_CLOUD_ENGINEER` + `NAVIGAN_CUSTOMER_CREATOR`.
An architect reviewing all onboarding requests needs `NAVIGAN_PLATFORM_ARCHITECT` +
`NAVIGAN_PLATFORM_SCOPE`. Assign the latter only when organization-wide access is intended.
Users without a supported role receive no Navigan API scope and the API rejects their requests.
The previous `navigan/naviganadmin` style OAuth scopes do not automatically map to these roles.

Already-issued access tokens retain their permissions until expiry. Group changes affect the next
issued/refreshed token; choose an access-token lifetime appropriate for your revocation needs.

## Rebuild and deploy the frontend

Edit `scripts/frontend/config.env` without overwriting your VPC and ECS settings:

```bash
export COGNITO_USER_POOL_ID='ap-south-1_PD9mv4fkd'
export NEXT_PUBLIC_OIDC_AUTHORITY='https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_PD9mv4fkd'
export NEXT_PUBLIC_OIDC_CLIENT_ID='REPLACE_WITH_NEW_PUBLIC_CLIENT_ID'
export NEXT_PUBLIC_APP_URL='https://navigan.click'
```

`NEXT_PUBLIC_OIDC_AUTHORITY` is retained for compatibility and supplies the user pool ID; it is not
the `auth.ap-south-1.amazoncognito.com` managed login domain. Do not use the earlier mistaken
`NEXT_PUBLIC_OIDC_ISSUER` variable: the build uses `NEXT_PUBLIC_OIDC_AUTHORITY`.

```bash
source scripts/frontend/config.env
IMAGE_URI="$(bash scripts/frontend/build-and-push.sh)" && export IMAGE_URI
bash scripts/frontend/deploy.sh
```

Open `https://navigan.click/login` in a fresh tab. Old `/auth/callback` links now direct users to
start a new sign-in. Rebuild when the public app client ID or authority changes.

## Supported flows and sessions

- SRP username/password authentication, administrator-issued temporary passwords and required attributes.
- Forgot password and code-based password reset, followed by a new sign-in.
- SMS, email and authenticator (TOTP) verification; MFA selection; email and manual-key TOTP setup.
- Passwords and challenge answers are not logged. Tokens use tab-scoped sessionStorage, not localStorage.
- Amplify refreshes expired tokens. The provider refreshes on focus and every minute, clears cached
  customer data on identity changes/sign-out, and API calls use the access token.
- Logout clears the local session and attempts Cognito refresh-token revocation through Amplify.
  It does not clear unrelated Managed Login cookies or sign users out of other devices.
- Social/federated SSO, passkeys, custom Lambda challenges and self-registration are not supplied by
  this SRP form. Unsupported challenges produce an explicit administrator-contact message.

## Verification checklist

Test with a disposable user before releasing broadly: valid/invalid password, temporary-password
change, wrong/right MFA code, password reset, page reload, refresh after token expiry and logout.
Confirm the API accepts a user with assigned groups and denies one without groups. Confirm a scoped
user cannot see another customer's records. Never paste access tokens, passwords, MFA setup keys or
raw authentication request bodies into logs or support messages.

Automated tests cover form challenge handling and token permission boundaries. Live AWS sign-in
requires your new client ID, trigger association and test user; repository CI cannot verify your pool configuration.

References: [Cognito SDK authentication](https://docs.aws.amazon.com/cognito/latest/developerguide/authentication.html),
[Access token customization](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html),
[Amplify sign-in](https://docs.amplify.aws/react/build-a-backend/auth/connect-your-frontend/sign-in/).
