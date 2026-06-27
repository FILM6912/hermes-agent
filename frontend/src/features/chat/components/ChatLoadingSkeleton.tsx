import React from "react";

export const ChatLoadingSkeleton: React.FC = () => {
  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex gap-4">
        <div className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-800 animate-pulse flex-shrink-0"></div>
        <div className="flex-1 space-y-3">
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse w-3/4"></div>
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse w-1/2"></div>
        </div>
      </div>

      <div className="flex gap-4 justify-end">
        <div className="flex-1 max-w-[80%] space-y-3">
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse w-full ml-auto"></div>
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse w-2/3 ml-auto"></div>
        </div>
        <div className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-800 animate-pulse flex-shrink-0"></div>
      </div>

      <div className="flex gap-4">
        <div className="w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-800 animate-pulse flex-shrink-0"></div>
        <div className="flex-1 space-y-3">
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse w-5/6"></div>
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse w-3/5"></div>
          <div className="h-4 bg-zinc-200 dark:bg-zinc-800 rounded-lg animate-pulse w-2/3"></div>
        </div>
      </div>
    </div>
  );
};
