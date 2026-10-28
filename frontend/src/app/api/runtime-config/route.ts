import { publicConfigFromEnvironment } from "@/shared/config/public-config";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const headers = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  };
  try {
    return Response.json(publicConfigFromEnvironment(process.env), { headers });
  } catch {
    return Response.json(
      { error: "Application settings are unavailable." },
      { status: 503, headers },
    );
  }
}
