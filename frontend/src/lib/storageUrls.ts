/** Fix common LLM typo in Supabase public storage paths. */
export function normalizePublicStorageUrl(url: string | undefined | null): string {
  if (!url) return "";
  return url.replace(/\/storage\/v1\/component\/public\//gi, "/storage/v1/object/public/");
}

export function normalizePublicStorageUrls(urls: string[]): string[] {
  return urls.map((url) => normalizePublicStorageUrl(url)).filter(Boolean);
}
