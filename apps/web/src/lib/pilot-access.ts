function decodeBasicCredentials(header: string): [string, string] | null {
  if (!header.startsWith("Basic ")) return null;
  try {
    const decoded = atob(header.slice(6));
    const separator = decoded.indexOf(":");
    if (separator < 0) return null;
    return [decoded.slice(0, separator), decoded.slice(separator + 1)];
  } catch {
    return null;
  }
}

export function isPilotAuthorized(
  authorization: string | null,
  configuredUsername: string,
  configuredPassword: string,
): boolean {
  if (!configuredUsername || !configuredPassword || !authorization) return false;
  const credentials = decodeBasicCredentials(authorization);
  return (
    credentials !== null &&
    credentials[0] === configuredUsername &&
    credentials[1] === configuredPassword
  );
}
