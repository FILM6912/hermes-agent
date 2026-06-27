/** Evaluate common Excel formulas for in-browser spreadsheet preview. */

const FORMULA_CELL_JSON = /^\s*\{\s*"formula"\s*:\s*"([^"]+)"\s*(?:,\s*"result"\s*:\s*([^}]+))?\s*\}\s*$/;

function excelColumnToIndex(col: string): number {
  let index = 0;
  for (const ch of col.toUpperCase()) {
    index = index * 26 + (ch.charCodeAt(0) - 64);
  }
  return index - 1;
}

function parseA1Range(range: string): {
  startRow: number;
  startCol: number;
  endRow: number;
  endCol: number;
} | null {
  const match = range
    .trim()
    .replace(/\$/g, "")
    .match(/^([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)$/);
  if (!match) return null;
  return {
    startCol: excelColumnToIndex(match[1]),
    startRow: Number(match[2]) - 1,
    endCol: excelColumnToIndex(match[3]),
    endRow: Number(match[4]) - 1,
  };
}

function getCellValue(rows: string[][], row: number, col: number): string {
  return rows[row]?.[col]?.trim() ?? "";
}

function collectRangeValues(rows: string[][], range: string): string[] {
  const bounds = parseA1Range(range);
  if (!bounds) return [];
  const values: string[] = [];
  for (let row = bounds.startRow; row <= bounds.endRow; row += 1) {
    for (let col = bounds.startCol; col <= bounds.endCol; col += 1) {
      values.push(getCellValue(rows, row, col));
    }
  }
  return values;
}

function parseNumeric(value: string): number | null {
  const cleaned = value.replace(/,/g, "").trim();
  if (!cleaned) return null;
  const num = Number(cleaned);
  return Number.isFinite(num) ? num : null;
}

function formatPreviewNumber(value: number): string {
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2).replace(/\.?0+$/, "");
}

export function evaluateSpreadsheetFormula(
  formula: string,
  rows: string[][],
): string {
  const expr = formula.trim().replace(/^=/, "");
  const fnMatch = expr.match(/^([A-Z]+)\(([^)]+)\)$/i);
  if (!fnMatch) return formula;

  const fn = fnMatch[1].toUpperCase();
  const arg = fnMatch[2].trim();
  const values = collectRangeValues(rows, arg);
  const numbers = values
    .map(parseNumeric)
    .filter((n): n is number => n !== null);

  switch (fn) {
    case "SUM": {
      if (numbers.length === 0) return "0";
      return formatPreviewNumber(numbers.reduce((a, b) => a + b, 0));
    }
    case "AVERAGE": {
      if (numbers.length === 0) return "0";
      return formatPreviewNumber(
        numbers.reduce((a, b) => a + b, 0) / numbers.length,
      );
    }
    case "COUNT":
      return String(numbers.length);
    case "COUNTA":
      return String(values.filter((v) => v !== "").length);
    case "MIN": {
      if (numbers.length === 0) return "0";
      return formatPreviewNumber(Math.min(...numbers));
    }
    case "MAX": {
      if (numbers.length === 0) return "0";
      return formatPreviewNumber(Math.max(...numbers));
    }
    default:
      return formula;
  }
}

type SpreadsheetCellObject = {
  richText?: Array<{ text?: string }>;
  text?: string;
  result?: unknown;
  formula?: string;
};

export function stringifySpreadsheetCell(
  value: unknown,
  rows: string[][],
): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (typeof value === "string") {
    const formulaJson = tryParseFormulaJson(value);
    if (formulaJson) {
      if (formulaJson.result !== undefined && formulaJson.result !== null) {
        return String(formulaJson.result);
      }
      if (formulaJson.formula) {
        return evaluateSpreadsheetFormula(formulaJson.formula, rows);
      }
    }
    if (isFormulaExpression(value)) {
      return evaluateSpreadsheetFormula(value, rows);
    }
    return value;
  }
  if (typeof value === "object") {
    const obj = value as SpreadsheetCellObject;
    if (Array.isArray(obj.richText)) {
      return obj.richText.map((part) => part.text ?? "").join("");
    }
    if (typeof obj.text === "string") return obj.text;
    if (obj.result !== undefined && obj.result !== null) {
      return String(obj.result);
    }
    if (typeof obj.formula === "string") {
      return evaluateSpreadsheetFormula(obj.formula, rows);
    }
    return JSON.stringify(value);
  }
  return String(value);
}

function tryParseFormulaJson(
  value: string,
): { formula?: string; result?: unknown } | null {
  const trimmed = value.trim();
  if (!trimmed.startsWith("{")) return null;
  try {
    const parsed = JSON.parse(trimmed) as { formula?: string; result?: unknown };
    if (typeof parsed.formula === "string") return parsed;
  } catch {
    const match = trimmed.match(FORMULA_CELL_JSON);
    if (match) {
      return {
        formula: match[1],
        result:
          match[2] !== undefined ? JSON.parse(match[2].trim()) : undefined,
      };
    }
  }
  return null;
}

/** Resolve formula JSON strings already stored in preview cache. */
export function resolveFormulaCellsInSheet(rows: string[][]): string[][] {
  return rows.map((row) =>
    row.map((cell) => stringifySpreadsheetCell(cell, rows)),
  );
}

function isFormulaExpression(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.startsWith("=") || /^[A-Z]+\([^)]+\)$/i.test(trimmed);
}

function toLiteralSpreadsheetCell(cell: unknown): string {
  if (cell === null || cell === undefined) return "";
  if (typeof cell === "number" || typeof cell === "boolean") {
    return String(cell);
  }
  if (typeof cell === "string") {
    const formulaJson = tryParseFormulaJson(cell);
    if (formulaJson?.result !== undefined && formulaJson.result !== null) {
      return String(formulaJson.result);
    }
    if (formulaJson?.formula || isFormulaExpression(cell)) return "";
    return cell;
  }
  if (typeof cell === "object") {
    const obj = cell as SpreadsheetCellObject;
    if (Array.isArray(obj.richText)) {
      return obj.richText.map((part) => part.text ?? "").join("");
    }
    if (typeof obj.text === "string") return obj.text;
    if (obj.result !== undefined && obj.result !== null) {
      return String(obj.result);
    }
    if (typeof obj.formula === "string") return "";
  }
  return String(cell);
}

/** Convert ExcelJS raw rows to display strings, evaluating uncached formulas. */
export function resolveRawSpreadsheetRows(rawRows: unknown[][]): string[][] {
  const literalRows = rawRows.map((row) => row.map(toLiteralSpreadsheetCell));
  return rawRows.map((row, rowIdx) =>
    row.map((cell, colIdx) => {
      if (typeof cell === "object" && cell !== null) {
        const obj = cell as SpreadsheetCellObject;
        if (typeof obj.formula === "string") {
          return evaluateSpreadsheetFormula(obj.formula, literalRows);
        }
      }
      if (typeof cell === "string") {
        const formulaJson = tryParseFormulaJson(cell);
        if (formulaJson?.formula) {
          return evaluateSpreadsheetFormula(formulaJson.formula, literalRows);
        }
        if (isFormulaExpression(cell)) {
          return evaluateSpreadsheetFormula(cell, literalRows);
        }
      }
      return literalRows[rowIdx]?.[colIdx] ?? "";
    }),
  );
}
