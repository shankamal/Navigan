import { forwardRequest } from "@/shared/api/proxy";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function handler(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  return forwardRequest(request, (await context.params).path);
}
export { handler as GET, handler as POST, handler as PUT };
