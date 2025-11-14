import { motion } from "framer-motion";
import { Square } from "lucide-react";
import { StatusBadge } from "./StatusBadge";
import { DeviceInfoDialog } from "./DeviceInfoDialog";
import { DeviceConnectionGuide } from "./DeviceConnectionGuide";
import { Button } from "@/components/ui/button";
import { useState } from "react";

interface DashboardHeaderProps {
  modelStatus: "connected" | "disconnected";
  deviceStatus: "connected" | "disconnected";
  isRunning: boolean;
  onStop?: () => void;
}

export const DashboardHeader = ({ modelStatus, deviceStatus, isRunning, onStop }: DashboardHeaderProps) => {
  const [showDeviceDialog, setShowDeviceDialog] = useState(false);
  const [showConnectionGuide, setShowConnectionGuide] = useState(false);
  return (
    <motion.header
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="glass-panel sticky top-0 z-50 border-b shrink-0 premium-shadow"
    >
      <div className="w-full px-4 py-4">
        <div className="flex items-center gap-4 w-full">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 260, damping: 20 }}
            className="relative h-14 flex items-center"
          >
            <img
              src="/company-logo.png"
              alt="Company Logo"
              className="h-full w-auto object-contain"
              style={{
                mixBlendMode: 'screen',
                filter: 'drop-shadow(0 0 0 transparent)',
              }}
              loading="lazy"
            />
          </motion.div>

          <div className="flex-1 flex flex-col items-center justify-center px-2 text-center">
            <h1 className="text-2xl font-bold text-white leading-tight tracking-tight">
                AI-Powered Mobile Testing
            </h1>
            <p className="text-xs text-white/80 leading-tight font-medium mt-0.5">
              Intelligent automation orchestrator
            </p>
          </div>

          <div className="flex items-center gap-3 ml-auto">
            <motion.div
              whileHover={{ scale: 1.08, y: -2 }}
              whileTap={{ scale: 0.95 }}
              transition={{ type: "spring", stiffness: 400, damping: 17 }}
              onClick={() => setShowConnectionGuide(true)}
              className="cursor-pointer"
            >
              <StatusBadge
                status="connected"
                label="Setup Guide"
              />
            </motion.div>
            <DeviceConnectionGuide
              open={showConnectionGuide}
              onOpenChange={setShowConnectionGuide}
            />
            <motion.div
              whileHover={{ scale: 1.08, y: -2 }}
              whileTap={{ scale: 0.95 }}
              transition={{ type: "spring", stiffness: 400, damping: 17 }}
              onClick={() => setShowDeviceDialog(true)}
              className="cursor-pointer"
            >
              <StatusBadge
                status={deviceStatus}
                label={deviceStatus === "connected" ? "Device" : "Offline"}
              />
            </motion.div>
            <DeviceInfoDialog
              open={showDeviceDialog}
              onOpenChange={setShowDeviceDialog}
            />
            <motion.div
              whileHover={{ scale: 1.08, y: -2 }}
              whileTap={{ scale: 0.95 }}
              transition={{ type: "spring", stiffness: 400, damping: 17 }}
            >
              <StatusBadge
                status={isRunning ? "running" : "idle"}
                label={isRunning ? "Running" : "Ready"}
              />
            </motion.div>
            {isRunning && onStop && (
              <motion.div
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                transition={{ type: "spring", stiffness: 400, damping: 17 }}
              >
                <Button
                  onClick={onStop}
                  variant="destructive"
                  size="sm"
                  className="bg-destructive hover:bg-destructive/90 text-destructive-foreground font-semibold shadow-lg glow-primary"
                >
                  <Square className="w-4 h-4 mr-2" />
                  Stop
                </Button>
              </motion.div>
            )}
          </div>
        </div>
      </div>
    </motion.header>
  );
};
