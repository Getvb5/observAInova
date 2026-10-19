const FORWARDED_HEADERS = [
  "accept",
  "authorization",
  "content-type",
  "x-problem-token",
] as const;

export async function buildBackendRequest(
  incoming: Request,
  backendBaseUrl: string,
  path: string[],
): Promise<Request> {
  const sourceUrl = new URL(incoming.url);
  const target = new URL(
    `/api/v1/${path.map(encodeURIComponent).join("/")}${sourceUrl.search}`,
    backendBaseUrl.endsWith("/") ? backendBaseUrl : `${backendBaseUrl}/`,
  );
  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = incoming.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (headers.get("authorization")?.startsWith("Basic ")) {
    headers.delete("authorization");
  }
  const hasBody = !["GET", "HEAD"].includes(incoming.method);
  return new Request(target, {
    method: incoming.method,
    headers,
    body: hasBody ? await incoming.arrayBuffer() : undefined,
  });
}

export async function proxyBackend(
  incoming: Request,
  path: string[],
): Promise<Response> {
  const backendBaseUrl = process.env.API_INTERNAL_URL?.trim();
  if (!backendBaseUrl) {
    return Response.json(
      { detail: "Backend privado não configurado." },
      { status: 503 },
    );
  }
  const response = await fetch(
    await buildBackendRequest(incoming, backendBaseUrl, path),
    { cache: "no-store" },
  );
  const headers = new Headers();
  for (const name of ["content-type", "cache-control"]) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(response.body, {
    status: response.status,
    headers,
  });
}
