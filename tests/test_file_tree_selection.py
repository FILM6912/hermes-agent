"""Workspace file tree multi-select helpers."""

from pathlib import Path


def test_file_tree_selection_utils_exist():
    src = Path("frontend/src/features/preview/utils/fileTreeSelection.ts").read_text(
        encoding="utf-8",
    )
    assert "flattenVisibleFiles" in src
    assert "rangeSelectPaths" in src
    tree = Path("frontend/src/features/preview/components/FileTreeItem.tsx").read_text(
        encoding="utf-8",
    )
    assert "selectedPaths" in tree
    assert "isMultiSelected" in tree
    assert 'type="checkbox"' not in tree
    preview = Path("frontend/src/features/preview/components/PreviewWindow.tsx").read_text(
        encoding="utf-8",
    )
    assert "handleDeleteSelected" in preview
    assert "findNodesByPaths" in preview
    hook = Path("frontend/src/features/preview/hooks/useFileSystem.ts").read_text(
        encoding="utf-8",
    )
    assert "setSelectedPaths(new Set())" in hook
    assert hook.index("if (modifiers?.shiftKey)") < hook.index("setSelectedFile(path)")
    assert hook.index("if (modifiers?.ctrlKey || modifiers?.metaKey)") < hook.index(
        "setSelectedFile(path)"
    )


def test_folder_multi_select_uses_on_select_with_modifiers():
    tree = Path("frontend/src/features/preview/components/FileTreeItem.tsx").read_text(
        encoding="utf-8",
    )
    assert "multiSelect" in tree
    assert "onSelect(treePath, node, modifiers)" in tree


def test_flatten_visible_includes_folders():
    src = Path("frontend/src/features/preview/utils/fileTreeSelection.ts").read_text(
        encoding="utf-8",
    )
    assert "out.push({ path, node })" in src
    assert 'if (node.type === "file")' not in src
