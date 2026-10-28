// Synthetic browser acceptance only: all platform API calls are intercepted.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1024 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const base = process.env.TEST_BASE_URL || "http://127.0.0.1:3101";
let created;
const writes = [];
try {
  const config = await page.request.get(base + "/api/runtime-config");
  assert.equal(config.status(), 200);
  const { oidcClientId, oidcAuthority } = await config.json();
  assert.ok(oidcClientId && oidcAuthority);
  await page.addInitScript(
    ({ oidcClientId, oidcAuthority }) => {
      const now = Math.floor(Date.now() / 1000);
      const claims = {
        sub: "customer-browser-test",
        username: "customer-browser-test",
        roles: JSON.stringify(["CLOUD_ENGINEER"]),
        customer_ids: "[]",
        platform_scope: "true",
        customer_create: "true",
        exp: now + 3600,
        iat: now,
        auth_time: now,
        iss: oidcAuthority,
      };
      const token = (use) =>
        [
          btoa(JSON.stringify({ alg: "RS256", typ: "JWT" })),
          btoa(
            JSON.stringify({
              ...claims,
              token_use: use,
              aud: oidcClientId,
              client_id: oidcClientId,
              name: "Asha Rao",
              email: "preview@example.com",
            }),
          ),
          "synthetic-test-signature",
        ].join(".");
      const prefix = "CognitoIdentityServiceProvider." + oidcClientId;
      sessionStorage.setItem(prefix + ".LastAuthUser", "customer-browser-test");
      sessionStorage.setItem(
        prefix + ".customer-browser-test.accessToken",
        token("access"),
      );
      sessionStorage.setItem(
        prefix + ".customer-browser-test.idToken",
        token("id"),
      );
      sessionStorage.setItem(prefix + ".customer-browser-test.clockDrift", "0");
    },
    { oidcClientId, oidcAuthority },
  );
  await page.route("**/api/platform/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api/platform",
      "",
    );
    if (path === "/access/me")
      return route.fulfill({
        json: {
          user: { userId: "customer-browser-test", displayName: "Asha Rao" },
          authorizationRevision: 1,
          privileges: [
            "customer.view",
            "customer.create",
            "customer.edit",
            "customer.submit",
          ],
          scopes: [{ type: "PLATFORM" }],
          source: "DYNAMIC",
        },
      });
    if (path === "/customers" && route.request().method() === "POST") {
      const input = route.request().postDataJSON();
      writes.push(input);
      assert.ok(route.request().headers()["idempotency-key"]);
      created = {
        ...input,
        customerId: "CUS-browser-preview",
        onboardingRequestId: "REQ-browser-preview",
        status: "DRAFT",
        version: 1,
        createdBy: "customer-browser-test",
        createdAt: "2026-10-28T10:00:00Z",
        updatedAt: "2026-10-28T10:00:00Z",
      };
      return route.fulfill({ status: 201, json: created });
    }
    if (path === "/customers/CUS-browser-preview" && created)
      return route.fulfill({ json: created });
    if (
      /^\/customers\/CUS-browser-preview\/(status-history|reviews|audit-log)$/.test(
        path,
      )
    )
      return route.fulfill({
        json: {
          items: [],
          pagination: {
            page: 0,
            pageSize: 10,
            totalElements: 0,
            totalPages: 0,
          },
        },
      });
    return route.fulfill({
      status: 404,
      json: {
        error: {
          code: "NOT_FOUND",
          message: "Missing browser fixture",
          details: {},
        },
      },
    });
  });
  await mkdir("test-results", { recursive: true });
  await page.goto(base + "/customers/new");
  await page
    .getByRole("heading", { name: "New customer", exact: true })
    .waitFor();
  await page
    .getByRole("button", { name: "Save as draft", exact: true })
    .click();
  await page.getByText("Enter the customer name.", { exact: true }).waitFor();
  assert.equal(writes.length, 0);
  await page.getByLabel(/Customer name/).fill("Northstar Logistics");
  await page
    .getByLabel(/Description/)
    .fill("Cloud platform modernisation for regional operations.");
  await page
    .getByRole("checkbox", { name: "AWS — Amazon Web Services" })
    .check();
  await page.getByRole("checkbox", { name: "Azure — Microsoft Azure" }).check();
  await page.getByRole("button", { name: "Add contact", exact: true }).click();
  await page.getByLabel(/Full name/).fill("Alex Morgan");
  await page.getByLabel(/^Email \(optional\)/).fill("invalid");
  await page
    .getByRole("button", { name: "Add to customer", exact: true })
    .click();
  await page
    .getByText("Enter a valid email address.", { exact: true })
    .waitFor();
  assert.equal(
    await page
      .getByRole("list", { name: "Added contacts", exact: true })
      .count(),
    0,
  );
  await page
    .getByLabel(/^Email \(optional\)/)
    .fill("alex.morgan@example.com");
  await page
    .getByRole("button", { name: "Add to customer", exact: true })
    .click();
  await page
    .getByRole("status")
    .filter({ hasText: "Complete for review." })
    .waitFor();
  await page
    .getByRole("button", { name: "Edit contact Alex Morgan", exact: true })
    .click();
  await page
    .getByLabel("Contact type", { exact: true })
    .selectOption("TECHNICAL");
  await page
    .getByRole("button", { name: "Update contact", exact: true })
    .click();
  await page
    .getByRole("list", { name: "Completion checklist", exact: true })
    .getByText(/Primary contact.*Pending/)
    .waitFor();
  await page
    .getByRole("button", { name: "Edit contact Alex Morgan", exact: true })
    .click();
  await page
    .getByLabel("Contact type", { exact: true })
    .selectOption("PRIMARY");
  await page
    .getByRole("button", { name: "Update contact", exact: true })
    .click();
  await page.screenshot({
    path: "test-results/customer-creation-desktop.png",
    fullPage: true,
  });
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("link", { name: "Cancel", exact: true }).click();
  assert.equal(new URL(page.url()).pathname, "/customers/new");
  await page
    .getByRole("button", { name: "Save as draft", exact: true })
    .click();
  await page.waitForURL("**/customers/CUS-browser-preview");
  assert.deepEqual(writes[0].cloudProviders, ["AWS", "AZURE"]);
  assert.deepEqual(writes[0].contacts, [
    {
      type: "PRIMARY",
      name: "Alex Morgan",
      email: "alex.morgan@example.com",
      phone: null,
    },
  ]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(base + "/customers/new");
  await page.getByRole("button", { name: "Add contact", exact: true }).click();
  await page.screenshot({
    path: "test-results/customer-creation-mobile-dialog.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  const sizes = await page
    .locator(".customer-save-bar .button")
    .evaluateAll((elements) =>
      elements.map((el) => el.getBoundingClientRect().height),
    );
  assert.ok(sizes.every((height) => height >= 44));
  await page.getByLabel(/Customer name/).fill("Mobile draft");
  await page
    .getByRole("button", { name: "Save as draft", exact: true })
    .click();
  await page.waitForURL("**/customers/CUS-browser-preview");
  assert.deepEqual(writes[1].contacts, []);
  assert.deepEqual(writes[1].cloudProviders, []);
  assert.deepEqual(errors, []);
  console.log(
    "Customer create/edit-contact/readiness/draft/unsaved/mobile browser acceptance passed.",
  );
} finally {
  await browser.close();
}
