import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Smartphone, CheckCircle, XCircle, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getDeviceInfo, DeviceInfo } from "@/lib/api";
import { toast } from "sonner";

interface DeviceInfoDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const DeviceInfoDialog = ({ open, onOpenChange }: DeviceInfoDialogProps) => {
  const [deviceInfo, setDeviceInfo] = useState<DeviceInfo | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchDeviceInfo = async () => {
    setIsLoading(true);
    try {
      const info = await getDeviceInfo();
      setDeviceInfo(info);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to fetch device info: ${errorMessage}`);
      setDeviceInfo({
        connected: false,
        deviceName: "Error",
        deviceCount: 0,
        devices: [],
        error: errorMessage,
      });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      fetchDeviceInfo();
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[550px] glass-panel premium-border rounded-2xl">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/20 border border-primary/30">
              <Smartphone className="w-6 h-6 text-primary" />
            </div>
            Device Information
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            Current device connection status and details
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
            </div>
          ) : deviceInfo ? (
            <>
              {/* Connection Status */}
              <div className="flex items-center justify-between p-4 rounded-xl bg-background/25 border-2 border-border/50 backdrop-blur-sm">
                <div className="flex items-center gap-3">
                  {deviceInfo.connected ? (
                    <CheckCircle className="w-6 h-6 text-green-500" />
                  ) : (
                    <XCircle className="w-6 h-6 text-red-500" />
                  )}
                  <div>
                    <p className="font-semibold text-foreground">
                      {deviceInfo.connected ? "Device Connected" : "No Device Connected"}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {deviceInfo.connected
                        ? `${deviceInfo.deviceCount} device(s) detected`
                        : "Please connect a device via USB"}
                    </p>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={fetchDeviceInfo}
                  disabled={isLoading}
                  className="border-border/50 hover:border-primary/50"
                >
                  <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? "animate-spin" : ""}`} />
                  Refresh
                </Button>
              </div>

              {/* Device Details */}
              {deviceInfo.connected && deviceInfo.devices.length > 0 ? (
                <div className="space-y-3">
                  <h3 className="font-semibold text-foreground">Connected Device(s)</h3>
                  {deviceInfo.devices.map((device, idx) => (
                    <motion.div
                      key={device.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.1 }}
                      className="p-4 rounded-xl bg-gradient-to-br from-primary/10 to-secondary/10 border-2 border-primary/20"
                    >
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium text-muted-foreground">Device Name:</span>
                          <span className="text-base font-bold text-foreground">{device.name}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium text-muted-foreground">Device ID:</span>
                          <span className="text-xs font-mono text-foreground/70 bg-background/30 px-2 py-1 rounded">
                            {device.id}
                          </span>
                        </div>
                        {device.model && (
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium text-muted-foreground">Model:</span>
                            <span className="text-sm text-foreground">{device.model}</span>
                          </div>
                        )}
                        {device.brand && (
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium text-muted-foreground">Brand:</span>
                            <span className="text-sm text-foreground">{device.brand}</span>
                          </div>
                        )}
                      </div>
                    </motion.div>
                  ))}
                </div>
              ) : (
                <div className="p-6 rounded-xl bg-muted/25 border-2 border-dashed border-border/50 text-center backdrop-blur-sm">
                  <XCircle className="w-12 h-12 text-muted-foreground/50 mx-auto mb-3" />
                  <p className="font-semibold text-foreground mb-2">No Device Connected</p>
                  <p className="text-sm text-muted-foreground mb-4">
                    {deviceInfo.message || "Please connect an Android device via USB and enable USB debugging."}
                  </p>
                  <div className="text-left space-y-2 text-xs text-muted-foreground bg-background/25 p-3 rounded-lg backdrop-blur-sm">
                    <p className="font-semibold">Steps to connect:</p>
                    <ol className="list-decimal list-inside space-y-1 ml-2">
                      <li>Connect your Android device via USB cable</li>
                      <li>Enable USB debugging on your device</li>
                      <li>Accept the USB debugging authorization prompt</li>
                      <li>Click Refresh to check connection</li>
                    </ol>
                  </div>
                </div>
              )}

              {/* Error Message */}
              {deviceInfo.error && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30">
                  <p className="text-sm text-red-500 font-medium">Error: {deviceInfo.error}</p>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <p>Unable to load device information</p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

