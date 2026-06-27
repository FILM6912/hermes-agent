import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  buildFullPageRedirectUrl,
  isFullPageRedirectPath,
  navigateToFullPagePath,
  resolvePostLoginPath,
  safeAppPath,
} from "./loginRedirect";

vi.mock("@/lib/api", () => ({
  getAccessToken: vi.fn(() => "test-session-token"),
}));

describe("loginRedirect", () => {
  const storage = new Map<string, string>();
  const assign = vi.fn();
  const replace = vi.fn();

  beforeEach(() => {
    storage.clear();
    assign.mockReset();
    replace.mockReset();
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      removeItem: (key: string) => {
        storage.delete(key);
      },
      clear: () => storage.clear(),
    });
    vi.stubGlobal("window", {
      location: {
        origin: "http://localhost:8787",
        assign,
        replace,
      },
      sessionStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        },
        removeItem: (key: string) => {
          storage.delete(key);
        },
        clear: () => storage.clear(),
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("detects FastAPI documentation paths as full-page redirects", () => {
    expect(isFullPageRedirectPath("/docs")).toBe(true);
    expect(isFullPageRedirectPath("/redoc")).toBe(true);
    expect(isFullPageRedirectPath("/openapi.json")).toBe(true);
    expect(isFullPageRedirectPath("/chat")).toBe(false);
    expect(isFullPageRedirectPath("/admin/users")).toBe(false);
  });

  it("preserves docs next target from hash login URL", () => {
    const target = resolvePostLoginPath({
      search: "",
      hash: "#/login?next=%2Fdocs",
    });
    expect(target).toBe("/docs");
    expect(isFullPageRedirectPath(target)).toBe(true);
  });

  it("appends access_token for server page redirects", () => {
    expect(buildFullPageRedirectUrl("/docs")).toBe("/docs?access_token=test-session-token");
  });

  it("blocks rapid repeat full-page redirects", () => {
    expect(navigateToFullPagePath("/docs")).toBe(true);
    expect(navigateToFullPagePath("/docs")).toBe(false);
    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith("/docs?access_token=test-session-token");
  });

  it("sanitizes unsafe next paths", () => {
    expect(safeAppPath("//evil.com")).toBe("/chat");
    expect(safeAppPath("/admin")).toBe("/admin");
  });
});
