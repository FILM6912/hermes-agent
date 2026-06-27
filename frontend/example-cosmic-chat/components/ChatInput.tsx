import React from "react";
import {
  Send,
  Paperclip,
  Mic,
  MicOff,
  X,
  File as FileIcon,
  Cpu,
  Server
} from "lucide-react";
import { Attachment } from "../types";
import { useLanguage } from "../hooks/useLanguage";

// Simplified mocked sub-components for the demo to work without missing files
const ModelSelector: React.FC<any> = ({ isOpen, onToggle, onModelSelect }) => (
  <div className="relative">
    <button 
      onClick={onToggle} 
      className="p-2 text-[#6e8cff] hover:text-[#a9c7ff] transition-colors rounded-full hover:bg-[#4d6dff]/10"
      title="Select Model"
    >
      <Cpu className="w-5 h-5" />
    </button>
  </div>
);

const MCPServerList: React.FC<any> = ({ isOpen, onToggle }) => (
  <div className="relative">
    <button 
      onClick={onToggle} 
      className="p-2 text-[#6e8cff] hover:text-[#a9c7ff] transition-colors rounded-full hover:bg-[#4d6dff]/10"
      title="MCP Servers"
    >
      <Server className="w-5 h-5" />
    </button>
  </div>
);

interface ChatInputProps {
  input: string;
  setInput: (value: string) => void;
  attachments: Attachment[];
  onRemoveAttachment: (index: number) => void;
  onSend: () => void;
  onFileSelect: () => void;
  onPaste: (e: React.ClipboardEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  isDragging: boolean;
  isLoading: boolean;
  isStreaming: boolean;
  isListening: boolean;
  speechError: string | null;
  onToggleListening: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  fileInputRef: React.RefObject<HTMLInputElement>;

  // Model Selector Props
  showModelMenu: boolean;
  setShowModelMenu: (show: boolean) => void;
  modelConfig: any;
  agentModels: { id: string; name: string; desc: string }[];
  pinnedAgentId: string | null;
  onModelSelect: (modelId: string, modelName: string) => void;
  onPinAgent: (agentId: string) => void;
  modelMenuRef: React.RefObject<HTMLDivElement>;

  // MCP Props
  showMcpMenu: boolean;
  setShowMcpMenu: (show: boolean) => void;
  mcpServers: string[];
  mcpMenuRef: React.RefObject<HTMLDivElement>;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  input,
  setInput,
  attachments,
  onRemoveAttachment,
  onSend,
  onFileSelect,
  onPaste,
  onDragOver,
  onDragLeave,
  onDrop,
  isDragging,
  isLoading,
  isStreaming,
  isListening,
  speechError,
  onToggleListening,
  textareaRef,
  fileInputRef,
  showModelMenu,
  setShowModelMenu,
  modelConfig,
  agentModels,
  pinnedAgentId,
  onModelSelect,
  onPinAgent,
  modelMenuRef,
  showMcpMenu,
  setShowMcpMenu,
  mcpServers,
  mcpMenuRef,
}) => {
  const { t } = useLanguage();

  const autoResize = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  // Cosmic CSS Styles injected directly to ensure exact match with requirements
  // Adjusted for responsiveness (w-full instead of fixed width) and larger gradients
  const cosmicStyles = `
    .cosmic-container {
      --bg-deep: #05071b;
      --accent-light: #a9c7ff;
      --accent-main: #4d6dff;
      --accent-dim: #6e8cff;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      width: 100%;
      border-radius: 16px;
      isolation: isolate;
    }

    /* Layers */
    .stardust, .cosmic-ring, .starfield, .nebula {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      z-index: -1;
      border-radius: 16px;
      filter: blur(3px);
      pointer-events: none;
    }

    .stardust { filter: blur(2px); }
    .cosmic-ring { filter: blur(0.5px); }
    .nebula { filter: blur(30px); opacity: 0.5; }

    /* Gradients - Size increased for responsiveness */
    .stardust::before, .cosmic-ring::before, .starfield::before, .nebula::before {
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      width: 200vmax; /* Massive size to cover full width */
      height: 200vmax;
      background-repeat: no-repeat;
      background-position: center;
      transition: transform 2s ease-out;
      will-change: transform;
    }

    /* Specific Gradient Definitions */
    .stardust::before {
      transform: translate(-50%, -50%) rotate(83deg);
      filter: brightness(1.4);
      background-image: conic-gradient(rgba(0,0,0,0) 0%, var(--accent-main), rgba(0,0,0,0) 8%, rgba(0,0,0,0) 50%, var(--accent-dim), rgba(0,0,0,0) 58%);
    }

    .cosmic-ring::before {
      transform: translate(-50%, -50%) rotate(70deg);
      filter: brightness(1.3);
      background-image: conic-gradient(var(--bg-deep), var(--accent-main) 5%, var(--bg-deep) 14%, var(--bg-deep) 50%, var(--accent-dim) 60%, var(--bg-deep) 64%);
    }

    .starfield::before {
      transform: translate(-50%, -50%) rotate(82deg);
      background-image: conic-gradient(rgba(0,0,0,0), #1c2452, rgba(0,0,0,0) 10%, rgba(0,0,0,0) 50%, #2a3875, rgba(0,0,0,0) 60%);
    }

    .nebula::before {
      transform: translate(-50%, -50%) rotate(60deg);
      background-image: conic-gradient(#000, var(--accent-main) 5%, #000 38%, #000 50%, var(--accent-dim) 60%, #000 87%);
    }

    /* Interactive States (Group Hover/Focus equivalent) */
    .cosmic-container:hover .starfield::before { transform: translate(-50%, -50%) rotate(-98deg); }
    .cosmic-container:hover .nebula::before { transform: translate(-50%, -50%) rotate(-120deg); }
    .cosmic-container:hover .stardust::before { transform: translate(-50%, -50%) rotate(-97deg); }
    .cosmic-container:hover .cosmic-ring::before { transform: translate(-50%, -50%) rotate(-110deg); }

    .cosmic-container:focus-within .starfield::before { transform: translate(-50%, -50%) rotate(442deg); transition: transform 4s ease-out; }
    .cosmic-container:focus-within .nebula::before { transform: translate(-50%, -50%) rotate(420deg); transition: transform 4s ease-out; }
    .cosmic-container:focus-within .stardust::before { transform: translate(-50%, -50%) rotate(443deg); transition: transform 4s ease-out; }
    .cosmic-container:focus-within .cosmic-ring::before { transform: translate(-50%, -50%) rotate(430deg); transition: transform 4s ease-out; }

    /* Glow Effect */
    #cosmic-glow {
      pointer-events: none;
      width: 40px;
      height: 25px;
      position: absolute;
      background: var(--accent-main);
      top: 20px;
      left: 20px;
      filter: blur(25px);
      opacity: 0.8;
      transition: all 2s;
    }
    .cosmic-container:hover #cosmic-glow { opacity: 0; }

    /* Wormhole Animation */
    @keyframes wormhole-rotate {
      100% { transform: translate(-50%, -50%) rotate(450deg); }
    }
    .wormhole-spin::before {
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%) rotate(90deg);
      width: 400px;
      height: 400px;
      background-image: conic-gradient(rgba(0,0,0,0), var(--accent-main), rgba(0,0,0,0) 50%, rgba(0,0,0,0) 50%, var(--accent-dim), rgba(0,0,0,0) 100%);
      animation: wormhole-rotate 4s linear infinite;
      filter: brightness(1.35);
    }
  `;

  return (
    <>
      <style>{cosmicStyles}</style>
      <div className="absolute bottom-6 left-0 w-full px-4 z-20 pointer-events-none">
        <div className="max-w-5xl mx-auto pointer-events-auto">
          {/* Main Cosmic Container */}
          <div 
            className="cosmic-container relative w-full group transition-all duration-500"
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            {/* Background Layers */}
            <div className="nebula"></div>
            <div className="starfield"></div>
            <div className="stardust"></div>
            <div className="stardust opacity-50 translate-x-1"></div>
            <div className="cosmic-ring"></div>
            <div id="cosmic-glow"></div>

            {/* Inner Content Wrapper (The "Main" div in CSS) */}
            <div className="relative z-10 w-full flex flex-col bg-[#05071b] rounded-2xl border border-white/5 shadow-2xl overflow-hidden">
              
              {/* Drag Overlay */}
              {isDragging && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-[#05071b]/90 backdrop-blur-sm animate-pulse">
                  <div className="flex flex-col items-center gap-3 text-[#a9c7ff]">
                    <div className="relative">
                       <div className="absolute inset-0 bg-[#4d6dff] blur-lg opacity-50 rounded-full"></div>
                       <Paperclip className="w-10 h-10 relative z-10" />
                    </div>
                    <span className="font-semibold tracking-wider text-sm uppercase">
                      {t("chat.dropFiles")}
                    </span>
                  </div>
                </div>
              )}

              {/* Attachments Area */}
              {attachments.length > 0 && (
                <div className="flex flex-wrap gap-2 px-4 pt-4 pb-0 max-h-32 overflow-y-auto custom-scrollbar relative z-20">
                  {attachments.map((file, index) => (
                    <div
                      key={index}
                      className="flex items-center gap-2 bg-[#1c2452] rounded-lg pl-2 pr-2 py-1.5 border border-[#2a3875] text-xs text-[#a9c7ff] animate-in fade-in zoom-in-95 group/file relative overflow-hidden"
                    >
                      {file.type === "image" ? (
                        <div className="relative w-8 h-8 rounded overflow-hidden shrink-0 border border-[#4d6dff]/30">
                          <img
                            src={file.content}
                            alt={file.name}
                            className="w-full h-full object-cover"
                          />
                        </div>
                      ) : (
                        <FileIcon className="w-3.5 h-3.5 text-[#4d6dff]" />
                      )}
                      <span className="max-w-[150px] truncate">{file.name}</span>
                      <button
                        onClick={() => onRemoveAttachment(index)}
                        className="p-1 hover:bg-[#2a3875] rounded-md text-[#6e8cff] hover:text-white transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Text Input Area */}
              <div className="relative w-full flex items-start">
                 {/* Left Actions (replacing search icon) */}
                 <div className="pl-3 py-3 flex items-center gap-1 self-end mb-[2px]">
                   <button
                    onClick={onFileSelect}
                    className="p-2 text-[#6e8cff] hover:text-[#a9c7ff] hover:bg-[#4d6dff]/10 rounded-xl transition-colors"
                    title="Attach File"
                   >
                     <Paperclip className="w-5 h-5" />
                   </button>
                    <MCPServerList
                      isOpen={showMcpMenu}
                      onToggle={() => setShowMcpMenu(!showMcpMenu)}
                    />
                 </div>

                 {/* Textarea */}
                 <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => {
                    setInput(e.target.value);
                    autoResize();
                  }}
                  onKeyDown={handleKeyDown}
                  onPaste={onPaste}
                  placeholder={t("chat.placeholder")}
                  className="w-full bg-transparent text-[#a9c7ff] placeholder-[#6e8cff]/50 px-3 py-5 outline-none resize-none min-h-[56px] max-h-[30vh] text-base leading-relaxed scrollbar-hide"
                  style={{ caretColor: '#a9c7ff' }}
                  rows={1}
                  disabled={isLoading || isStreaming}
                />

                {/* Right Actions (Mic & Send) */}
                <div className="pr-3 py-3 flex items-center gap-2 self-end mb-[2px]">
                  
                  <ModelSelector
                    isOpen={showModelMenu}
                    onToggle={() => setShowModelMenu(!showModelMenu)}
                  />

                  {/* Speech Button */}
                  <div className="relative">
                    {speechError && (
                      <div className="absolute bottom-full mb-3 left-1/2 -translate-x-1/2 whitespace-nowrap bg-red-500/90 text-white text-[10px] px-2 py-1 rounded border border-red-400 backdrop-blur-sm z-50">
                        {speechError}
                      </div>
                    )}
                    <button
                      onClick={onToggleListening}
                      className={`p-2 rounded-xl transition-all duration-300 ${
                        isListening
                          ? "bg-red-500/20 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.4)] animate-pulse border border-red-500/50"
                          : "text-[#6e8cff] hover:text-[#a9c7ff] hover:bg-[#4d6dff]/10"
                      }`}
                    >
                      {isListening ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
                    </button>
                  </div>

                  {/* Wormhole Send Button Wrapper */}
                  <div className="relative w-10 h-10 flex items-center justify-center">
                    {/* The animated border container */}
                    <div className={`absolute inset-0 rounded-xl overflow-hidden pointer-events-none transition-opacity duration-300 ${
                       (input.trim() || attachments.length > 0) && !isLoading ? 'opacity-100' : 'opacity-0'
                    }`}>
                      <div className="wormhole-spin w-full h-full relative"></div>
                    </div>

                    {/* The actual button */}
                    <button
                      onClick={onSend}
                      disabled={(!input.trim() && attachments.length === 0) || isLoading || isStreaming}
                      className={`relative z-10 w-9 h-9 flex items-center justify-center rounded-[10px] transition-all duration-300 ${
                         (input.trim() || attachments.length > 0) && !isLoading && !isStreaming
                          ? "bg-[#05071b] text-[#a9c7ff] hover:text-white" // Button sits on top of wormhole bg
                          : "bg-transparent text-[#6e8cff]/30"
                      }`}
                    >
                      <Send className="w-5 h-5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};