import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { Terminal } from "lucide-react";
import { LogEntry } from "./LogEntry";
import { ScrollArea } from "@/components/ui/scroll-area";
import { HelpTooltip } from "./HelpTooltip";

interface Log {
  id: string;
  timestamp: string;
  type: "success" | "error" | "info" | "action";
  message: string;
  details?: string;
}

interface LogsPanelProps {
  logs: Log[];
}

export const LogsPanel = ({ logs }: LogsPanelProps) => {
  const scrollViewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Auto-scroll to bottom when new logs arrive
    const timeout = setTimeout(() => {
      if (scrollViewportRef.current) {
        const viewport = scrollViewportRef.current.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement;
        if (viewport) {
          viewport.scrollTop = viewport.scrollHeight;
        }
      }
    }, 50);
    return () => clearTimeout(timeout);
  }, [logs]);

  return (
    <motion.div
      initial={{ x: 20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      whileHover={{ boxShadow: "0 0 40px hsl(var(--glow-primary) / 0.25)" }}
      className="glass-panel rounded-2xl p-5 h-full flex flex-col interactive-card premium-border"
    >
      <div className="flex items-center gap-3 mb-4 flex-shrink-0">
        <motion.div
          animate={{ rotate: [0, 5, -5, 0] }}
          transition={{ duration: 2, repeat: Infinity, repeatDelay: 3 }}
          className="p-2 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/20 border border-primary/30"
        >
          <Terminal className="w-5 h-5 text-primary" />
        </motion.div>
        <div className="flex-1">
          <h2 className="text-xl font-bold text-foreground">Live Console</h2>
          <p className="text-xs text-muted-foreground/70 mt-0.5">Real-time automation logs</p>
        </div>
        <HelpTooltip content="Watch real-time AI decision-making and automation steps. Green = success, Red = error, Yellow = action, Blue = info." />
        <motion.span 
          animate={{ opacity: [0.7, 1, 0.7] }}
          transition={{ duration: 2, repeat: Infinity }}
          className="text-xs font-bold px-3 py-1.5 rounded-full bg-gradient-to-r from-primary/20 to-secondary/20 border border-primary/30 text-primary"
        >
          {logs.length}
        </motion.span>
      </div>

      <div className="flex-1 overflow-hidden flex flex-col bg-background/25 rounded-xl border-2 border-border/30 shadow-inner backdrop-blur-sm" ref={scrollViewportRef}>
        <ScrollArea className="flex-1 h-full w-full">
          <div className="space-y-2 p-3 min-w-0">
            {logs.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full min-h-[300px] text-center p-8">
                <motion.div
                  animate={{ opacity: [0.5, 1, 0.5] }}
                  transition={{ duration: 2, repeat: Infinity }}
                  className="mb-4"
                >
                  <Terminal className="w-12 h-12 text-muted-foreground/30 mx-auto" />
                </motion.div>
                <p className="text-sm font-medium text-muted-foreground mb-2">
                  No logs yet
                </p>
                <p className="text-xs text-muted-foreground/70 max-w-xs">
                  When you run an automation, you'll see real-time logs of every action, decision, and result here
                </p>
              </div>
            ) : (
              logs.map((log) => (
                <LogEntry
                  key={log.id}
                  timestamp={log.timestamp}
                  type={log.type}
                  message={log.message}
                  details={log.details}
                />
              ))
            )}
          </div>
        </ScrollArea>
      </div>
    </motion.div>
  );
};
