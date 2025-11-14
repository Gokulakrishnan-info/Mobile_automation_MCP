import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

export const WelcomeGuide = () => {
  const [showGuide, setShowGuide] = useState(false);

  useEffect(() => {
    const hasSeenGuide = localStorage.getItem("hasSeenWelcomeGuide");
    if (!hasSeenGuide) {
      setShowGuide(true);
    }
  }, []);

  const handleClose = () => {
    localStorage.setItem("hasSeenWelcomeGuide", "true");
    setShowGuide(false);
  };

  return (
    <AnimatePresence>
      {showGuide && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={handleClose}
        >
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
            className="glass-panel rounded-2xl p-8 max-w-2xl w-full relative"
          >
            <Button
              variant="ghost"
              size="icon"
              onClick={handleClose}
              className="absolute top-4 right-4"
            >
              <X className="w-5 h-5" />
            </Button>

            <div className="text-center space-y-6">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-primary/10 mb-4">
                <Sparkles className="w-8 h-8 text-primary" />
              </div>

              <div>
                <h2 className="text-3xl font-bold mb-3 text-gradient">
                  Welcome to Android Orchestrator
                </h2>
                <p className="text-lg text-muted-foreground">
                  AI-powered automation made simple. Let's get you started!
                </p>
              </div>

              <div className="grid gap-4 text-left">
                <div className="p-4 rounded-lg bg-muted/30 border border-border/50">
                  <h3 className="font-semibold mb-2 flex items-center gap-2">
                    <span className="text-xl">1️⃣</span> Write Your Command
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    Type a natural language command in the Command Center, like "Open app and login"
                  </p>
                </div>

                <div className="p-4 rounded-lg bg-muted/30 border border-border/50">
                  <h3 className="font-semibold mb-2 flex items-center gap-2">
                    <span className="text-xl">2️⃣</span> Watch It Work
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    See real-time logs as Claude AI analyzes and executes actions on your device
                  </p>
                </div>

                <div className="p-4 rounded-lg bg-muted/30 border border-border/50">
                  <h3 className="font-semibold mb-2 flex items-center gap-2">
                    <span className="text-xl">3️⃣</span> Review Results
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    View device screen updates and download detailed JSON reports of all actions
                  </p>
                </div>
              </div>

              <Button
                onClick={handleClose}
                className="w-full bg-gradient-to-r from-primary to-secondary hover:opacity-90"
                size="lg"
              >
                Got It, Let's Start!
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
