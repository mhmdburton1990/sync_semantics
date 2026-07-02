let DEV_TOKEN: string | null = null

export function setDevToken(token: string | null): void {
  DEV_TOKEN = token
}

export function getDevToken(): string | null {
  return DEV_TOKEN
}

export function authHeaders(): Record<string, string> {
  if (DEV_TOKEN) {
    return { 'X-Forwarded-Access-Token': DEV_TOKEN }
  }
  return {}
}
