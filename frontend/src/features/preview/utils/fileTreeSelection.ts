import type { FileNode } from "../components/FileTreeItem";

export type VisibleFileEntry = {
  path: string;
  node: FileNode;
};

/** Flatten files and folders currently visible in the tree (expanded folders only). */
export function flattenVisibleFiles(
  nodes: FileNode[],
  expandedPaths: Set<string>,
): VisibleFileEntry[] {
  const out: VisibleFileEntry[] = [];

  const walk = (list: FileNode[]) => {
    for (const node of list) {
      const path = node.id ?? node.name;
      out.push({ path, node });
      if (
        node.type === "folder" &&
        expandedPaths.has(path) &&
        node.children?.length
      ) {
        walk(node.children);
      }
    }
  };

  walk(nodes);
  return out;
}

/** Range-select paths between anchor and target in visible file order. */
export function rangeSelectPaths(
  visible: VisibleFileEntry[],
  anchorPath: string,
  targetPath: string,
): string[] {
  const anchorIdx = visible.findIndex((entry) => entry.path === anchorPath);
  const targetIdx = visible.findIndex((entry) => entry.path === targetPath);
  if (anchorIdx < 0 || targetIdx < 0) return [targetPath];
  const start = Math.min(anchorIdx, targetIdx);
  const end = Math.max(anchorIdx, targetIdx);
  return visible.slice(start, end + 1).map((entry) => entry.path);
}

/** Resolve file nodes by workspace-relative paths (files and folders). */
export function findNodesByPaths(
  nodes: FileNode[],
  paths: Iterable<string>,
): FileNode[] {
  const wanted = new Set(paths);
  const found: FileNode[] = [];

  const walk = (list: FileNode[]) => {
    for (const node of list) {
      const path = node.id ?? node.name;
      if (wanted.has(path)) {
        found.push(node);
      }
      if (node.children?.length) {
        walk(node.children);
      }
    }
  };

  walk(nodes);
  return found;
}
