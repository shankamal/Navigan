/** Server-side release switch; this does not change authorization or preview access. */
export function isSourceFirstEnabled(): boolean {
  const configured = process.env.MIGRATION_SOURCE_FIRST_ENABLED;
  return (
    configured === "true" ||
    (process.env.NODE_ENV === "development" && configured !== "false")
  );
}
