import React from "react";
import {
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  Pencil,
  Trash2,
} from "lucide-react";
import { getLanguageConfig } from "@/lib/languageUtils";
import { useLanguage } from "@/hooks/useLanguage";

export interface FileNode {
  id?: string;
  name: string;
  type: "file" | "folder";
  children?: FileNode[];
  isOpen?: boolean;
  content?: string;
}

export type FileTreeSelectEvent = {
  shiftKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
};

interface FileTreeItemProps {
  node: FileNode;
  level: number;
  path: string;
  selectedFile: string | null;
  selectedPaths?: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (path: string, node: FileNode, event?: FileTreeSelectEvent) => void;
  onDelete?: (node: FileNode) => void;
  onRename?: (node: FileNode) => void;
  onDownload?: (node: FileNode) => void;
  onFileDrop?: (sourceNode: FileNode, targetNode: FileNode | null) => void;
  onContextMenu?: (e: React.MouseEvent, node: FileNode) => void;
  expandedPaths: Set<string>;
  renamingNodeId?: string | null;
  onRenameSubmit?: (node: FileNode, newName: string) => void;
  onRenameCancel?: () => void;
}

const getFileIcon = (fileName: string) => {
  const ext = fileName.split(".").pop()?.toLowerCase() || "";
  const config = getLanguageConfig(ext);
  
  return (
    <div className={!config.color ? "text-zinc-500 dark:text-zinc-400" : ""} style={{ color: config.color }}>
      {config.icon}
    </div>
  );
};

