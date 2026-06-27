"use client";

import * as React from "react";

import { Spinner } from "@/components/ui/spinner";
import { useAuthenticatedPreviewUrl } from "@/features/preview/hooks/useAuthenticatedPreviewUrl";

type AuthenticatedPreviewShellProps = {
  sourceUrl: string | null;
  loadingLabel?: string;
  errorLabel?: string;
  className?: string;
  children: (url: string) => React.ReactNode;
};

export function AuthenticatedPreviewShell({
  sourceUrl,
  loadingLabel = "Loading preview…",
  errorLabel = "Unable to preview file",
  className,
  children,
}: AuthenticatedPreviewShellProps) {
  const { url, state } = useAuthenticatedPreviewUrl(sourceUrl);

  if (!sourceUrl) {
    return null;
  }

  if (state === "loading") {
    return (
      <div
        className={
          className ??
          "flex h-full min-h-[12rem] items-center justify-center"
        }
      >
        <Spinner className="size-5 text-muted-foreground" />
        <span className="sr-only">{loadingLabel}</span>
      </div>
    );
  }

  if (!url || state === "error") {
    return (
      <div
        className={
          className ??
          "flex h-full min-h-[12rem] items-center justify-center px-6 text-center text-sm text-muted-foreground"
        }
      >
        {errorLabel}
      </div>
    );
  }

  return <>{children(url)}</>;
}
