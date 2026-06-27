import { useState } from "react";

type Log = {
  time: string;
  type: "system" | "info" | "success" | "error" | "warning";
  msg: string;
};

const formatTime = (d: Date) =>
  d.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

const getInitialLogs = (): Log[] => {
  const now = new Date();
  const t = (offsetSeconds: number) => {
    const d = new Date(now.getTime() - offsetSeconds * 1000);
    return formatTime(d);
  };

  return [
    { time: t(5), type: "system", msg: "System initialized" },
    { time: t(4), type: "info", msg: "Loading configuration..." },
    { time: t(3), type: "success", msg: "Configuration loaded" },
  ];
};

export const useTerminalLogs = () => {
  const [logs, setLogs] = useState<Log[]>(getInitialLogs());

  const addLog = (type: Log["type"], msg: string) => {
    setLogs((prev) => [...prev, { time: formatTime(new Date()), type, msg }]);
  };

  const clearLogs = () => {
    setLogs(getInitialLogs());
  };

  return {
    logs,
    addLog,
    clearLogs,
  };
};
