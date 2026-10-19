import { proxyBackend } from "@/lib/backend-proxy";

interface Context {
  params: Promise<{ path: string[] }>;
}

async function handle(request: Request, context: Context): Promise<Response> {
  const { path } = await context.params;
  return proxyBackend(request, path);
}

export const dynamic = "force-dynamic";
export { handle as DELETE, handle as GET, handle as POST, handle as PUT };
