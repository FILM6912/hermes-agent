import React, { useState } from 'react';
import { useElectron, electronFileSystem } from '../hooks/useElectron';
import { Folder, File, Download, Upload, Trash2, Plus } from 'lucide-react';

export const ElectronFileManager: React.FC = () => {
  const { isElectron } = useElectron();
  const [selectedPath, setSelectedPath] = useState<string>('');
  const [fileContent, setFileContent] = useState<string>('');
  const [files, setFiles] = useState<Array<{ name: string; isDirectory: boolean; path: string }>>([]);

  if (!isElectron) {
    return null; // Don't show in web version
  }

  const handleSelectFolder = async () => {
    const path = await electronFileSystem.selectFolder();
    if (path) {
      setSelectedPath(path);
      const dirFiles = await electronFileSystem.readDir(path);
      if (dirFiles) {
        setFiles(dirFiles);
      }
    }
  };

  const handleSelectFile = async () => {
    const path = await electronFileSystem.selectFile();
    if (path) {
      setSelectedPath(path);
      const content = await electronFileSystem.readFile(path);
      if (content) {
        setFileContent(content);
      }
    }
  };

  const handleSaveFile = async () => {
    if (selectedPath && fileContent) {
      const success = await electronFileSystem.writeFile(selectedPath, fileContent);
      if (success) {
        alert('File saved successfully!');
      }
    }
  };

  const handleReadFile = async (filePath: string) => {
    const content = await electronFileSystem.readFile(filePath);
    if (content) {
      setSelectedPath(filePath);
      setFileContent(content);
    }
  };

  return (
    <div className="p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800">
      <h3 className="text-lg font-bold text-zinc-900 dark:text-zinc-100 mb-4">
        File Manager (Desktop Only)
      </h3>

      {/* Action Buttons */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={handleSelectFolder}
          className="flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
        >
          <Folder className="w-4 h-4" />
          Select Folder
        </button>
        <button
          onClick={handleSelectFile}
          className="flex items-center gap-2 px-3 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors"
        >
          <File className="w-4 h-4" />
          Select File
        </button>
        {selectedPath && (
          <button
            onClick={handleSaveFile}
            className="flex items-center gap-2 px-3 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Download className="w-4 h-4" />
            Save File
          </button>
        )}
      </div>

      {/* Selected Path */}
      {selectedPath && (
        <div className="mb-4 p-3 bg-zinc-100 dark:bg-zinc-800 rounded-lg">
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-1">Selected Path:</p>
          <p className="text-sm text-zinc-900 dark:text-zinc-100 font-mono break-all">
            {selectedPath}
          </p>
        </div>
      )}

      {/* File List */}
      {files.length > 0 && (
        <div className="mb-4">
          <h4 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
            Files in Directory:
          </h4>
          <div className="space-y-1 max-h-60 overflow-y-auto">
            {files.map((file, idx) => (
              <div
                key={idx}
                onClick={() => !file.isDirectory && handleReadFile(file.path)}
                className={`flex items-center gap-2 p-2 rounded-lg ${
                  file.isDirectory
                    ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400'
                    : 'bg-zinc-50 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-700'
                }`}
              >
                {file.isDirectory ? (
                  <Folder className="w-4 h-4" />
                ) : (
                  <File className="w-4 h-4" />
                )}
                <span className="text-sm">{file.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* File Content Editor */}
      {fileContent && (
        <div>
          <h4 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
            File Content:
          </h4>
          <textarea
            value={fileContent}
            onChange={(e) => setFileContent(e.target.value)}
            className="w-full h-64 p-3 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg text-sm font-mono text-zinc-900 dark:text-zinc-100 resize-none focus:outline-none focus:border-indigo-500"
          />
        </div>
      )}
    </div>
  );
};
