import { motion } from "framer-motion";
import { ChevronDown, ChevronRight, CheckCircle, XCircle, Info, Zap } from "lucide-react";
import { useState } from "react";

interface LogEntryProps {
  timestamp: string;
  type: "success" | "error" | "info" | "action";
  message: string;
  details?: string;
}

export const LogEntry = ({ timestamp, type, message, details }: LogEntryProps) => {
  const [expanded, setExpanded] = useState(false);

  const typeConfig = {
    success: { 
      icon: CheckCircle, 
      color: "text-green-500", 
      bg: "bg-green-500/15", 
      border: "border-green-500/30",
      textColor: "text-green-50"
    },
    error: { 
      icon: XCircle, 
      color: "text-red-500", 
      bg: "bg-red-500/15", 
      border: "border-red-500/30",
      textColor: "text-red-50"
    },
    info: { 
      icon: Info, 
      color: "text-blue-500", 
      bg: "bg-blue-500/15", 
      border: "border-blue-500/30",
      textColor: "text-blue-50"
    },
    action: { 
      icon: Zap, 
      color: "text-yellow-500", 
      bg: "bg-yellow-500/15", 
      border: "border-yellow-500/30",
      textColor: "text-yellow-50"
    },
  };

  const config = typeConfig[type];
  const Icon = config.icon;

  // Clean up and format message for better readability
  const formatMessage = (msg: string): string => {
    // Remove redundant prefixes and clean up formatting
    let formatted = msg
      .replace(/^---\s*\[([^\]]+)\]\s*/, '[$1] ')
      .replace(/^---\s*/, '')
      .replace(/\s+/g, ' ')
      .trim();
    
    // Make step descriptions more readable
    if (formatted.includes('Step') && formatted.includes(':')) {
      formatted = formatted.replace(/Step\s+(\d+):\s*/, 'Step $1: ');
    }
    
    return formatted;
  };

  const formattedMessage = formatMessage(message);

  return (
    <motion.div
      initial={{ x: 10, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      whileHover={{ scale: 1.01, y: -2 }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
      className={`p-3.5 rounded-xl ${config.bg} border-2 ${config.border} hover:border-opacity-80 transition-all cursor-default group backdrop-blur-sm shadow-md hover:shadow-lg w-full max-w-full`}
    >
      <div className="flex items-start gap-2.5">
        <motion.div
          whileHover={{ scale: 1.2, rotate: 5 }}
          transition={{ duration: 0.2 }}
          className="mt-0.5 flex-shrink-0 p-1.5 rounded-lg bg-background/25 border border-border/30"
        >
          <Icon className={`w-5 h-5 ${config.color} drop-shadow-md`} />
        </motion.div>
        <div className="flex-1 min-w-0 w-full">
          <div className="flex flex-col gap-1.5 w-full">
            <div className="flex items-start justify-between gap-2 w-full">
              <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-start gap-2 text-left w-full group focus:outline-none"
              >
                <span className="mt-1 flex-shrink-0 text-muted-foreground">
                  {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                </span>
                <span
                  className="text-sm font-semibold text-foreground leading-relaxed flex-1 min-w-0"
                  style={{
                    wordBreak: "break-word",
                    overflowWrap: "anywhere",
                    hyphens: "auto",
                  }}
                >
                  {formattedMessage}
                </span>
              </button>
              <span className="text-[10px] font-mono font-bold text-muted-foreground/80 whitespace-nowrap flex-shrink-0 px-2 py-1 rounded-lg bg-background/30 border border-border/30 shadow-sm">
                {timestamp}
              </span>
            </div>

            {expanded && (
              <motion.pre
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                className="mt-2.5 p-4 bg-background/30 rounded-xl text-xs font-mono text-foreground/90 leading-relaxed overflow-x-auto border-2 border-border/50 max-h-64 overflow-y-auto shadow-inner whitespace-pre-wrap break-words backdrop-blur-sm"
                style={{
                  wordBreak: "break-word",
                  overflowWrap: "break-word",
                }}
              >
                {details ?? formattedMessage}
              </motion.pre>
            )}

            {details && !expanded && (
              <button
                onClick={() => setExpanded(true)}
                className="flex items-center gap-2 w-fit text-xs font-bold text-muted-foreground hover:text-foreground transition-all px-3 py-1.5 rounded-lg hover:bg-background/30 border border-border/40 hover:border-primary/40 hover:shadow-md"
              >
                <ChevronRight className="w-4 h-4" />
                Show details
              </button>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
};
