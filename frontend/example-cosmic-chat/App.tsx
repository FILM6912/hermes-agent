import React, { useState, useRef } from 'react';
import { ChatInput } from './components/ChatInput';
import { Attachment } from './types';

function App() {
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const mcpMenuRef = useRef<HTMLDivElement>(null);

  const [isListening, setIsListening] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  
  // Handlers
  const handleSend = () => {
    console.log("Sending:", input);
    setInput("");
    setAttachments([]);
    if(textareaRef.current) textareaRef.current.style.height = "auto";
  };

  return (
    <div className="relative min-h-screen w-full bg-[#020205] text-white flex flex-col items-center justify-center overflow-hidden">
      {/* Background decoration to show transparency */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-purple-900/10 rounded-full blur-[100px]"></div>
      
      <div className="z-10 text-center mb-20 space-y-4">
        <h1 className="text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-[#a9c7ff] to-[#4d6dff]">
          Cosmic Chat
        </h1>
        <p className="text-[#6e8cff]">Interact with the void.</p>
      </div>

      <ChatInput
        input={input}
        setInput={setInput}
        attachments={attachments}
        onRemoveAttachment={(i) => setAttachments(prev => prev.filter((_, idx) => idx !== i))}
        onSend={handleSend}
        onFileSelect={() => {}}
        onPaste={() => {}}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
        onDrop={(e) => { e.preventDefault(); setIsDragging(false); }}
        isDragging={isDragging}
        isLoading={false}
        isStreaming={false}
        isListening={isListening}
        speechError={null}
        onToggleListening={() => setIsListening(!isListening)}
        textareaRef={textareaRef}
        fileInputRef={fileInputRef}
        showModelMenu={false}
        setShowModelMenu={() => {}}
        modelConfig={{}}
        agentModels={[]}
        pinnedAgentId={null}
        onModelSelect={() => {}}
        onPinAgent={() => {}}
        modelMenuRef={modelMenuRef}
        showMcpMenu={false}
        setShowMcpMenu={() => {}}
        mcpServers={[]}
        mcpMenuRef={mcpMenuRef}
      />
    </div>
  );
}

export default App;