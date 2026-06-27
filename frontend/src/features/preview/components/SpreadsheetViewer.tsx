import React from "react";
import { normalizeSpreadsheetTable } from "../utils/spreadsheetDisplay";

interface SheetImage {
  range: {
    tl: { nativeCol: number; nativeRow: number };
    br: { nativeCol: number; nativeRow: number };
  };
  base64: string;
  extension: string;
}

interface ParsedSheet {
  rows: string[][];
  images: SheetImage[];
}

interface SpreadsheetViewerProps {
  content: string;
  isExcel?: boolean;
  isDark?: boolean;
}

export const SpreadsheetViewer: React.FC<SpreadsheetViewerProps> = ({
  content,
  isExcel = false,
  isDark = true,
}) => {
  const [activeSheet, setActiveSheet] = React.useState<string>("");
  const [parsedData, setParsedData] = React.useState<{
    sheetNames: string[];
    sheets: Record<string, ParsedSheet>;
  } | null>(null);

  let headers: string[] = [];
  let dataRows: string[][] = [];
  let currentSheetImages: SheetImage[] = [];

  React.useEffect(() => {
    if (isExcel) {
      try {
        const trimmed = (content || "").trim();
        if (!trimmed || !(trimmed.startsWith("{") || trimmed.startsWith("["))) {
          return;
        }
        const data = JSON.parse(trimmed);
        
        // Handle multi-sheet format
        if (data.sheetNames && data.sheets) {
          const sheets: Record<string, ParsedSheet> = {};
          
          Object.keys(data.sheets).forEach(name => {
            const rawSheet = data.sheets[name];
            
            // Check if it's the new format with data and images
            if (rawSheet && typeof rawSheet === 'object' && !Array.isArray(rawSheet) && rawSheet.data) {
               sheets[name] = {
                 rows: Array.isArray(rawSheet.data) ? rawSheet.data.map((row: any[]) => row.map((c: any) => String(c || ""))) : [],
                 images: Array.isArray(rawSheet.images) ? rawSheet.images : []
               };
            } else if (Array.isArray(rawSheet)) {
              // Legacy/Fallback array format
              sheets[name] = {
                rows: rawSheet.map((row: any[]) => row.map((c: any) => String(c || ""))),
                images: []
              };
            } else {
              sheets[name] = { rows: [], images: [] };
            }
          });

          setParsedData({
            sheetNames: data.sheetNames,
            sheets: sheets
          });
          
          if (!activeSheet || !data.sheetNames.includes(activeSheet)) {
            setActiveSheet(data.sheetNames[0] || "");
          }
          return;
        }
        
        // Handle legacy single-sheet array format
        if (Array.isArray(data) && data.length > 0) {
          const processedData = data.map((row: any[]) => row.map((c: any) => String(c || "")));
          setParsedData({
            sheetNames: ["Sheet1"],
            sheets: { "Sheet1": { rows: processedData, images: [] } }
          });
          setActiveSheet("Sheet1");
          return;
        }
      } catch (e) {
        console.error("Error parsing Excel content:", e);
      }
    } else {
      // CSV format
      const rows = content.split("\n").filter((r) => r.trim());
      const processedHeaders = rows[0]?.split(",").map((h) => h.trim()) || [];
      const processedRows = rows.slice(1).map((r) => r.split(",").map((c) => c.trim()));
      
      // Add header to rows for consistent rendering with Excel data which includes headers in data
      setParsedData({
        sheetNames: ["CSV"],
        sheets: { "CSV": { rows: [processedHeaders, ...processedRows], images: [] } }
      });
      setActiveSheet("CSV");
    }
  }, [content, isExcel]);

  if (isExcel && !parsedData) {
    return (
      <div className="flex items-center justify-center h-full bg-zinc-100 dark:bg-zinc-900 text-zinc-500">
        <div className="flex flex-col items-center gap-2">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-zinc-500"></div>
          <span>Loading spreadsheet...</span>
        </div>
      </div>
    );
  }

  // Determine current sheet data
  if (parsedData && activeSheet && parsedData.sheets[activeSheet]) {
    const sheetData = parsedData.sheets[activeSheet];
    if (sheetData.rows.length > 0) {
      const rawHeaders = sheetData.rows[0];
      const rawDataRows = sheetData.rows.slice(1);
      const normalized = normalizeSpreadsheetTable(rawHeaders, rawDataRows);
      headers = normalized.headers;
      dataRows = normalized.dataRows;
    }
    currentSheetImages = sheetData.images || [];
  }

  // Error state for raw binary
  if (isExcel && content.startsWith("PK")) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-400">
        <div className="text-center">
          <p>Unable to preview Excel file content.</p>
          <p className="text-xs mt-2 text-zinc-500">The file content appears to be raw binary data.</p>
        </div>
      </div>
    );
  }

  const renderImagesForCell = (rowIndex: number, colIndex: number) => {
    const images = currentSheetImages.filter(img => 
      Math.floor(img.range.tl.nativeRow) === rowIndex && 
      Math.floor(img.range.tl.nativeCol) === colIndex
    );
    
    if (images.length === 0) return null;
    
    return (
      <>
        {images.map((img, idx) => (
          <div 
            key={idx} 
            className="absolute z-10 pointer-events-none"
            style={{
              top: 0,
              left: 0,
              // Simple rendering: just show the image with max dimensions
              // In a real app we'd calculate exact position/size based on col width/row height
            }}
          >
            <img 
              src={img.base64} 
              alt="Embedded" 
              className="max-w-[200px] max-h-[200px] object-contain shadow-md bg-white/5"
            />
          </div>
        ))}
      </>
    );
  };

  const tableBorder = isDark ? "border-zinc-700" : "border-zinc-300";
  const tableSurface = isDark ? "bg-zinc-950" : "bg-white";
  const headSurface = isDark ? "bg-zinc-800 text-zinc-400" : "bg-zinc-100 text-zinc-600";
  const rowHoverCell = isDark
    ? "group-hover:bg-zinc-800/50"
    : "group-hover:bg-zinc-100/80";
  const cellText = isDark ? "text-zinc-300" : "text-zinc-800";
  const indexText = isDark ? "text-zinc-500" : "text-zinc-500";
  const stickyIndexHoverBg = isDark
    ? "group-hover:bg-zinc-800"
    : "group-hover:bg-zinc-100";

  const stickyIndexHead = `sticky left-0 z-30 w-10 min-w-[2.5rem] border border-l-0 px-2 py-2 text-center text-xs font-semibold shadow-[4px_0_8px_-2px_rgba(0,0,0,0.35)] ${tableBorder} ${headSurface}`;
  const stickyIndexCell = `sticky left-0 z-30 w-10 min-w-[2.5rem] border border-l-0 px-2 py-2 text-center text-sm leading-normal shadow-[4px_0_8px_-2px_rgba(0,0,0,0.35)] ${tableBorder} ${tableSurface} ${indexText} ${stickyIndexHoverBg}`;

  return (
    <div className={`flex h-full flex-col ${isDark ? "bg-zinc-950" : "bg-zinc-50"}`}>
      <div className="relative flex-1 overflow-auto py-4 pr-4 pl-0">
        <table
          className={`min-w-full border-separate border-spacing-0 border-y border-r ${tableBorder} ${tableSurface}`}
        >
          <thead>
            <tr className={isDark ? "bg-zinc-800" : "bg-zinc-100"}>
              <th className={stickyIndexHead}>#</th>
              {headers.map((h, i) => (
                <th
                  key={i}
                  className={`relative min-w-[100px] border px-3 py-2 text-left text-xs font-semibold ${tableBorder} ${
                    isDark ? "text-zinc-300" : "text-zinc-700"
                  }`}
                >
                  {h}
                  {renderImagesForCell(0, i)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dataRows.map((row, rIdx) => (
              <tr key={rIdx} className="group transition-colors">
                <td className={stickyIndexCell}>{rIdx + 1}</td>
                {row.map((cell, cIdx) => (
                  <td
                    key={cIdx}
                    className={`relative whitespace-nowrap border px-3 py-2 text-sm leading-normal ${tableBorder} ${cellText} ${rowHoverCell}`}
                  >
                    {cell}
                    {renderImagesForCell(rIdx + 1, cIdx)}
                  </td>
                ))}
                {Array.from({ length: Math.max(0, headers.length - row.length) }).map((_, i) => (
                  <td
                    key={`empty-${i}`}
                    className={`relative border px-3 py-2 text-sm leading-normal ${tableBorder} ${cellText} ${rowHoverCell}`}
                  >
                    {renderImagesForCell(rIdx + 1, row.length + i)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      
      {/* Sheet Tabs */}
      {parsedData && parsedData.sheetNames.length > 1 && (
        <div
          className={`flex items-center gap-1 overflow-x-auto border-t p-1 ${
            isDark ? "border-zinc-800 bg-zinc-900" : "border-zinc-300 bg-zinc-100"
          }`}
        >
          {parsedData.sheetNames.map((name) => (
            <button
              key={name}
              onClick={() => setActiveSheet(name)}
              className={`px-4 py-1.5 text-xs font-medium rounded-t transition-colors whitespace-nowrap ${
                activeSheet === name
                  ? isDark
                    ? "border-t-2 border-emerald-500 bg-zinc-800 text-zinc-100"
                    : "border-t-2 border-emerald-500 bg-white text-zinc-900"
                  : isDark
                    ? "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200"
                    : "text-zinc-600 hover:bg-zinc-200 hover:text-zinc-900"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
