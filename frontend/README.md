# Navigan frontend

Modular Next.js / React / TypeScript application for Customer Management.

```bash
npm ci
cp .env.example .env.local
# Set NEXT_PUBLIC_OIDC_CLIENT_ID and register Cognito callback/logout URLs.
npm run dev
```

Open http://localhost:3000. See [frontend setup and architecture](../docs/frontend.md) for Cognito,
API integration, brand decisions, workflow behavior, testing, and production deployment.

```bash
npm run check
```

The UI uses the real API through a Next.js server proxy; there is no production mock data.
Environment, Cluster, and Application Management are planned-module placeholders.

For production container hosting, see [ECS Fargate deployment](../docs/frontend-ecs.md).
