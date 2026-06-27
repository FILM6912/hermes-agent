import React from 'react';
import { createPortal } from 'react-dom';
import { X, AlertCircle, HelpCircle } from 'lucide-react';

interface ConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  type?: 'danger' | 'info';
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  type = 'info'
}) => {
  const [confirming, setConfirming] = React.useState(false);

  if (!isOpen) return null;

  const Icon = type === 'danger' ? AlertCircle : HelpCircle;
  const iconColor = type === 'danger' ? 'text-red-500' : 'text-blue-500';
  const bgColor = type === 'danger' ? 'bg-red-50 dark:bg-red-900/20' : 'bg-blue-50 dark:bg-blue-900/20';
  const borderColor = type === 'danger' ? 'border-red-200 dark:border-red-800/50' : 'border-blue-200 dark:border-blue-800/50';

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 animate-modal-backdrop">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative bg-white dark:bg-[#18181b] rounded-2xl shadow-2xl max-w-md w-full animate-modal-content border border-zinc-200 dark:border-zinc-800">
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
            type="button"
            disabled={confirming}
            onClick={onClose}
            className="px-4 py-2 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-700/50 transition-colors font-medium text-sm disabled:opacity-50"
          >
            {cancelText}
          </button>
          <button
            type="button"
            disabled={confirming}
            onClick={() => {
              void (async () => {
                setConfirming(true);
                try {
                  await onConfirm();
                  onClose();
                } finally {
                  setConfirming(false);
                }
              })();
            }}
            className={`px-4 py-2 text-white rounded-lg transition-colors font-medium text-sm disabled:opacity-50 ${
              type === 'danger' 
                ? 'bg-red-500 hover:bg-red-600' 
                : 'bg-blue-500 hover:bg-blue-600'
            }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
};
