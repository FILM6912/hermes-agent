import { useState, useEffect } from 'react';

export const useElectron = () => {
  const [isElectron, setIsElectron] = useState(false);
  const [version, setVersion] = useState<string>('');

  useEffect(() => {
    const checkElectron = async () => {
      if (window.electronAPI) {
        const electron = await window.electronAPI.isElectron();
        setIsElectron(electron);
        
        if (electron) {
          const ver = await window.electronAPI.getVersion();
          setVersion(ver);
        }
      }
    };
    
    checkElectron();
  }, []);

  return {
    isElectron,
    version,
    api: window.electronAPI
  };
};

// Helper functions for file operations
export const electronFileSystem = {
  async selectFolder() {
    if (!window.electronAPI) return null;
    const result = await window.electronAPI.selectFolder();
    return result.canceled ? null : result.path;
  },

  async selectFile() {
    if (!window.electronAPI) return null;
    const result = await window.electronAPI.selectFile();
    return result.canceled ? null : result.path;
  },

  async readFile(filePath: string) {
    if (!window.electronAPI) return null;
    const result = await window.electronAPI.readFile(filePath);
    return result.success ? result.content : null;
  },

  async writeFile(filePath: string, content: string) {
    if (!window.electronAPI) return false;
    const result = await window.electronAPI.writeFile(filePath, content);
    return result.success;
  },

  async readDir(dirPath: string) {
    if (!window.electronAPI) return null;
    const result = await window.electronAPI.readDir(dirPath);
    return result.success ? result.files : null;
  },

  async createDir(dirPath: string) {
    if (!window.electronAPI) return false;
    const result = await window.electronAPI.createDir(dirPath);
    return result.success;
  },

  async deleteFile(filePath: string) {
    if (!window.electronAPI) return false;
    const result = await window.electronAPI.deleteFile(filePath);
    return result.success;
  }
};
