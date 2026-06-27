import { describe, expect, it } from "vitest"

import type { HermesDirEntry } from "@/services/hermes/workspace"

import {
  mapHermesEntriesToFileSystemItems,
  mapHermesEntryToFileSystemItem,
} from "./hermesFileSystemItems"

describe("mapHermesEntryToFileSystemItem", () => {
  it("maps directory entries to folder items", () => {
    const entry: HermesDirEntry = {
      name: "docs",
      path: "docs",
      type: "dir",
    }

    expect(mapHermesEntryToFileSystemItem(entry)).toEqual({
      kind: "folder",
      path: "docs/",
      name: "docs",
      hasChildren: true,
    })
  })

  it("maps file entries with size", () => {
    const entry: HermesDirEntry = {
      name: "report.pdf",
      path: "docs/report.pdf",
      type: "file",
      size: 2048,
    }

    expect(mapHermesEntryToFileSystemItem(entry)).toEqual({
      kind: "file",
      path: "docs/report.pdf",
      name: "report.pdf",
      size: 2048,
    })
  })
})

describe("mapHermesEntriesToFileSystemItems", () => {
  it("maps a full directory listing", () => {
    const entries: HermesDirEntry[] = [
      { name: "docs", path: "docs", type: "dir" },
      { name: "readme.txt", path: "readme.txt", type: "file", size: 12 },
    ]

    expect(mapHermesEntriesToFileSystemItems(entries)).toEqual([
      {
        kind: "folder",
        path: "docs/",
        name: "docs",
        hasChildren: true,
      },
      {
        kind: "file",
        path: "readme.txt",
        name: "readme.txt",
        size: 12,
      },
    ])
  })
})
