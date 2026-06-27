import { useState } from "react";
import { copyTextToClipboard } from "@/lib/clipboard";

export const useClipboard = () => {
  const [copied, setCopied] = useState(false);

  const copyToClipboard = async (text: string): Promise<boolean> => {
    const ok = await copyTextToClipboard(text);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
    return ok;
  };

  return { copied, copyToClipboard };
};
