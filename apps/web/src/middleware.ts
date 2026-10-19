import { NextRequest, NextResponse } from "next/server";

import { isPilotAuthorized } from "@/lib/pilot-access";

export function middleware(request: NextRequest): NextResponse {
  const username = process.env.PILOT_ACCESS_USERNAME?.trim() ?? "";
  const password = process.env.PILOT_ACCESS_PASSWORD ?? "";
  if (
    isPilotAuthorized(request.headers.get("authorization"), username, password)
  ) {
    return NextResponse.next();
  }
  return new NextResponse("Piloto privado ObservAInova", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="ObservAInova privado"' },
  });
}

export const config = {
  matcher: ["/((?!healthz|_next/static|_next/image|favicon.ico).*)"],
};
