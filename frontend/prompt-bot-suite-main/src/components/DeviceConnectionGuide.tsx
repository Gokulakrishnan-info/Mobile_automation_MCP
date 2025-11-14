import { motion } from "framer-motion";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Smartphone,
  Settings,
  Usb,
  CheckCircle,
  ChevronRight,
  SmartphoneCharging,
  ShieldCheck,
  Laptop,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useState, useEffect } from "react";

interface DeviceConnectionGuideProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Step {
  number: number;
  title: string;
  description: string;
  details: string[];
  icon: React.ComponentType<{ className?: string }>;
}

const renderSteps = (steps: Step[], delayOffset = 0) => {
  return steps.map((step, idx) => {
    const Icon = step.icon;
    return (
      <motion.div
        key={`${step.number}-${step.title}`}
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: delayOffset + idx * 0.1 }}
        className="p-5 rounded-xl bg-gradient-to-br from-background/15 to-background/10 border-2 border-border/50 backdrop-blur-sm"
      >
        <div className="flex items-start gap-4">
          {/* Step Number Circle */}
          <div className="flex-shrink-0">
            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-primary/20 to-secondary/20 border-2 border-primary/30 flex items-center justify-center">
              <span className="text-lg font-bold text-primary">{step.number}</span>
            </div>
          </div>

          {/* Step Content */}
          <div className="flex-1 space-y-3">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10 border border-primary/20">
                <Icon className="w-5 h-5 text-primary" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-foreground">{step.title}</h3>
                <p className="text-sm text-muted-foreground">{step.description}</p>
              </div>
            </div>

            {/* Step Details */}
            <div className="ml-11 space-y-2">
              {step.details.map((detail, detailIdx) => (
                <motion.div
                  key={detailIdx}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: delayOffset + idx * 0.1 + detailIdx * 0.05 }}
                  className="flex items-start gap-2 text-sm text-foreground/90"
                >
                  <ChevronRight className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
                  <span>{detail}</span>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </motion.div>
    );
  });
};

