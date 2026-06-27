import React from "react";

interface AIIconProps {
  className?: string;
  size?: "sm" | "md" | "lg";
}

const sizeMap = {
  sm: "w-4 h-4",
  md: "w-8 h-8",
  lg: "w-10 h-10",
};

/** Modern AI icon: minimal friendly assistant face */
export const AIIcon: React.FC<AIIconProps> = ({ className = "", size = "md" }) => {
  const sizeClass = sizeMap[size];

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`${sizeClass} ${className}`}
      aria-hidden
    >
      {/* Head */}
      <circle cx="12" cy="12" r="9" strokeWidth="1.6" />
      {/* Eyes */}
      <circle cx="9" cy="10.5" r="1.4" fill="currentColor" />
      <circle cx="15" cy="10.5" r="1.4" fill="currentColor" />
      {/* Smile */}
      <path d="M8.5 14.5 a 4 2.5 0 0 1 7 0" strokeWidth="1.4" fill="none" />
    </svg>
  );
};
