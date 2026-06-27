/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_HOVER: string;
  readonly VITE_SUGGESTION_SESSION_ID: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface ElectronAPI {
  isElectron(): Promise<boolean>;
  getVersion(): Promise<string>;
  selectFolder(): Promise<{ canceled: boolean; path?: string }>;
  selectFile(): Promise<{ canceled: boolean; path?: string }>;
  readFile(filePath: string): Promise<{ success: boolean; content?: string }>;
  writeFile(filePath: string, content: string): Promise<{ success: boolean }>;
  readDir(dirPath: string): Promise<{ success: boolean; files?: unknown[] }>;
  createDir(dirPath: string): Promise<{ success: boolean }>;
  deleteFile(filePath: string): Promise<{ success: boolean }>;
}

interface Window {
  electronAPI?: ElectronAPI;
}

declare module "react-dom";
declare module "react-dom/client";