export const DeviceConnectionGuide = ({ open, onOpenChange }: DeviceConnectionGuideProps) => {
  const [selectedPlatform, setSelectedPlatform] = useState<"android" | "ios" | null>(null);

  // Reset selection when dialog opens
  useEffect(() => {
    if (open) {
      setSelectedPlatform(null);
    }
  }, [open]);

  const androidSteps: Step[] = [
    {
      number: 1,
      title: "Enable Developer Options",
      description: "Open Settings on your Android device",
      details: [
        "Go to Settings → About Phone",
        "Find 'Build Number' (usually at the bottom)",
        "Tap 'Build Number' 7 times",
        "You'll see a message: 'You are now a developer!'",
      ],
      icon: Settings,
    },
    {
      number: 2,
      title: "Enable USB Debugging",
      description: "Turn on USB debugging in Developer Options",
      details: [
        "Go back to Settings → System → Developer Options",
        "Find 'USB Debugging'",
        "Toggle it ON",
        "Confirm the warning dialog if prompted",
      ],
      icon: Smartphone,
    },
    {
      number: 3,
      title: "Connect Your Device",
      description: "Connect your Android device to your computer via USB cable",
      details: [
        "Use a USB cable to connect your device to your computer",
        "Make sure the cable supports data transfer (not just charging)",
        "On your device, select 'File Transfer' or 'MTP' mode when prompted",
      ],
      icon: Usb,
    },
    {
      number: 4,
      title: "Authorize USB Debugging",
      description: "Allow USB debugging on your computer",
      details: [
        "A popup will appear on your device: 'Allow USB debugging?'",
        "Check 'Always allow from this computer' (optional but recommended)",
        "Tap 'OK' or 'Allow'",
      ],
      icon: CheckCircle,
    },
    {
      number: 5,
      title: "Verify Connection",
      description: "Check if your device is detected",
      details: [
        "Click the 'Device' badge in the header to check connection status",
        "Or run this command in terminal: adb devices",
        "You should see your device listed",
      ],
      icon: CheckCircle,
    },
  ];

  const iosSteps: Step[] = [
    {
      number: 1,
      title: "Install Prerequisites",
      description: "Set up iOS tooling on your Mac",
      details: [
        "Install Xcode from the App Store (Xcode 14 or newer)",
        "Install Xcode command line tools: xcode-select --install",
        "Install Homebrew if not already installed (brew.sh)",
      ],
      icon: Laptop,
    },
    {
      number: 2,
      title: "Enable Developer Mode",
      description: "Prepare your physical iOS device for testing",
      details: [
        "Connect your iPhone/iPad via USB",
        "Open Settings → Privacy & Security → Developer Mode",
        "Toggle Developer Mode on, then restart your device",
        "After restart, enable Developer Mode when prompted",
      ],
      icon: SmartphoneCharging,
    },
    {
      number: 3,
      title: "Trust This Computer",
      description: "Establish a secure pairing",
      details: [
        "When prompted on the device, tap 'Trust'",
        "Enter your device passcode to confirm",
        "On macOS, open Finder and ensure the device appears under 'Locations'",
      ],
      icon: ShieldCheck,
    },
    {
      number: 4,
      title: "Register Device in Xcode",
      description: "Let Xcode configure your device for development",
      details: [
        "Open Xcode → Window → Devices and Simulators",
        "Ensure your device shows up and is paired",
        "Wait for Xcode to finish processing/setting up the device",
      ],
      icon: Laptop,
    },
    {
      number: 5,
      title: "Start WebDriverAgent / Web Inspector",
      description: "Prepare for Appium connections",
      details: [
        "For Appium, build WebDriverAgent once via Xcode (Product → Build)",
        "Enable Web Inspector: Settings → Safari → Advanced → Web Inspector (for web automation)",
        "Once done, your device is ready for automation sessions",
      ],
      icon: RefreshCw,
    },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[700px] glass-panel premium-border rounded-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader className="space-y-1.5">
          <DialogTitle className="text-2xl font-bold flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/20 border border-primary/30">
                <Smartphone className="w-6 h-6 text-primary" />
              </div>
              Device Connection Guide
            </div>
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {selectedPlatform
              ? `Follow these steps to connect your ${selectedPlatform === "android" ? "Android" : "iOS"} device for automation.`
              : "Select your device platform to view connection instructions."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {!selectedPlatform ? (
            // Platform Selection Screen
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="space-y-4"
            >
              <div className="text-center mb-6">
                <p className="text-lg font-semibold text-foreground mb-2">
                  Choose Your Device Platform
                </p>
                <p className="text-sm text-muted-foreground">
                  Select Android or iOS to view platform-specific connection instructions
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Android Option */}
                <motion.button
                  onClick={() => setSelectedPlatform("android")}
                  whileHover={{ scale: 1.02, y: -2 }}
                  whileTap={{ scale: 0.98 }}
                  className="p-6 rounded-xl bg-gradient-to-br from-background/15 to-background/10 border-2 border-border/50 hover:border-primary/50 transition-all text-left group cursor-pointer backdrop-blur-sm"
                >
                  <div className="flex flex-col items-center text-center space-y-4">
                    <div className="p-4 rounded-xl bg-gradient-to-br from-green-500/20 to-emerald-500/20 border-2 border-green-500/30 group-hover:border-green-500/50 transition-all">
                      <Smartphone className="w-12 h-12 text-green-500" />
                    </div>
                    <div>
                      <h3 className="text-xl font-bold text-foreground mb-1">Android</h3>
                      <p className="text-sm text-muted-foreground">
                        Connect your Android phone or tablet
                      </p>
                    </div>
                    <div className="flex items-center gap-2 text-primary font-semibold text-sm">
                      <span>View Instructions</span>
                      <ChevronRight className="w-4 h-4" />
                    </div>
                  </div>
                </motion.button>

                {/* iOS Option */}
                <motion.button
                  onClick={() => setSelectedPlatform("ios")}
                  whileHover={{ scale: 1.02, y: -2 }}
                  whileTap={{ scale: 0.98 }}
                  className="p-6 rounded-xl bg-gradient-to-br from-background/15 to-background/10 border-2 border-border/50 hover:border-primary/50 transition-all text-left group cursor-pointer backdrop-blur-sm"
                >
                  <div className="flex flex-col items-center text-center space-y-4">
                    <div className="p-4 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 border-2 border-blue-500/30 group-hover:border-blue-500/50 transition-all">
                      <SmartphoneCharging className="w-12 h-12 text-blue-500" />
                    </div>
                    <div>
                      <h3 className="text-xl font-bold text-foreground mb-1">iOS</h3>
                      <p className="text-sm text-muted-foreground">
                        Connect your iPhone or iPad
                      </p>
                    </div>
                    <div className="flex items-center gap-2 text-primary font-semibold text-sm">
                      <span>View Instructions</span>
                      <ChevronRight className="w-4 h-4" />
                    </div>
                  </div>
                </motion.button>
              </div>
            </motion.div>
          ) : (
            // Selected Platform Instructions
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className="space-y-6"
            >
              {/* Back Button */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSelectedPlatform(null)}
                className="mb-2"
              >
                <ChevronRight className="w-4 h-4 mr-2 rotate-180" />
                Back to Platform Selection
              </Button>

              {/* Platform Header */}
              <div className="flex items-center gap-3 pb-2 border-b border-border/50">
                <div className={`p-2 rounded-xl ${
                  selectedPlatform === "android"
                    ? "bg-gradient-to-br from-green-500/20 to-emerald-500/20 border-2 border-green-500/30"
                    : "bg-gradient-to-br from-blue-500/20 to-cyan-500/20 border-2 border-blue-500/30"
                }`}>
                  {selectedPlatform === "android" ? (
                    <Smartphone className="w-6 h-6 text-green-500" />
                  ) : (
                    <SmartphoneCharging className="w-6 h-6 text-blue-500" />
                  )}
                </div>
                <div>
                  <h2 className="text-xl font-bold text-foreground">
                    {selectedPlatform === "android" ? "Android" : "iOS"} Setup Instructions
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    Follow these steps to connect your device
                  </p>
                </div>
              </div>

              {/* Steps */}
              <section className="space-y-4">
                {renderSteps(selectedPlatform === "android" ? androidSteps : iosSteps)}
              </section>

              {/* Additional Tips */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.6 }}
                className="p-4 rounded-xl bg-primary/10 border-2 border-primary/20 backdrop-blur-sm"
              >
                <h4 className="font-bold text-foreground mb-2 flex items-center gap-2">
                  <CheckCircle className="w-5 h-5 text-primary" />
                  Pro Tips
                </h4>
                <ul className="space-y-1.5 text-sm text-muted-foreground ml-7">
                  {selectedPlatform === "android" ? (
                    <>
                      <li>• Keep USB Debugging enabled for easier reconnection</li>
                      <li>• Use a high-quality USB cable for stable connection</li>
                      <li>• If device is not detected, try a different USB port</li>
                      <li>• Some devices require 'PTP' mode instead of 'MTP'</li>
                      <li>• Restart ADB if connection issues persist: <code className="bg-background/30 px-1.5 py-0.5 rounded text-xs">adb kill-server && adb start-server</code></li>
                    </>
                  ) : (
                    <>
                      <li>• Keep developer options enabled on devices used for automation</li>
                      <li>• For iOS real devices, ensure your Apple developer profile is trusted annually</li>
                      <li>• Use high-quality Lightning/USB-C cables for stable connections</li>
                      <li>• If connections fail, reboot the device and restart Appium/Xcode</li>
                      <li>• Maintain separate automation Apple IDs to avoid personal account disruptions</li>
                    </>
                  )}
                </ul>
              </motion.div>

              {/* Troubleshooting */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.7 }}
                className="p-4 rounded-xl bg-muted/25 border-2 border-border/50 backdrop-blur-sm"
              >
                <h4 className="font-bold text-foreground mb-2">Troubleshooting</h4>
                <div className="space-y-2 text-sm text-muted-foreground">
                  <p><strong className="text-foreground">Device not showing up?</strong></p>
                  <ul className="list-disc list-inside ml-2 space-y-1">
                    {selectedPlatform === "android" ? (
                      <>
                        <li>Check if USB drivers are installed (for Windows)</li>
                        <li>Try different USB cable or port</li>
                        <li>Revoke USB debugging authorizations and reconnect</li>
                        <li>Restart both device and computer</li>
                      </>
                    ) : (
                      <>
                        <li>Check if Xcode and command line tools are properly installed</li>
                        <li>Try a different USB cable or port; avoid USB hubs when possible</li>
                        <li>Re-trust the computer in device settings, then reconnect</li>
                        <li>Restart the device and automation services (Appium server, Xcode, etc.)</li>
                      </>
                    )}
                  </ul>
                </div>
              </motion.div>
            </motion.div>
          )}
        </div>

        <div className="flex justify-end pt-4 border-t border-border/50">
          <Button
            onClick={() => onOpenChange(false)}
            className="bg-gradient-to-r from-primary to-secondary hover:opacity-90"
          >
            Got it!
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

