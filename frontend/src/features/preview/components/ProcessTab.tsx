import React, { useRef, useEffect } from "react";
import { Terminal } from "lucide-react";
import { ProcessStep as ProcessStepType } from "@/types";
import { ProcessStepCard } from "./ProcessStepCard";
import { useLanguage } from "@/hooks/useLanguage";

interface ProcessTabProps {
  steps?: ProcessStepType[];
}

export const ProcessTab: React.FC<ProcessTabProps> = ({ steps }) => {
  const { t } = useLanguage();
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [steps]);

  return (
    <div className="w-full h-full flex flex-col bg-[#050506] transition-colors duration-200 relative">
      {/* Decorative Background Elements */}
      <div className="absolute top-0 left-0 w-full h-full pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-indigo-500/10 blur-[120px] rounded-full" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-purple-500/10 blur-[120px] rounded-full" />
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-8 scrollbar-thin scrollbar-thumb-white/10 relative z-10">
        <div className="w-full space-y-0 pb-32">
          {steps && steps.length > 0 ? (
            steps.map((step, index) => (
              <ProcessStepCard 
                key={step.id} 
                step={step} 
                isLastStep={index === steps.length - 1}
              />
            ))
          ) : (
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-zinc-500 animate-in fade-in duration-700">
              <div className="bg-[#141416] rounded-2xl p-4 border border-white/3 flex items-center justify-center mb-6 shadow-2xl relative group">
                <div className="absolute inset-0 bg-indigo-500/20 blur-2xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                <Terminal className="w-8 h-8 opacity-40 relative z-10" />
              </div>
              <p className="text-sm font-semibold opacity-40 tracking-[0.2em] uppercase">
                {t("preview.waitingForAgent")}
              </p>
            </div>
          )}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
};
