import type { MouseEvent, RefObject } from "react";
import { CodeBlock } from "../components/CodeBlock";
import { TableWithExport } from "../components/TableWithExport";
import { normalizePublicStorageUrl } from "@/lib/storageUrls";

interface UseMarkdownComponentsProps {
  onPreviewRequest?: (content: string) => void;
  onViewImage: (url: string | string[]) => void;
  /** Chat messages scroll container — anchor/footnote jumps use this for reliable scrolling */
  scrollRootRef?: RefObject<HTMLElement | null>;
  /** Called when jumping to an in-page anchor — disables “stick to bottom” so auto-scroll won’t undo the jump */
  onAnchorNavigation?: () => void;
}

export const useMarkdownComponents = ({
  onPreviewRequest,
  onViewImage,
  scrollRootRef,
  onAnchorNavigation,
}: UseMarkdownComponentsProps) => {
  const isExternalHref = (href?: string) =>
    !!href && /^(https?:\/\/|mailto:|tel:)/i.test(href);
  const isAnchorHref = (href?: string) => !!href && href.startsWith("#");
  const isFileHref = (href?: string) =>
    !!href &&
    !isExternalHref(href) &&
    !isAnchorHref(href) &&
    /\.(?:docx?|xlsx?|pptx?|pdf|txt|csv|md|rtf|odt|ods|odp|zip|rar|7z|json|xml|html?|png|jpe?g|gif|webp|svg|mp3|mp4|wav|mov)$/i.test(href);
  const isReferenceId = (href?: string) =>
    !!href &&
    !isExternalHref(href) &&
    !isAnchorHref(href) &&
    !isFileHref(href) &&
    /^[a-zA-Z0-9_-]{6,}$/.test(href);

  const classNameToString = (className: unknown): string => {
    if (typeof className === "string") return className;
    if (Array.isArray(className)) return className.map((c) => String(c ?? "")).join(" ");
    return "";
  };

  const isFootnoteBackref = (
    href: string | undefined,
    props: Record<string, unknown>
  ) => {
    if ("data-footnote-backref" in props) return true;
    const cls = classNameToString(props["className"]);
    if (cls.includes("data-footnote-backref") || cls.includes("footnote-backref")) return true;
    const ariaLabel = typeof props["aria-label"] === "string" ? (props["aria-label"] as string) : "";
    if (/^back to (reference|footnote)/i.test(ariaLabel)) return true;
    if (!!href && /#(?:user-content-)?fnref[-:]/i.test(href)) return true;
    return false;
  };

  const findScrollableAncestor = (el: HTMLElement | null): HTMLElement | null => {
    let current: HTMLElement | null = el?.parentElement ?? null;
    while (current && current !== document.body && current !== document.documentElement) {
      const style = window.getComputedStyle(current);
      const overflowY = style.overflowY;
      const isScrollable =
        (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay") &&
        current.scrollHeight > current.clientHeight + 1;
      if (isScrollable) return current;
      current = current.parentElement;
    }
    return null;
  };

  const isFootnoteId = (id: string) => /^(?:user-content-)?fn-/i.test(id);

  /** Smallest element whose text should flash (footnote body, link, or block itself). */
  const pickHighlightTextContainer = (anchorEl: HTMLElement): HTMLElement => {
    const id = anchorEl.id || "";
    if (anchorEl.tagName === "LI" && isFootnoteId(id)) {
      const directP = anchorEl.querySelector(":scope > p");
      if (directP instanceof HTMLElement) return directP;
      const nestedP = anchorEl.querySelector("p");
      if (nestedP instanceof HTMLElement) return nestedP;
      const mainLink = Array.from(anchorEl.querySelectorAll("a")).find((a) => {
        if (a.hasAttribute("data-footnote-backref")) return false;
        const c = a.getAttribute("class") || "";
        return !c.includes("footnote-backref");
      });
      if (mainLink) return mainLink;
    }
    const scopeP = anchorEl.querySelector(":scope > p");
    if (scopeP instanceof HTMLElement) return scopeP;
    return anchorEl;
  };

  /** Wrap visible text in a temporary <mark> that blinks orange a few times, then unwrap. */
  const highlightAnchorText = (anchorEl: HTMLElement) => {
    const el = pickHighlightTextContainer(anchorEl);
    if (!el.textContent?.trim()) return;

    const unwrap = (mark: HTMLElement) => {
      const parent = mark.parentNode;
      if (!parent) return;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      parent.removeChild(mark);
    };

    try {
      const range = document.createRange();
      range.selectNodeContents(el);
      if (range.collapsed) return;

      const mark = document.createElement("mark");
      mark.setAttribute("data-anchor-flash", "");
      range.surroundContents(mark);

      const cleanup = () => unwrap(mark);
      mark.addEventListener("animationend", cleanup, { once: true });
      window.setTimeout(cleanup, 2600);
    } catch {
      const cls = "anchor-flash-fallback";
      el.classList.add(cls);
      window.setTimeout(() => el.classList.remove(cls), 2600);
    }
  };

  const findAnchorTarget = (rawId: string): HTMLElement | null => {
    let decoded = rawId;
    try {
      decoded = decodeURIComponent(rawId);
    } catch {
      // ignore decode failure
    }
    const candidates = Array.from(
      new Set(
        [rawId, decoded]
          .flatMap((id) => [id, id.replace(/^user-content-/, ""), `user-content-${id}`])
          .filter((id) => typeof id === "string" && id.length > 0)
      )
    );

    for (const id of candidates) {
      const byId = document.getElementById(id);
      if (byId) return byId;
    }

    for (const id of candidates) {
      try {
        const escaped =
          typeof (window as any).CSS?.escape === "function"
            ? (window as any).CSS.escape(id)
            : id.replace(/(["\\])/g, "\\$1");
        const byQuery = document.querySelector(`[id="${escaped}"]`) as HTMLElement | null;
        if (byQuery) return byQuery;
      } catch {
        // ignore selector errors
      }
    }
    return null;
  };

  const scrollWithinRoot = (root: HTMLElement, el: HTMLElement, padding = 24) => {
    const rootRect = root.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const nextTop = root.scrollTop + (elRect.top - rootRect.top) - padding;
    try {
      root.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
    } catch {
      root.scrollTop = Math.max(0, nextTop);
    }
  };

  const scrollToAnchor = (rawId: string) => {
    const target = findAnchorTarget(rawId);
    if (!target) {
      if (typeof window !== "undefined" && (window as any).console) {
        console.warn("[scrollToAnchor] target not found for id:", rawId);
      }
      return false;
    }

    onAnchorNavigation?.();

    const footnoteSection =
      (target.closest("section.footnotes, section.footnote, section[data-footnotes]") as HTMLElement | null) ??
      null;
    const scrollTarget = footnoteSection ?? target;

    const doScroll = () => {
      const root = scrollRootRef?.current;
      if (root && root.contains(scrollTarget)) {
        scrollWithinRoot(root, scrollTarget, 24);
        return;
      }

      try {
        scrollTarget.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch {
        scrollTarget.scrollIntoView();
      }

      const scrollable = findScrollableAncestor(scrollTarget);
      if (scrollable) {
        const targetRect = scrollTarget.getBoundingClientRect();
        const containerRect = scrollable.getBoundingClientRect();
        const currentOffset = targetRect.top - containerRect.top;
        if (currentOffset < 0 || currentOffset > containerRect.height - 40) {
          const nextTop =
            scrollable.scrollTop + currentOffset - containerRect.height / 2 + targetRect.height / 2;
          try {
            scrollable.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
          } catch {
            scrollable.scrollTop = Math.max(0, nextTop);
          }
        }
      }
    };

    doScroll();
    window.requestAnimationFrame(() => {
      doScroll();
    });
    highlightAnchorText(target);
    return true;
  };

  const findFootnoteUrl = (target: HTMLElement): string | null => {
    const links = Array.from(target.querySelectorAll("a")) as HTMLAnchorElement[];
    let textContent = target.textContent || "";
    for (const link of links) {
      if (link.hasAttribute("data-footnote-backref")) {
        textContent = textContent.replace(link.textContent || "", "");
        continue;
      }
      const cls = link.getAttribute("class") || "";
      if (cls.includes("footnote-backref")) {
        textContent = textContent.replace(link.textContent || "", "");
        continue;
      }
    }

    const trimmed = textContent.trim();
    for (const link of links) {
      if (link.hasAttribute("data-footnote-backref")) continue;
      const cls = link.getAttribute("class") || "";
      if (cls.includes("footnote-backref")) continue;
      const raw = link.getAttribute("href") || "";
      if (!raw || raw.startsWith("#")) continue;
      if (!isExternalHref(raw)) continue;

      const linkText = (link.textContent || "").trim();
      if (linkText === trimmed || raw === trimmed) {
        return raw;
      }
    }

    if (/^(https?:\/\/|mailto:|tel:)\S+$/i.test(trimmed)) {
      return trimmed;
    }

    return null;
  };

  const handleLinkClick = (event: MouseEvent<HTMLAnchorElement>, href?: string) => {
    if (!href) return;

    if (isAnchorHref(href)) {
      event.preventDefault();
      const targetId = href.slice(1);
      if (!targetId) return;

      if (isFootnoteId(targetId)) {
        const target = findAnchorTarget(targetId);
        if (target) {
          const url = findFootnoteUrl(target);
          if (url) {
            window.open(url, "_blank", "noopener,noreferrer");
            return;
          }
        }
      }

      scrollToAnchor(targetId);
      return;
    }

    if (isFileHref(href) || isReferenceId(href)) {
      event.preventDefault();
      if (onPreviewRequest) {
        onPreviewRequest(href);
      } else {
        window.open(href, "_blank", "noopener,noreferrer");
      }
      return;
    }
  };

  return {
    // Paragraphs
    p: ({ children }: any) => (
      <p className="mb-3 last:mb-0 leading-relaxed text-zinc-700 dark:text-zinc-300">
        {children}
      </p>
    ),

    // Bold & Italics
    strong: ({ children }: any) => (
      <strong className="font-bold">
        {children}
      </strong>
    ),
    em: ({ children }: any) => (
      <em className="italic text-zinc-800 dark:text-zinc-200">{children}</em>
    ),

    // Headings
    h1: ({ children }: any) => (
      <h1 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-4 mt-6 pb-2 border-b border-zinc-200 dark:border-zinc-800">
        {children}
      </h1>
    ),
    h2: ({ children, id }: any) => {
      const idStr = typeof id === "string" ? id : "";
      if (idStr === "footnote-label" || idStr === "user-content-footnote-label") {
        return null;
      }
      return (
        <h2 id={idStr || undefined} className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-3 mt-5">
          {children}
        </h2>
      );
    },
    h3: ({ children }: any) => (
      <h3 className="text-lg font-medium text-zinc-900 dark:text-zinc-100 mb-2 mt-4">
        {children}
      </h3>
    ),

    // Lists
    ul: ({ children, className, id, ...props }: any) => (
      <ul
        id={typeof id === "string" ? id : undefined}
        className={["list-disc pl-6 mb-4 space-y-1 text-zinc-700 dark:text-zinc-300 marker:text-zinc-400 dark:marker:text-zinc-500", className]
          .filter(Boolean)
          .join(" ")}
        {...props}
      >
        {children}
      </ul>
    ),
    ol: ({ children, className, id, ...props }: any) => (
      <ol
        id={typeof id === "string" ? id : undefined}
        className={["list-decimal pl-6 mb-4 space-y-1 text-zinc-700 dark:text-zinc-300 marker:text-zinc-400 dark:marker:text-zinc-500", className]
          .filter(Boolean)
          .join(" ")}
        {...props}
      >
        {children}
      </ol>
    ),
    li: ({ children, className, id, ...props }: any) => (
      <li
        id={typeof id === "string" ? id : undefined}
        className={["pl-1 leading-relaxed", className].filter(Boolean).join(" ")}
        {...props}
      >
        {children}
      </li>
    ),

    // Links
    a: ({ href, children, ...props }: any) => {
      if (isFootnoteBackref(href, props)) {
        return null;
      }

      return isExternalHref(href) ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => handleLinkClick(event, href)}
          className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-500 dark:hover:text-indigo-300 hover:underline transition-colors"
        >
          {children}
        </a>
      ) : (
        <a
          href={href}
          target={isAnchorHref(href) || isReferenceId(href) || isFileHref(href) ? undefined : "_blank"}
          rel={isAnchorHref(href) || isReferenceId(href) || isFileHref(href) ? undefined : "noopener noreferrer"}
          onClick={(event) => handleLinkClick(event, href)}
          className={
            isFileHref(href)
              ? "text-indigo-600 dark:text-indigo-400 hover:text-indigo-500 dark:hover:text-indigo-300 underline underline-offset-4 decoration-1 decoration-indigo-400/70 dark:decoration-indigo-500/60 hover:decoration-indigo-500 dark:hover:decoration-indigo-300 transition-colors cursor-pointer break-all"
              : "inline-flex items-center px-1.5 py-0.5 rounded-md border border-indigo-200/70 dark:border-indigo-700/60 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/35 transition-colors text-xs no-underline"
          }
          title={href}
        >
          {children}
        </a>
      );
    },

    // Images
    img: ({ src, alt }: any) => {
      const normalizedSrc = normalizePublicStorageUrl(typeof src === "string" ? src : undefined);
      return (
      <img
        src={normalizedSrc}
        alt={alt}
        onClick={() => onViewImage(normalizedSrc)}
        className="max-w-full rounded-lg my-2 cursor-zoom-in hover:opacity-90 transition-opacity"
      />
      );
    },

    // Blockquotes
    blockquote: ({ children }: any) => (
      <blockquote className="border-l-4 border-indigo-500/50 pl-4 py-2 my-4 italic text-zinc-600 dark:text-zinc-400 bg-zinc-100 dark:bg-zinc-900/50 rounded-r-lg">
        {children}
      </blockquote>
    ),

    // Horizontal Rule
    hr: () => <hr className="border-zinc-200 dark:border-zinc-800 my-6" />,

    // Tables - with export functionality
    table: ({ children }: any) => (
      <TableWithExport>{children}</TableWithExport>
    ),
    thead: ({ children }: any) => (
      <thead className="bg-zinc-100 dark:bg-zinc-800/40 text-zinc-900 dark:text-zinc-200">
        {children}
      </thead>
    ),
    tbody: ({ children }: any) => (
      <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800/40">
        {children}
      </tbody>
    ),
    tr: ({ children }: any) => (
      <tr className="hover:bg-zinc-50 dark:hover:bg-zinc-800/20 transition-colors group">
        {children}
      </tr>
    ),
    th: ({ children }: any) => (
      <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-zinc-500 dark:text-zinc-400 border-b border-zinc-200 dark:border-zinc-800">
        {children}
      </th>
    ),
    td: ({ children }: any) => (
      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300 group-hover:text-zinc-900 dark:group-hover:text-zinc-200">
        {children}
      </td>
    ),

    // Code
    code: ({ className, children, ...props }: any) => (
      <CodeBlock
        className={className}
        onPreviewRequest={onPreviewRequest}
        {...props}
      >
        {children}
      </CodeBlock>
    ),
  };
};
