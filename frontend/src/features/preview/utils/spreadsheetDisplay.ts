import { resolveFormulaCellsInSheet } from "./spreadsheetFormula";

/** Normalize spreadsheet rows for preview (strip duplicate index columns). */

const INDEX_HEADER =
  /^(#|index|idx|id|no|no\.|number|row|ลำดับ|ลำดับที่)$/i;

/** Pandas-style "index| value" or "-1| 31" corrupted export in a single cell. */
const PIPE_INDEX_CELL = /^-?\d+\|\s*(\d+(?:\.\d+)?)\s*$/;

export function cleanIndexLikeCell(value: string): string {
  const trimmed = value.trim();
  const pipeMatch = trimmed.match(PIPE_INDEX_CELL);
  if (pipeMatch) return pipeMatch[1];
  return trimmed;
}

function firstColumnLooksLikeRowIndex(dataRows: string[][]): boolean {
  const sample = dataRows.slice(0, Math.min(25, dataRows.length));
  if (sample.length === 0) return false;

  let matches = 0;
  for (let i = 0; i < sample.length; i += 1) {
    const raw = sample[i]?.[0]?.trim() ?? "";
    if (!raw) continue;
    const cleaned = cleanIndexLikeCell(raw);
    const asNum = Number(cleaned);
    if (Number.isFinite(asNum) && Math.abs(asNum - (i + 1)) <= 1) {
      matches += 1;
      continue;
    }
    if (PIPE_INDEX_CELL.test(raw)) {
      matches += 1;
    }
  }

  return matches >= Math.max(3, Math.ceil(sample.length * 0.7));
}

/**
 * Drop a leading index column when the preview already renders a `#` row header.
 * Agent-generated Excel/CSV often includes Index/ลำดับ that duplicates UI row numbers.
 */
export function stripRedundantIndexColumn(
  headers: string[],
  dataRows: string[][],
): { headers: string[]; dataRows: string[][] } {
  if (headers.length === 0 || dataRows.length === 0) {
    return { headers, dataRows };
  }

  const header = headers[0]?.trim() ?? "";
  const redundantHeader = INDEX_HEADER.test(header);
  const redundantValues = firstColumnLooksLikeRowIndex(dataRows);

  if (!redundantHeader && !redundantValues) {
    return { headers, dataRows };
  }

  return {
    headers: headers.slice(1),
    dataRows: dataRows.map((row) => row.slice(1)),
  };
}

export function normalizeSpreadsheetTable(
  headers: string[],
  dataRows: string[][],
): { headers: string[]; dataRows: string[][] } {
  const resolved = resolveFormulaCellsInSheet([headers, ...dataRows]);
  const resolvedHeaders = resolved[0] ?? headers;
  const resolvedDataRows = resolved.slice(1);
  const stripped = stripRedundantIndexColumn(resolvedHeaders, resolvedDataRows);
  return {
    headers: stripped.headers,
    dataRows: stripped.dataRows.map((row) =>
      row.map((cell) => cleanIndexLikeCell(cell)),
    ),
  };
}