export const FileTreeItem: React.FC<FileTreeItemProps> = ({
  node,
  level,
  path,
  selectedFile,
  selectedPaths,
  onToggle,
  onSelect,
  onDelete,
  onRename,
  onDownload,
  onFileDrop,
  onContextMenu,
  expandedPaths,
  renamingNodeId,
  onRenameSubmit,
  onRenameCancel,
}) => {
  const { t } = useLanguage();
  const treePath = node.id ?? path;
  const isExpanded = expandedPaths.has(treePath);
  const isMultiSelected = Boolean(selectedPaths?.has(treePath));
  const isPreviewFocus = selectedFile === treePath && !isMultiSelected;
  const isRenaming = renamingNodeId === node.id;

  const [isDragOver, setIsDragOver] = React.useState(false);
  const [renameValue, setRenameValue] = React.useState(node.name);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (isRenaming) {
      setRenameValue(node.name);
      // Focus and select only filename (exclude extension)
      setTimeout(() => {
        if (inputRef.current) {
          inputRef.current.focus();
          const lastDotIndex = node.name.lastIndexOf(".");
          if (lastDotIndex > 0) {
            inputRef.current.setSelectionRange(0, lastDotIndex);
          } else {
            inputRef.current.select();
          }
        }
      }, 0);
    }
  }, [isRenaming, node.name]);

  const handleDragStart = (e: React.DragEvent) => {
    e.stopPropagation();
    const payload = JSON.stringify(node);
    e.dataTransfer.setData("application/json", payload);
    // Firefox requires a plain-text payload for drag data to persist.
    e.dataTransfer.setData("text/plain", treePath);
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (node.type === "folder") {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    if (node.type === "folder") {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      try {
        const sourceNode = JSON.parse(e.dataTransfer.getData("application/json"));
        if (onFileDrop && sourceNode.id !== node.id) {
          onFileDrop(sourceNode, node);
        }
      } catch (err) {
        console.error("Failed to parse drag data", err);
      }
    }
  };

  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden [contain:inline-size]">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`group grid w-full min-w-0 max-w-full items-center overflow-hidden rounded-md transition-colors ${
          (onRename || onDelete) && !isRenaming
            ? "grid-cols-[minmax(0,1fr)_auto]"
            : "grid-cols-[minmax(0,1fr)]"
        } ${
          isDragOver
            ? "bg-blue-100 dark:bg-blue-900/40 border border-blue-500/50"
            : isMultiSelected
              ? "bg-indigo-500/20 text-indigo-600 dark:text-indigo-400"
              : isPreviewFocus
                ? "bg-zinc-200/80 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100"
                : "hover:bg-zinc-100 dark:hover:bg-zinc-800/50 text-zinc-700 dark:text-zinc-300"
        }`}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onContextMenu?.(e, node);
        }}
      >
        <div
          draggable
          onDragStart={handleDragStart}
          className="flex min-h-7 min-w-0 max-w-full cursor-pointer items-center gap-2 overflow-hidden py-1.5 pr-1"
          style={{ paddingLeft: `${level * 12 + 8}px` }}
          onClick={(e) => {
            const modifiers = {
              shiftKey: e.shiftKey,
              ctrlKey: e.ctrlKey,
              metaKey: e.metaKey,
            };
            const multiSelect =
              modifiers.shiftKey || modifiers.ctrlKey || modifiers.metaKey;
            if (node.type === "folder") {
              if (multiSelect) {
                onSelect(treePath, node, modifiers);
                return;
              }
              onToggle(treePath);
              return;
            }
            onSelect(treePath, node, modifiers);
          }}
        >
          {node.type === "folder" ? (
            <>
              {isExpanded ? (
                <ChevronDown className="w-3.5 h-3.5 shrink-0 text-zinc-500" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5 shrink-0 text-zinc-500" />
              )}
              {isExpanded ? (
                <FolderOpen className="w-4 h-4 shrink-0 text-blue-400" />
              ) : (
                <Folder className="w-4 h-4 shrink-0 text-blue-400" />
              )}
            </>
          ) : (
            <span className="shrink-0">{getFileIcon(node.name)}</span>
          )}
          {isRenaming ? (
            <input
              ref={inputRef}
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onBlur={() => onRenameSubmit?.(node, renameValue)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  onRenameSubmit?.(node, renameValue);
                } else if (e.key === "Escape") {
                  onRenameCancel?.();
                }
                e.stopPropagation();
              }}
              className="text-sm px-1 py-0.5 border rounded border-blue-500 bg-white dark:bg-zinc-800 text-foreground w-full min-w-0 outline-none"
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <span
              className="min-w-0 flex-1 basis-0 truncate overflow-hidden whitespace-nowrap text-sm"
              title={node.name}
            >
              {node.name}
            </span>
          )}
        </div>
        {(onRename || onDelete) && !isRenaming ? (
          <div className="pointer-events-none flex shrink-0 items-center gap-0.5 self-center overflow-hidden rounded-md bg-zinc-100/95 px-0.5 py-0.5 opacity-0 shadow-sm transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100 dark:bg-zinc-900/95">
            {onRename ? (
              <button
                type="button"
                draggable={false}
                onMouseDown={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  onRename(node);
                }}
                className="touch-manipulation rounded p-1 text-zinc-500 transition-colors hover:bg-zinc-200 hover:text-zinc-700 dark:hover:bg-zinc-700 dark:hover:text-zinc-200"
                title={t("preview.rename")}
                aria-label={`${t("preview.rename")} ${node.name}`}
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            ) : null}
            {onDelete ? (
              <button
                type="button"
                draggable={false}
                onMouseDown={(e) => e.stopPropagation()}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onDelete(node);
                }}
                className="touch-manipulation rounded p-1 text-red-500/70 transition-colors hover:bg-red-500/10 hover:text-red-500"
                title={t("preview.delete")}
                aria-label={`${t("preview.delete")} ${node.name}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {node.type === "folder" && isExpanded && node.children && (
        <div
          className="min-w-0 overflow-hidden"
          onDragOver={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            try {
              const sourceNode = JSON.parse(e.dataTransfer.getData("application/json"));
              if (onFileDrop && sourceNode.id !== node.id) {
                onFileDrop(sourceNode, node);
              }
            } catch (err) {
              console.error("Failed to parse drag data", err);
            }
          }}
        >
          {node.children.map((child, idx) => (
            <FileTreeItem
              key={child.id ?? `${treePath}/${child.name}-${idx}`}
              node={child}
              level={level + 1}
              path={child.id ?? `${treePath}/${child.name}`}
              selectedFile={selectedFile}
              selectedPaths={selectedPaths}
              onToggle={onToggle}
              onSelect={onSelect}
              onDelete={onDelete}
              onRename={onRename}
              onDownload={onDownload}
              onFileDrop={onFileDrop}
              onContextMenu={onContextMenu}
              expandedPaths={expandedPaths}
              renamingNodeId={renamingNodeId}
              onRenameSubmit={onRenameSubmit}
              onRenameCancel={onRenameCancel}
            />
          ))}
        </div>
      )}
    </div>
  );
};
