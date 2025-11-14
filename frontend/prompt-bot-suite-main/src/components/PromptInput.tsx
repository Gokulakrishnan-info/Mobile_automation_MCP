import { useState } from "react";
import { motion } from "framer-motion";
import { Play, History, Loader2, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { HelpTooltip } from "./HelpTooltip";

interface PromptInputProps {
  onSubmit: (prompt: string) => void;
  isRunning: boolean;
}

export const PromptInput = ({ onSubmit, isRunning }: PromptInputProps) => {
  const [prompt, setPrompt] = useState("");
  const [history, setHistory] = useState<string[]>([
    "Open Swag Labs app and log in using username and password",
    "Navigate to products and add first item to cart",
    "Go to checkout and complete the purchase"
  ]);
  const [showHistory, setShowHistory] = useState(false);
  const [showExamples, setShowExamples] = useState(true);

  const examplePrompts = [
    "Open the app and login with test credentials",
    "Navigate to settings and enable notifications",
    "Add three items to cart and proceed to checkout",
    "Search for 'product' and view first result"
  ];

  const handleSubmit = () => {
    if (!prompt.trim()) {
      toast.error("Please enter a command");
      return;
    }
    
    setHistory(prev => [prompt, ...prev.slice(0, 9)]);
    onSubmit(prompt);
    setPrompt("");
  };

  return (
    <motion.div
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      whileHover={{ boxShadow: "0 0 40px hsl(var(--glow-primary) / 0.25)" }}
      className="glass-panel rounded-2xl p-6 space-y-4 interactive-card h-full premium-border"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/20 border border-primary/30">
            <span className="text-xl">⚡</span>
          </div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Command Center</h2>
            <p className="text-xs text-muted-foreground/70 mt-0.5">Enter your automation task</p>
          </div>
          <HelpTooltip content="Enter natural language commands to automate your Android app. Be specific about what you want the AI to do." />
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowHistory(!showHistory)}
          className="text-muted-foreground hover:text-foreground"
        >
          <History className="w-4 h-4 mr-2" />
          History
        </Button>
      </div>

      {showExamples && !prompt && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-4 rounded-lg bg-primary/5 border border-primary/20 backdrop-blur-sm"
        >
          <div className="flex items-start gap-2 mb-3">
            <Lightbulb className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm font-medium mb-1">Try these example commands:</p>
              <div className="space-y-2">
                {examplePrompts.map((example, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      setPrompt(example);
                      setShowExamples(false);
                    }}
                    className="block w-full text-left text-xs text-muted-foreground hover:text-primary transition-colors p-2 rounded hover:bg-primary/10"
                  >
                    → {example}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </motion.div>
      )}

      <Textarea
        value={prompt}
        onChange={(e) => {
          setPrompt(e.target.value);
          if (e.target.value) setShowExamples(false);
        }}
        placeholder="Describe what you want to automate...&#10;&#10;Example: 'Open Swag Labs app, login with username standard_user and password secret_sauce, then add first item to cart'"
        className="min-h-[120px] resize-none bg-background/25 border-2 border-border/40 focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all text-sm rounded-xl px-4 py-3"
        disabled={isRunning}
        onFocus={() => setShowExamples(false)}
      />

      <Button
        onClick={handleSubmit}
        disabled={isRunning || !prompt.trim()}
        className="w-full bg-gradient-to-r from-primary via-secondary to-primary text-base font-semibold py-6 rounded-xl shadow-lg hover:shadow-xl glow-primary hover:glow-primary transition-all duration-500"
        style={{
          backgroundSize: '200% auto',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundPosition = '100% center';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundPosition = '0% center';
        }}
        size="lg"
      >
        {isRunning ? (
          <>
            <Loader2 className="w-5 h-5 mr-2 animate-spin" />
            Running Automation...
          </>
        ) : (
          <>
            <Play className="w-5 h-5 mr-2" />
            Run Automation
          </>
        )}
      </Button>

      {showHistory && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="space-y-2 pt-4 border-t border-border/50"
        >
          <p className="text-sm text-muted-foreground mb-2">Recent Commands</p>
          {history.map((cmd, idx) => (
            <motion.button
              key={idx}
              initial={{ x: -10, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              transition={{ delay: idx * 0.05 }}
              onClick={() => setPrompt(cmd)}
              className="w-full text-left p-3 rounded-lg bg-muted/25 hover:bg-muted/35 border border-border/30 hover:border-primary/30 transition-all text-sm backdrop-blur-sm"
            >
              {cmd}
            </motion.button>
          ))}
        </motion.div>
      )}
    </motion.div>
  );
};
