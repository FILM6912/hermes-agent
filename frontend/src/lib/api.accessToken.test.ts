import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const STORAGE_KEY = "hermes_webui_access_token";

describe("access token sessionStorage fallback", () => {
  beforeEach(() => {
    vi.resetModules();
    const store = new Map<string, string>();
    vi.stubGlobal("window", {
      __HERMES_CONFIG__: {},
      sessionStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => {
          store.set(key, value);
        },
        removeItem: (key: string) => {
          store.delete(key);
        },
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("persists access_token across module reload", async () => {
    const first = await import("@/lib/api");
    first.setAccessToken("signed.session.token");
    vi.resetModules();

    const second = await import("@/lib/api");
    expect(second.getAccessToken()).toBe("signed.session.token");
  });

  it("clears sessionStorage when token is reset", async () => {
    const api = await import("@/lib/api");
    api.setAccessToken("signed.session.token");
    api.setAccessToken("");
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(api.getAccessToken()).toBe("");
  });
});
