import { describe, expect, it } from "vitest"

import {
  buildAcceptAttribute,
  validateExtendUploadFile,
} from "./file-upload-validation"

describe("validateExtendUploadFile", () => {
  it("accepts files within size and type rules", () => {
    const file = new File(["hello"], "notes.pdf", { type: "application/pdf" })
    expect(
      validateExtendUploadFile(file, {
        maxBytes: 1024,
        accept: [".pdf", ".docx"],
      }),
    ).toEqual({ ok: true })
  })

  it("rejects files over maxBytes", () => {
    const file = new File([new Uint8Array(2048)], "big.pdf", {
      type: "application/pdf",
    })
    expect(
      validateExtendUploadFile(file, {
        maxBytes: 1024,
        accept: [".pdf"],
      }),
    ).toEqual({ ok: false, reason: "size" })
  })

  it("rejects unsupported extensions", () => {
    const file = new File(["zip"], "archive.zip", {
      type: "application/zip",
    })
    expect(
      validateExtendUploadFile(file, {
        maxBytes: 1024,
        accept: [".pdf", ".docx"],
      }),
    ).toEqual({ ok: false, reason: "type" })
  })
})

describe("buildAcceptAttribute", () => {
  it("joins accept tokens for input elements", () => {
    expect(buildAcceptAttribute([".pdf", ".docx"])).toBe(".pdf,.docx")
  })
})
