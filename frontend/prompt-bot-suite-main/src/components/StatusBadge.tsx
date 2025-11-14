import { motion } from "framer-motion";

interface StatusBadgeProps {
  status: "connected" | "disconnected" | "running" | "idle";
  label: string;
}

export const StatusBadge = ({ status, label }: StatusBadgeProps) => {
  const statusConfig = {
    connected: { bgColor: "bg-success/20" },
    disconnected: { bgColor: "bg-destructive/20" },
    running: { bgColor: "bg-warning/20" },
    idle: { bgColor: "bg-muted/20" },
  };

  const config = statusConfig[status];

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      whileHover={{ scale: 1.05 }}
      className={`flex items-center gap-2 px-3 py-1.5 rounded-full ${config.bgColor} backdrop-blur-sm border border-border/50 transition-all duration-300 hover:border-border/80`}
    >
      <span className="text-sm font-medium text-white">{label}</span>
    </motion.div>
  );
};
