export function normalizePublicStorageUrl(url: string | undefined | null): string {
  return url ?? "";
}

export function normalizePublicStorageUrls(urls: string[]): string[] {
  return urls.map((url) => normalizePublicStorageUrl(url)).filter(Boolean);
}
