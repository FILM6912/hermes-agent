export interface ElectronAPI {
  // Dialog APIs
  selectFolder: () => Promise<{ canceled: boolean; path?: string }>;
  selectFile: () => Promise<{ canceled: boolean; path?: string }>;
  
  // File System APIs
  readFile: (filePath: string) => Promise<{ success: boolean; content?: string; error?: string }>;
  writeFile: (filePath: string, content: string) => Promise<{ success: boolean; error?: string }>;
  readDir: (dirPath: string) => Promise<{ 
    success: boolean; 
    files?: Array<{ name: string; isDirectory: boolean; path: string }>; 
    error?: string 
  }>;
  createDir: (dirPath: string) => Promise<{ success: boolean; error?: string }>;
  deleteFile: (filePath: string) => Promise<{ success: boolean; error?: string }>;
  
  // App APIs
  isElectron: () => Promise<boolean>;
  getVersion: () => Promise<string>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
