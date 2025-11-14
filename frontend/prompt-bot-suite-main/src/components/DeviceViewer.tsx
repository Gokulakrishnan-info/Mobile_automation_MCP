import { motion } from "framer-motion";
import { Smartphone, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useState, useEffect, useRef } from "react";
import { HelpTooltip } from "./HelpTooltip";

interface DeviceViewerProps {
  screenUrl?: string;
  onRefresh: () => void;
  isLoading: boolean;
  deviceType?: "android" | "ios" | null;
  deviceName?: string | null;
  isTablet?: boolean;
}

type DeviceConfig = {
  type: "phone" | "phablet" | "tablet";
  maxWidth: string;
  bezelRounded: string;
  screenRounded: string;
  padding: string;
  borderWidth: string;
  notchWidth: string;
  notchHeight: string;
  defaultAspectRatio: number;
};

export const DeviceViewer = ({
  screenUrl,
  onRefresh,
  isLoading,
  deviceType,
  deviceName,
  isTablet,
}: DeviceViewerProps) => {
  const [imageError, setImageError] = useState(false);
  const [displayUrl, setDisplayUrl] = useState<string | undefined>(screenUrl);
  const [imageAspectRatio, setImageAspectRatio] = useState<number | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  const getDeviceConfig = (): DeviceConfig => {
    const name = (deviceName || "").toLowerCase();

    // Tablet / iPad profile (prefer explicit flag or name detection, fallback to heuristic)
    if (isTablet || name.includes("tablet") || name.includes("ipad") || name.includes("tab")) {
      return {
        type: "tablet",
        maxWidth: "420px",
        bezelRounded: "rounded-[2.25rem]",
        screenRounded: "rounded-[1.75rem]",
        padding: "p-6",
        borderWidth: "border-[6px]",
        notchWidth: "w-40",
        notchHeight: "h-8",
        defaultAspectRatio: 4 / 3,
      };
    }

    // Large phones / phablets
    if (name.includes("max") || name.includes("plus") || name.includes("pro max")) {
      return {
        type: "phablet",
        maxWidth: "340px",
        bezelRounded: "rounded-[2.35rem]",
        screenRounded: "rounded-[1.85rem]",
        padding: "p-5",
        borderWidth: "border-[5px]",
        notchWidth: "w-36",
        notchHeight: "h-6",
        defaultAspectRatio: 9 / 19.5,
      };
    }

    // Default phone profile
    return {
      type: "phone",
      maxWidth: "300px",
      bezelRounded: "rounded-[2.4rem]",
      screenRounded: "rounded-[1.9rem]",
      padding: "p-5",
      borderWidth: "border-[5px]",
      notchWidth: "w-32",
      notchHeight: "h-6",
      defaultAspectRatio: 9 / 19.5,
    };
  };

  const deviceConfig = getDeviceConfig();
  
  // Update image URL immediately for low latency (optimized for live screen)
  useEffect(() => {
    if (screenUrl) {
      // For live screen updates, update immediately without preloading
      // The timestamp in URL ensures browser fetches fresh image
      if (screenUrl !== displayUrl) {
        setDisplayUrl(screenUrl);
      }
    } else {
      setDisplayUrl(undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screenUrl]);

  return (
    <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      whileHover={{ boxShadow: "0 0 40px hsl(var(--glow-secondary) / 0.25)" }}
      className="glass-panel rounded-2xl p-6 interactive-card h-full flex flex-col premium-border"
    >
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-gradient-to-br from-secondary/20 to-primary/20 border border-secondary/30">
            <Smartphone className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Device Screen</h2>
            <p className="text-xs text-muted-foreground/70 mt-0.5">Live preview</p>
          </div>
          {deviceName ? (
            <span className="text-xs font-semibold px-3 py-1.5 rounded-full bg-gradient-to-r from-primary/20 to-secondary/20 border border-primary/30 text-primary">
              {deviceName}
            </span>
          ) : deviceType && (
            <span className="text-xs font-semibold px-3 py-1.5 rounded-full bg-gradient-to-r from-primary/20 to-secondary/20 border border-primary/30 text-primary">
              {deviceType === "android" ? "Android" : "iOS"}
            </span>
          )}
          <HelpTooltip content="Live preview of your device screen. Updates automatically during automation or click refresh to see current state." />
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={isLoading}
          className="border-border/50 hover:border-primary/50"
        >
            <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Device Frame - Adaptive Size */}
      <div
        className={`relative mx-auto flex-1 flex items-center`}
        style={{ maxWidth: deviceConfig.maxWidth }}
      >
        {/* Device Bezel */}
        <div
          className={`relative bg-gradient-to-b from-slate-800 to-slate-900 ${deviceConfig.bezelRounded} ${deviceConfig.padding} shadow-2xl w-full`}
        >
          {/* Screen Notch */}
          <div
            className={`absolute top-0 left-1/2 -translate-x-1/2 ${deviceConfig.notchWidth} ${deviceConfig.notchHeight} bg-slate-900 rounded-b-3xl z-10`}
          />

          {/* Screen */}
          <div
            className={`relative bg-background/20 ${deviceConfig.screenRounded} overflow-hidden ${deviceConfig.borderWidth} border-slate-900`}
            style={{
              aspectRatio: imageAspectRatio ?? deviceConfig.defaultAspectRatio,
            }}
          >
            {displayUrl && !imageError ? (
              <img
                ref={imgRef}
                src={displayUrl}
                alt="Device Screen"
                className="w-full h-full object-cover"
                onError={() => setImageError(true)}
                onLoad={(event) => {
                  setImageError(false);
                  const { naturalWidth, naturalHeight } = event.currentTarget;
                  if (naturalWidth && naturalHeight) {
                    setImageAspectRatio(naturalWidth / naturalHeight);
                  }
                }}
                style={{ 
                  imageRendering: 'auto',
                  display: 'block',
                  opacity: 1,
                  transition: 'opacity 0.05s ease-in-out'
                }}
                loading="eager"
                decoding="async"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center bg-muted/10">
                <div className="text-center space-y-4 p-8">
                  <motion.div
                    animate={{ y: [0, -10, 0] }}
                    transition={{ duration: 2, repeat: Infinity }}
                  >
                    <Smartphone className="w-16 h-16 mx-auto text-muted-foreground/30" />
                  </motion.div>
                  <div>
                    <p className="text-sm font-medium text-muted-foreground mb-2">
                      {imageError ? "Failed to load screen" : "Waiting for device..."}
                    </p>
                    <p className="text-xs text-muted-foreground/70 mb-3">
                      {imageError 
                        ? "Try refreshing to reconnect" 
                        : "Device screen will appear here once automation starts"}
                    </p>
                    {!imageError && (
                      <div className="inline-flex items-center gap-2 text-xs text-primary bg-primary/10 px-3 py-1.5 rounded-full">
                        <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                        Ready to connect
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
            
            {/* Loading Overlay */}
            {isLoading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="absolute inset-0 bg-background/20 backdrop-blur-sm flex items-center justify-center"
              >
                <div className="text-center space-y-2">
                  <RefreshCw className="w-8 h-8 animate-spin text-primary mx-auto" />
                  <p className="text-sm text-muted-foreground">Updating screen...</p>
                </div>
              </motion.div>
            )}
          </div>

          {/* Power Button */}
          <div className="absolute right-0 top-24 w-1 h-12 bg-slate-700 rounded-l" />
          {/* Volume Buttons */}
          <div className="absolute left-0 top-20 w-1 h-8 bg-slate-700 rounded-r" />
          <div className="absolute left-0 top-32 w-1 h-8 bg-slate-700 rounded-r" />
        </div>
      </div>

      {/* Status Info */}
      <div className="mt-2 flex items-center justify-center gap-2 text-[10px] text-muted-foreground">
        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
        <span>Live Preview</span>
      </div>
    </motion.div>
  );
};
