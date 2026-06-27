import React, { useCallback, useRef } from "react";
import { FileSpreadsheet, Table } from "lucide-react";
import * as XLSX from "xlsx";

interface TableWithExportProps {
  children: React.ReactNode;
}

export const TableWithExport: React.FC<TableWithExportProps> = ({ children }) => {
  const tableRef = useRef<HTMLDivElement>(null);

  const parseTableToData = useCallback(() => {
    if (!tableRef.current) return { headers: [], rows: [] };

    const table = tableRef.current.querySelector("table");
    if (!table) return { headers: [], rows: [] };

    const headerCells = table.querySelectorAll("thead th");
    const headers = Array.from(headerCells).map((th) => th.textContent?.trim() || "");

    const bodyRows = table.querySelectorAll("tbody tr");
    const rows = Array.from(bodyRows).map((tr) => {
      const cells = tr.querySelectorAll("td");
      return Array.from(cells).map((td) => td.textContent?.trim() || "");
    });

    return { headers, rows };
  }, []);

  const exportToCSV = useCallback(() => {
    const { headers, rows } = parseTableToData();
    if (headers.length === 0 && rows.length === 0) return;

    const csvContent = [
      headers.join(","),
      ...rows.map((row) =>
        row.map((cell) => {
          // Escape cells containing commas or quotes
          if (cell.includes(",") || cell.includes('"') || cell.includes("\n")) {
            return `"${cell.replace(/"/g, '""')}"`;
          }
          return cell;
        }).join(",")
      ),
    ].join("\n");

    const blob = new Blob(["\ufeff" + csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `table-export-${Date.now()}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [parseTableToData]);

  const exportToExcel = useCallback(() => {
    try {
      const { headers, rows } = parseTableToData();
      if (headers.length === 0 && rows.length === 0) {
        console.warn("No data to export");
        return;
      }

      const wsData = [headers, ...rows];
      const workbook = XLSX.utils.book_new();
      const worksheet = XLSX.utils.aoa_to_sheet(wsData);

      // Auto-size columns
      const colWidths = headers.map((header, i) => {
        const maxLen = Math.max(
          header.length,
          ...rows.map((row) => (row[i] || "").length)
        );
        return { wch: Math.min(Math.max(maxLen + 2, 10), 50) };
      });
      worksheet["!cols"] = colWidths;

      XLSX.utils.book_append_sheet(workbook, worksheet, "Data");
      
      // Use array buffer and blob for better browser compatibility
      const excelBuffer = XLSX.write(workbook, { bookType: "xlsx", type: "array" });
      const blob = new Blob([excelBuffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `table-export-${Date.now()}.xlsx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Excel export error:", error);
    }
  }, [parseTableToData]);

  return (
    <div className="relative group/mytable">
      <div ref={tableRef} className="overflow-x-auto my-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-[#121214] shadow-sm">
        <table className="w-full text-left text-sm border-collapse">
          {children}
        </table>
      </div>

      {/* Export Buttons - appear on hover */}
      <div className="absolute top-2 right-2 opacity-0 group-hover/mytable:opacity-100 transition-opacity duration-200 flex gap-1">
        <button
          onClick={exportToCSV}
          className="flex items-center gap-1 px-2 py-1 text-xs font-medium bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-md shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-300 transition-colors"
          title="Export as CSV"
        >
          <Table className="w-3 h-3" />
          CSV
        </button>
        <button
          onClick={exportToExcel}
          className="flex items-center gap-1 px-2 py-1 text-xs font-medium bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800 rounded-md shadow-sm hover:bg-emerald-100 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 transition-colors"
          title="Export as Excel"
        >
          <FileSpreadsheet className="w-3 h-3" />
          Excel
        </button>
      </div>
    </div>
  );
};
