"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

export type SchemaBuilderField = {
  id: string
  name: string
  type: "string" | "number" | "boolean" | "date"
  required?: boolean
  description?: string
}

export type SchemaBuilderProps = {
  className?: string
  fields: SchemaBuilderField[]
  onChange?: (fields: SchemaBuilderField[]) => void
}

function fieldsToJson(fields: SchemaBuilderField[]) {
  const properties: Record<string, unknown> = {}
  const required: string[] = []

  for (const field of fields) {
    properties[field.name] = {
      type: field.type,
      ...(field.description ? { description: field.description } : {}),
    }
    if (field.required) required.push(field.name)
  }

  return JSON.stringify({ type: "object", properties, required }, null, 2)
}

/**
 * Stub shell for Extend Schema Builder — table editor with JSON sync.
 */
export function SchemaBuilder({
  className,
  fields,
  onChange,
}: SchemaBuilderProps) {
  const json = React.useMemo(() => fieldsToJson(fields), [fields])

  return (
    <div
      data-testid="extend-schema-builder"
      className={cn("grid min-h-0 gap-3 lg:grid-cols-2", className)}
    >
      <div className="rounded-md border">
        <div className="border-b px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Fields
        </div>
        <div className="divide-y">
          {fields.map((field) => (
            <div key={field.id} className="grid grid-cols-3 gap-2 px-3 py-2 text-sm">
              <input
                className="rounded border bg-background px-2 py-1"
                value={field.name}
                onChange={(event) =>
                  onChange?.(
                    fields.map((entry) =>
                      entry.id === field.id
                        ? { ...entry, name: event.target.value }
                        : entry,
                    ),
                  )
                }
              />
              <select
                className="rounded border bg-background px-2 py-1"
                value={field.type}
                onChange={(event) =>
                  onChange?.(
                    fields.map((entry) =>
                      entry.id === field.id
                        ? {
                            ...entry,
                            type: event.target.value as SchemaBuilderField["type"],
                          }
                        : entry,
                    ),
                  )
                }
              >
                <option value="string">string</option>
                <option value="number">number</option>
                <option value="boolean">boolean</option>
                <option value="date">date</option>
              </select>
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={Boolean(field.required)}
                  onChange={(event) =>
                    onChange?.(
                      fields.map((entry) =>
                        entry.id === field.id
                          ? { ...entry, required: event.target.checked }
                          : entry,
                      ),
                    )
                  }
                />
                Required
              </label>
            </div>
          ))}
        </div>
      </div>
      <pre className="min-h-48 overflow-auto rounded-md border bg-muted/20 p-3 text-xs">
        {json}
      </pre>
    </div>
  )
}
