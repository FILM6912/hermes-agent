import React from 'react';
import { X, AlertCircle, AlertTriangle } from 'lucide-react';

interface ErrorModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  message: string;
  type?: 'error' | 'warning';
}

export const ErrorModal: React.FC<ErrorModalProps> = ({
  isOpen,
  onClose,
  title,
  message,
  type = 'error'
}) => {
  if (!isOpen) return null;

  const Icon = type === 'warning' ? AlertTriangle : AlertCircle;
  const iconColor = type === 'warning' ? 'text-amber-500' : 'text-red-500';
  const bgColor = type === 'warning' ? 'bg-amber-50 dark:bg-amber-900/20' : 'bg-red-50 dark:bg-red-900/20';
  const borderColor = type === 'warning' ? 'border-amber-200 dark:border-amber-800/50' : 'border-red-200 dark:border-red-800/50';

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 animate-in fade-in duration-200">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative bg-white dark:bg-[#18181b] rounded-2xl shadow-2xl max-w-md w-full animate-in zoom-in-95 duration-200 border border-zinc-200 dark:border-zinc-800">
        {/* Header */}
        <div className="flex items-start gap-4 p-6 pb-4">
          <div className={`p-3 rounded-xl ${bgColor} border ${borderColor}`}>
            <Icon className={`w-6 h-6 ${iconColor}`} />
          </div>
          
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100 mb-1">
              {title}
            </h2>
            <p className="text-sm text-zinc-600 dark:text-zinc-400 whitespace-pre-line">
              {message}
            </p>
          </div>
          
          <button
            onClick={onClose}
            className="p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors text-zinc-500 dark:text-zinc-400"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        
        {/* Footer */}
        <div className="flex justify-end gap-2 p-6 pt-2 border-t border-zinc-200 dark:border-zinc-800">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-zinc-900 dark:bg-white text-white dark:text-black rounded-lg hover:bg-zinc-800 dark:hover:bg-zinc-100 transition-colors font-medium text-sm"
          >
            ตกลง
          </button>
        </div>
      </div>
    </div>
  );
};
