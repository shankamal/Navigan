import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import assert from "node:assert/strict";
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:3101/login");
  await page.getByRole("button", { name: "Sign in", exact: true }).waitFor();
  assert.equal(await page.getByLabel("Password", { exact: true }).getAttribute("type"), "password");
  await mkdir("test-results", { recursive: true });
  await page.screenshot({ path: "test-results/login-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Forgot password?" }).click();
  await page.getByRole("button", { name: "Send reset code" }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/reset-mobile.png", fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
  await page.getByRole("button", { name: "Back to sign-in" }).click();
  await page.getByRole("button", { name: "Sign in", exact: true }).waitFor();
  await page.screenshot({ path: "test-results/login-mobile.png", fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
  assert.deepEqual(errors, []);
  console.log("Login and password recovery render on desktop/mobile without browser errors.");
} finally {
  await browser.close();
}
