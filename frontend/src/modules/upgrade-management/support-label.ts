export function supportLabel(status?: string | null): string {
  if (!status) return "Unknown";
  const labels: Record<string, string> = {
    STANDARD_SUPPORT: "Standard",
    EXTENDED_SUPPORT: "Extended",
    UNSUPPORTED: "Out of support",
  };
  return (
    labels[status] ??
    status
      .toLowerCase()
      .replaceAll("_", " ")
      .replace(/^./, (letter) => letter.toUpperCase())
  );
}
