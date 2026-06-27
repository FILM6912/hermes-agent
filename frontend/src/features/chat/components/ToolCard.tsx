import React from "react";
import { ProcessStep } from "@/types";
import { ProcessStep as ProcessStepView } from "@/features/preview/components/ProcessStep";

interface ToolCardProps {
  step: ProcessStep;
  isLastStep?: boolean;
  forceExpanded?: boolean;
  onOpenInPanel?: (step: ProcessStep) => void;
}

/** Tool / command trace card for assistant transcript (M34). */
export const ToolCard: React.FC<ToolCardProps> = ({
  step,
  isLastStep = false,
  forceExpanded = false,
  onOpenInPanel,
}) => (
  <ProcessStepView
    step={step}
    isLastStep={isLastStep}
    forceExpanded={forceExpanded}
    onOpenInPanel={onOpenInPanel}
  />
);
