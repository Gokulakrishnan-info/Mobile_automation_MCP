import express, { Request, Response } from 'express';
import cors from 'cors';
import { AppiumHelper, AppiumCapabilities } from './lib/appium/appiumHelper.js';
import { AdbCommands } from './lib/adb/adbCommands.js';

const app = express();
const PORT = parseInt(process.env.PORT || '8080', 10);

// Middleware
app.use(cors());
app.use(express.json());

// Store active Appium sessions
const activeSessions = new Map<string, AppiumHelper>();

// Generate unique session ID
function generateSessionId(): string {
  return `session_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

function mapLocatorStrategy(by?: string): string {
  if (!by) return "xpath";
  const b = by.toLowerCase();
  if (b === "accessibility_id" || b === "accessibility id") return "accessibility id";
  if (b === "id") return "id";
  if (b === "class_name" || b === "class name") return "class name";
  return "xpath";
}

// Safely escape a value for use inside an XPath string literal
function escapeXPathValue(value: string): string {
  // If no single quotes, wrap in single quotes
  if (value.indexOf("'") === -1) {
    return `'${value}'`;
  }
  // If no double quotes, wrap in double quotes
  if (value.indexOf('"') === -1) {
    return `"${value}"`;
  }
  // If both quote types exist, use concat to build the string safely
  const parts = value.split("'");
  // Build: concat("part0", "'", "part1", "'", ...)
  let result = 'concat(';
  for (let i = 0; i < parts.length; i++) {
    if (i > 0) {
      result += ', "\'", ';
    }
    result += `"${parts[i]}"`;
  }
  result += ')';
  return result;
}

async function findElementWithFallback(helper: AppiumHelper, locator?: any, fallbacks?: any[]): Promise<any> {
  const tryList: Array<{ strategy: string; value: string }> = [];
  if (locator && locator.value) {
    tryList.push({ strategy: mapLocatorStrategy(locator.by), value: locator.value });
  }
  if (Array.isArray(fallbacks)) {
    for (const fb of fallbacks) {
      if (fb && fb.value) {
        tryList.push({ strategy: mapLocatorStrategy(fb.by), value: fb.value });
      }
    }
  }
  let lastError: any = null;
  for (const t of tryList) {
    try {
      // AppiumHelper exposes findElement(selector, strategy)
      // selector is the value; strategy one of: xpath, id, accessibility id, class name
      // @ts-ignore
      const el = await (helper as any).findElement(t.value, t.strategy);
      return el;
    } catch (e) {
      lastError = e;
    }
  }
  throw lastError || new Error("Element not found with provided locators");
}

async function runNamedTool(helper: AppiumHelper, tool: string, args: any): Promise<any> {
  const h: any = helper;
  
  switch (tool) {
    // Basic interactions
    case 'click':
    case 'tap-element': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };

      try {
        // If using content-desc/accessibility and the value is very long (dynamic metadata),
        // build a more forgiving XPath contains selector using a prefix of the value.
        let strategyToUse = mappedStrategy;
        let selectorToUse = selector;

        const isA11y = (args?.strategy === 'content-desc' || args?.strategy === 'accessibility_id' || mappedStrategy === 'accessibility id');
        const longValue = typeof args?.value === 'string' && args.value.length > 80;
        if (isA11y && longValue) {
          const prefix = String(args.value).slice(0, 60);
          selectorToUse = `//*[contains(@content-desc, ${escapeXPathValue(prefix)})]`;
          strategyToUse = 'xpath';
        }

        // Normalize overly complex content-desc contains-within-contains patterns
        // e.g., //...[@content-desc[contains(., 'text')]][2] -> (//*[contains(@content-desc, 'text')])[2]
        if ((args?.strategy === 'xpath' || strategyToUse === 'xpath') && typeof selectorToUse === 'string') {
          const complexPattern = /\[@content-desc\[contains\(\.,\s*(['\"][^'\"]+['\"])\)\]\]\[(\d+)\]/;
          const m = selectorToUse.match(complexPattern);
          if (m) {
            const text = m[1];
            const idx = m[2];
            selectorToUse = `(//*[contains(@content-desc, ${text})])[${idx}]`;
          }
        }

        // Try to find the element
        let element;
        try {
          element = await h.findElement(selectorToUse, strategyToUse);
        } catch (findError: any) {
          // If element not found, provide helpful error message
          const errorMsg = findError instanceof Error ? findError.message : String(findError);
          if (errorMsg.includes('not found') || errorMsg.includes('NoSuchElement')) {
            return { 
              success: false, 
              message: 'Element not found in current screen', 
              error: `Element with selector '${selectorToUse}' (strategy: ${strategyToUse}) not found. Please check the page source to verify the element exists.`
            };
          }
          throw findError;
        }

        // Ensure element is visible before clicking
        try {
          if (typeof element.waitForDisplayed === 'function') {
            await element.waitForDisplayed({ timeout: 5000 });
          } else {
            const isDisplayed = await element.isDisplayed();
            if (!isDisplayed) {
              return { 
                success: false, 
                message: 'Element not visible', 
                error: 'Element found but not displayed on screen. It may be hidden or off-screen.'
              };
            }
          }
        } catch (displayError: any) {
          return { 
            success: false, 
            message: 'Element not visible', 
            error: displayError instanceof Error ? displayError.message : String(displayError)
          };
        }

        // Attempt click
        try {
          await element.click();
        } catch (clickError: any) {
          const cm = (clickError instanceof Error ? clickError.message : String(clickError)).toLowerCase();
          // Convert low-level selector errors into a structured failure instead of 500s
          if (cm.includes('invalid selector') || cm.includes('invalid xpath') || cm.includes('stale element')) {
            return {
              success: false,
              message: 'Click failed',
              error: clickError instanceof Error ? clickError.message : String(clickError)
            };
          }
          throw clickError;
        }
        return { success: true, message: 'Clicked element', method: 'element' };
      } catch (error: any) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        
        // OCR Fallback: If element not found, try OCR coordinate tapping
        if (errorMsg.includes('not found') || errorMsg.includes('NoSuchElement')) {
          try {
            // Try to extract search text from the selector/value
            const searchText = args?.value || args?.selector || '';
            if (searchText && typeof searchText === 'string' && searchText.length > 0) {
              console.log(`⚠️  Element not found, trying OCR coordinate tapping for: ${searchText}`);
              
              // Take screenshot and find text coordinates
              const screenshotPath = await (h as any).takeScreenshot(`ocr_click_${Date.now()}.png`);
              const coordinates = await (h as any).findTextOnScreen(searchText);
              
              if (coordinates) {
                // Tap at OCR coordinates
                await (h as any).tapCoordinates(coordinates.x, coordinates.y);
                console.log(`✅ Clicked via OCR coordinates (${coordinates.x}, ${coordinates.y})`);
                return { 
                  success: true, 
                  message: 'Clicked element via OCR coordinates', 
                  method: 'ocr_coordinate',
                  coordinates: { x: coordinates.x, y: coordinates.y }
                };
              }
            }
          } catch (ocrError) {
            console.log('OCR fallback also failed:', ocrError);
            // Continue to return original error
          }
        }
        
        return { 
          success: false, 
          message: 'Click failed', 
          error: errorMsg.includes('not found') || errorMsg.includes('NoSuchElement') 
            ? `Element not found in current screen. Verify it exists in the page source.` 
            : errorMsg
        };
      }
    }
    case 'send-keys':
    case 'send_keys': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
      try {
        const success = await h.sendKeys(selector, args?.text || '', mappedStrategy);
        if (success) {
          return { success: true, message: `Successfully sent text: ${args?.text || ''}` };
        } else {
          return { 
            success: false, 
            message: `Failed to send text: ${args?.text || ''}`,
            error: 'Element might not be found, not editable, or not an input field. Check if the element is visible and supports text input.'
          };
        }
      } catch (error: any) {
        return { 
          success: false, 
          message: `Error sending text: ${args?.text || ''}`,
          error: error instanceof Error ? error.message : String(error)
        };
      }
    }
    case 'clear-element':
    case 'clear_element': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
      const success = await h.clearElement(selector, mappedStrategy);
      return { success, message: 'Cleared element' };
    }
    case 'get-element-text':
    case 'get_element_text': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
      const text = await h.getText(selector, mappedStrategy);
      return { success: true, text, message: 'Retrieved element text' };
    }
    case 'wait-for-element':
    case 'wait_for_element': {
      const timeout = args?.timeoutMs ?? 10000;
      try {
        // Check if helper has driver initialized
        try {
          const driver = h.getDriver ? h.getDriver() : null;
          if (!driver) {
            return {
              success: false,
              message: 'Driver not initialized',
              error: 'Appium driver is not initialized. Please ensure the session is active.'
            };
          }
        } catch (driverError) {
          return {
            success: false,
            message: 'Driver not initialized',
            error: 'Appium driver is not initialized. Please ensure the session is active.'
          };
        }

        const rawStrategy = (args?.strategy || 'text') as string;
        const rawValue = (args?.value || args?.selector || '').toString();
        if (!rawValue) {
          return {
            success: false,
            message: 'Invalid arguments',
            error: 'wait_for_element requires a non-empty value/selector'
          };
        }

        let mappedStrategy: string;
        let selector: string;

        if (rawStrategy === 'text') {
          // Robust Android text locator: match text or content-desc via contains
          mappedStrategy = 'xpath';
          const escaped = escapeXPathValue(rawValue);
          selector = `//*[contains(@text, ${escaped}) or contains(@content-desc, ${escaped})]`;
        } else if (rawStrategy === 'xpath') {
          // If a bare string was passed, wrap it to a contains TextView match
          const val = rawValue.trim();
          if (val.startsWith('/') || val.startsWith('(')) {
            mappedStrategy = 'xpath';
            selector = val;
          } else {
            mappedStrategy = 'xpath';
            const escaped = escapeXPathValue(val);
            selector = `//*[contains(@text, ${escaped}) or contains(@content-desc, ${escaped})]`;
          }
        } else {
          const converted = args?.strategy && args?.value
            ? convertStrategyAndValue(args.strategy, args.value)
            : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
          mappedStrategy = converted.mappedStrategy;
          selector = converted.selector;
        }

        try {
          await h.waitForElement(selector, mappedStrategy, timeout);
          return { success: true, message: 'Element found and visible' };
        } catch (waitError: any) {
          const errorMsg = waitError instanceof Error ? waitError.message : String(waitError);
          return {
            success: false,
            message: 'Element not found or wait failed',
            error: errorMsg.includes('not found') || errorMsg.includes('timeout') || errorMsg.includes('Element not found')
              ? `Element with selector '${selector}' (strategy: ${mappedStrategy}) not found within ${timeout}ms timeout. Please check the page source to verify the element exists.`
              : errorMsg
          };
        }
      } catch (error: any) {
        return {
          success: false,
          message: 'Wait for element failed',
          error: error instanceof Error ? error.message : String(error)
        };
      }
    }
    
    // Gestures
    case 'scroll': {
      const direction = args?.direction || 'down';
      const success = await h.scroll(direction, args?.distance || 0.5);
      // Clarify semantics: 'down' means swipe up so content moves up
      const semantic = direction === 'down' ? 'content moved up' : direction === 'up' ? 'content moved down' : '';
      const message = semantic ? `Scrolled ${direction} (${semantic})` : `Scrolled ${direction}`;
      return { success, message };
    }
    case 'scroll-to-element':
    case 'scroll_to_element': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
      const dir = (args?.direction === 'up' || args?.direction === 'down') ? args.direction : 'down';
      const success = await h.scrollToElement(selector, mappedStrategy, args?.maxScrolls || 10, dir);
      return { success, message: success ? 'Scrolled to element' : 'Element not found after scrolling' };
    }
    case 'swipe': {
      await h.swipe(args?.startX, args?.startY, args?.endX, args?.endY, args?.duration ?? 800);
      return { success: true, message: 'Swiped' };
    }
    case 'long-press':
    case 'long_press': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
      const success = await h.longPress(selector, args?.duration || 1000, mappedStrategy);
      return { success, message: 'Long pressed element' };
    }
    
    // Device controls
    case 'press-home-button':
    case 'press_home_button': {
      await h.pressKeyCode(3); // Android HOME key
      return { success: true, message: 'Pressed home button' };
    }
    case 'press-back-button':
    case 'press_back_button': {
      await h.pressKeyCode(4); // Android BACK key
      return { success: true, message: 'Pressed back button' };
    }
    case 'press-key-code': {
      await h.pressKeyCode(args?.keycode);
      return { success: true, message: `Pressed key code: ${args?.keycode}` };
    }
    case 'get-orientation':
    case 'get_orientation': {
      const orientation = await h.getOrientation();
      return { success: true, orientation, message: `Current orientation: ${orientation}` };
    }
    case 'set-orientation':
    case 'set_orientation': {
      await h.setOrientation(args?.orientation);
      return { success: true, message: `Set orientation to ${args?.orientation}` };
    }
    case 'hide-keyboard':
    case 'hide_keyboard': {
      await h.hideKeyboard();
      return { success: true, message: 'Keyboard hidden' };
    }
    case 'lock-device':
    case 'lock_device': {
      await h.lockDevice(args?.duration);
      return { success: true, message: 'Device locked' };
    }
    case 'unlock-device':
    case 'unlock_device': {
      await h.unlockDevice();
      return { success: true, message: 'Device unlocked' };
    }
    case 'get-battery-info':
    case 'get_battery_info': {
      const batteryInfo = await h.getBatteryInfo();
      return { success: true, batteryInfo, message: `Battery: ${batteryInfo.level}%` };
    }
    
    // App management
    case 'launch-app':
    case 'launch_app': {
      if (args?.packageName) {
        if (args?.activityName) {
          await h.startActivity(args.packageName, args.activityName);
          return { success: true, message: `Launched app: ${args.packageName}/${args.activityName}` };
        } else {
          // Launch app by package name only using ADB command
          // We need to use monkey command to launch app by package
          try {
            const { exec } = require('child_process');
            const { promisify } = require('util');
            const execAsync = promisify(exec);
            // Use monkey command: adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1
            const cmd = `adb shell monkey -p ${args.packageName} -c android.intent.category.LAUNCHER 1`;
            await execAsync(cmd, { timeout: 10000 });
            return { success: true, message: `Launched app: ${args.packageName}` };
          } catch (error: any) {
            // If monkey fails, try using am start with main activity
            try {
              const { exec } = require('child_process');
              const { promisify } = require('util');
              const execAsync = promisify(exec);
              // Try to get main activity and launch
              const cmd = `adb shell monkey -p ${args.packageName} 1`;
              await execAsync(cmd, { timeout: 10000 });
              return { success: true, message: `Launched app: ${args.packageName}` };
            } catch (error2: any) {
              throw new Error(`Failed to launch app ${args.packageName}: ${error2.message || error.message}`);
            }
          }
        }
      } else {
        // No package specified, launch the app associated with the session
        await h.launchApp();
        return { success: true, message: 'Launched app' };
      }
    }
    case 'close-app':
    case 'close_app': {
      await h.closeApp();
      return { success: true, message: 'Closed app' };
    }
    case 'reset-app':
    case 'reset_app': {
      await h.resetApp();
      return { success: true, message: 'Reset app' };
    }
    case 'is-app-installed':
    case 'is_app_installed': {
      const isInstalled = await h.isAppInstalled(args?.bundleId);
      return { success: true, isInstalled, message: `App ${args?.bundleId} is ${isInstalled ? 'installed' : 'not installed'}` };
    }
    
    // Context management
    case 'get-contexts': {
      const contexts = await h.getContexts();
      const currentContext = await h.getCurrentContext();
      return { success: true, contexts, currentContext, message: `Available contexts: ${contexts.join(', ')}` };
    }
    case 'switch-context': {
      await h.switchContext(args?.context);
      return { success: true, message: `Switched to context: ${args?.context}` };
    }
    case 'open-notifications': {
      await h.openNotifications();
      return { success: true, message: 'Opened notifications' };
    }
    
    // State observation
    case 'get-page-source':
    case 'get_page_source': {
      try {
        // Try to get page source - any errors will be caught below
        const xml = await h.getPageSource();
        return { success: true, value: xml, xml };
      } catch (error: any) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        // Check for common session/driver errors - return as error response, not throw
        if (errorMsg.includes('not initialized') || 
            errorMsg.includes('session') || 
            errorMsg.includes('connection') ||
            errorMsg.includes('expired') ||
            errorMsg.includes('driver')) {
          return {
            success: false,
            error: `Appium session error: ${errorMsg}. The session may have expired. Please reinitialize.`
          };
        }
        // For other errors, still return error response instead of throwing
        // This prevents 500 errors and provides better error messages
        return {
          success: false,
          error: `Failed to get page source: ${errorMsg}`
        };
      }
    }
    case 'take-screenshot':
    case 'take_screenshot': {
      const path = await h.takeScreenshot(args?.filename || `screenshot_${Date.now()}.png`);
      return { success: !!path, screenshotPath: path, message: `Screenshot saved: ${path}` };
    }
    case 'get-current-package-activity':
    case 'get_current_package_activity': {
      const packageName = await h.getCurrentPackage();
      const activityName = await h.getCurrentActivity();
      return { success: true, package: packageName, activity: activityName, message: `Current app: ${packageName}/${activityName}` };
    }
    case 'get-current-package': {
      const pkg = await h.getCurrentPackage();
      return { success: true, result: pkg, data: pkg };
    }
    case 'get-current-activity': {
      const act = await h.getCurrentActivity();
      return { success: true, result: act, data: act };
    }
    
    // Advanced features
    case 'start-recording': {
      await h.startRecording(args || {});
      return { success: true, message: 'Started recording' };
    }
    case 'stop-recording': {
      const base64 = await h.stopRecording();
      return { success: true, data: base64, message: 'Stopped recording' };
    }
    case 'run-adb-shell': {
      const command = args?.command || '';
      if (!command) {
        return { success: false, error: 'No command provided' };
      }
      
      const { exec } = require('child_process');
      const { promisify } = require('util');
      const execAsync = promisify(exec);
      
      try {
        const fullCmd = `adb shell "sh -c '${command.replace(/'/g, "'\"'\"'")}'"`;
        const { stdout, stderr } = await execAsync(fullCmd, { timeout: 10000 });
        return { success: true, result: stdout.trim(), data: stdout.trim() };
      } catch (error: any) {
        return { success: false, error: error.message, result: '', data: '' };
      }
    }
    // Additional tools - try to map to AppiumHelper methods dynamically
    case 'get-device-time':
    case 'get_device_time': {
      const time = await h.getDeviceTime();
      return { success: true, time, message: `Device time: ${time}` };
    }
    case 'pull-file':
    case 'pull_file': {
      const fileContent = await h.pullFile(args?.path);
      return { success: true, data: fileContent, message: `File pulled from ${args?.path}` };
    }
    case 'push-file':
    case 'push_file': {
      await h.pushFile(args?.path, args?.data);
      return { success: true, message: `File pushed to ${args?.path}` };
    }
    case 'element-exists':
    case 'element_exists': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
      const exists = await h.elementExists(selector, mappedStrategy);
      return { success: true, exists, message: `Element ${exists ? 'exists' : 'does not exist'}` };
    }
    case 'get-element-attributes':
    case 'get_element_attributes': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
      const attributes = await h.getElementAttributes(selector, mappedStrategy);
      return { success: true, attributes, message: 'Retrieved element attributes' };
    }
    case 'scroll-screen':
    case 'scroll_screen': {
      const direction = args?.direction || 'down';
      await h.scrollScreen(direction);
      return { success: true, message: `Scrolled screen ${direction}` };
    }
    case 'shake-device':
    case 'shake_device': {
      await h.shakeDevice();
      return { success: true, message: 'Device shaken' };
    }
    case 'is-device-locked':
    case 'is_device_locked': {
      const isLocked = await h.isDeviceLocked();
      return { success: true, isLocked, message: `Device is ${isLocked ? 'locked' : 'unlocked'}` };
    }
    case 'get-current-context':
    case 'get_current_context': {
      const context = await h.getCurrentContext();
      return { success: true, context, message: `Current context: ${context}` };
    }
    case 'execute-mobile-command':
    case 'execute_mobile_command': {
      const result = await h.executeMobileCommand(args?.command, args?.args || []);
      return { success: true, result, message: 'Mobile command executed' };
    }
    case 'perform-w3c-gesture':
    case 'perform_w3c_gesture': {
      await h.performW3CGesture(args?.gesture);
      return { success: true, message: 'W3C gesture performed' };
    }
    case 'tap-element':
    case 'tap_element': {
      const { mappedStrategy, selector } = args?.strategy && args?.value 
        ? convertStrategyAndValue(args.strategy, args.value)
        : { mappedStrategy: mapLocatorStrategy(args?.strategy), selector: args?.selector || args?.value };
      const success = await h.tapElement(selector, mappedStrategy);
      return { success, message: success ? 'Element tapped' : 'Failed to tap element' };
    }
    case 'send-key-event':
    case 'send_key_event': {
      await h.sendKeyEvent(args?.keycode);
      return { success: true, message: `Key event sent: ${args?.keycode}` };
    }
    case 'list-ios-simulators':
    case 'list_ios_simulators': {
      const simulators = await h.listIosSimulators();
      return { success: true, simulators, message: `Found ${simulators.length} simulators` };
    }
    
    // ADB Tools (don't require Appium session)
    case 'list-devices': {
      try {
        const devices = await AdbCommands.getDevices();
        return { success: true, devices, message: `Found ${devices.length} device(s)` };
      } catch (error: any) {
        return { success: false, error: error.message || 'Failed to list devices' };
      }
    }
    case 'install-app': {
      try {
        const result = await AdbCommands.installApp(args?.deviceId, args?.apkPath);
        return { success: true, result, message: 'App installed successfully' };
      } catch (error: any) {
        return { success: false, error: error.message || 'Failed to install app' };
      }
    }
    case 'uninstall-app': {
      try {
        const result = await AdbCommands.uninstallApp(args?.deviceId, args?.packageName);
        return { success: true, result, message: 'App uninstalled successfully' };
      } catch (error: any) {
        return { success: false, error: error.message || 'Failed to uninstall app' };
      }
    }
    case 'list-installed-packages': {
      try {
        const packages = await AdbCommands.getInstalledPackages(args?.deviceId);
        return { success: true, packages, message: `Found ${packages.length} package(s)` };
      } catch (error: any) {
        return { success: false, error: error.message || 'Failed to list packages' };
      }
    }
    case 'execute-adb-command': {
      try {
        const result = await AdbCommands.executeCommand(args?.command);
        return { success: true, result, message: 'ADB command executed' };
      } catch (error: any) {
        return { success: false, error: error.message || 'Failed to execute ADB command' };
      }
    }
    
    // For tools that need special handling or don't map directly, return a helpful error
    default: {
      // Try to find if it's a method on AppiumHelper
      const methodName = tool.replace(/-/g, '').replace(/_/g, '');
      if (typeof (h as any)[methodName] === 'function') {
        try {
          const result = await (h as any)[methodName](...(args ? Object.values(args) : []));
          return { success: true, result, message: `Executed ${tool}` };
        } catch (error: any) {
          return { 
            success: false, 
            error: `Error executing ${tool}: ${error instanceof Error ? error.message : String(error)}` 
          };
        }
      }
      throw new Error(`Unknown tool: ${tool}. Available tools: click, send_keys, get_page_source, take_screenshot, scroll, swipe, long_press, get_element_text, clear_element, press_home_button, press_back_button, launch_app, close_app, reset_app, scroll_to_element, get_orientation, set_orientation, hide_keyboard, lock_device, unlock_device, get_battery_info, get_contexts, switch_context, open_notifications, is_app_installed, get_current_package_activity, get_device_time, pull_file, push_file, element_exists, and more. See /tools/run endpoint documentation.`);
    }
  }
}

// Helper function to convert strategy/value format
function convertStrategyAndValue(strategy: string, value: string): { mappedStrategy: string; selector: string } {
  const strategyLower = strategy.toLowerCase();
  const escapeXPathValue = (val: string): string => val.replace(/'/g, "''");
  
  if (strategyLower === 'text') {
    const mappedStrategy = 'xpath';
    const escapedValue = escapeXPathValue(value);
    const selector = `//*[contains(@text, '${escapedValue}') or contains(@content-desc, '${escapedValue}')]`;
    return { mappedStrategy, selector };
  } else if (strategyLower === 'content-desc' || strategyLower === 'content_desc' || strategyLower === 'accessibility_id' || strategyLower === 'accessibility id') {
    return { mappedStrategy: 'accessibility id', selector: value };
  } else {
    return { mappedStrategy: mapLocatorStrategy(strategy), selector: value };
  }
}

// Health check endpoint
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok', message: 'MCP Appium Server is running' });
});

// Initialize Appium session
app.post('/tools/initialize-appium', async (req, res) => {
  try {
    const params = req.body || {};
    
    // Convert legacy format to W3C format with proper appium: prefixes
    const capabilities: AppiumCapabilities = {
      platformName: params.platformName || 'Android',
      'appium:deviceName': params.deviceName,
      'appium:udid': params.udid,
      'appium:appPackage': params.appPackage,
      'appium:appActivity': params.appActivity,
      'appium:bundleId': params.bundleId,
      'appium:automationName': params.automationName || 'UiAutomator2',
      'appium:noReset': params.noReset !== undefined ? params.noReset : true,
      'appium:fullReset': params.fullReset,
      'appium:newCommandTimeout': 300, // 5 minutes timeout
      'appium:commandTimeouts': {
        'implicit': 10000,
        'pageLoad': 30000
      }
    } as AppiumCapabilities;

    console.log('W3C Formatted Capabilities:', JSON.stringify(capabilities, null, 2));
    
    const helper = new AppiumHelper(params.screenshotDir || './screenshots');
    await helper.initializeDriver(capabilities, params.appiumUrl || 'http://127.0.0.1:4723');
    const sessionId = generateSessionId();
    activeSessions.set(sessionId, helper);
    res.json({ success: true, sessionId });
  } catch (error) {
    console.error('Appium initialization error:', error);
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Execute YAML test
app.post('/tools/execute-yaml-test', async (req, res) => {
  try {
    const { app, steps, screenshotDir, sessionId } = req.body || {};
    if (!Array.isArray(steps)) {
      return res.status(400).json({ success: false, error: 'steps must be an array' });
    }

    const helper = sessionId ? activeSessions.get(sessionId) : undefined;
    if (!helper) {
      return res.status(400).json({ success: false, error: 'Invalid or missing sessionId' });
    }

    const driver = (helper as any).getDriver ? (helper as any).getDriver() : null;
    if (!driver) {
      return res.status(500).json({ success: false, error: 'Driver not initialized' });
    }

    const results: any[] = [];
    const screenshots: string[] = [];
    const startedAt = Date.now();

    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      const action = step?.action;
      try {
        if (action === 'start_app') {
          // If Android package/activity provided, (re)launch explicitly
          if (app?.package && app?.activity && driver.startActivity) {
            await driver.startActivity(app.package, app.activity);
          }
          results.push({ step: i + 1, action, success: true });
          continue;
        }

        if (action === 'wait') {
          const timeoutMs = Math.max(0, Math.floor((step?.timeout || 1) * 1000));
          await new Promise(r => setTimeout(r, timeoutMs));
          results.push({ step: i + 1, action, success: true });
          continue;
        }

        if (action === 'wait_for') {
          const timeoutSec = step?.timeout || 10;
          const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
          await el.waitForDisplayed({ timeout: timeoutSec * 1000 });
          results.push({ step: i + 1, action, success: true });
          continue;
        }

        if (action === 'send_keys') {
          const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
          await el.setValue(step?.text ?? '');
          results.push({ step: i + 1, action, success: true });
          continue;
        }

        if (action === 'tap') {
          const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
          await el.click();
          results.push({ step: i + 1, action, success: true });
          continue;
        }

        if (action === 'screenshot') {
          const name = step?.filename || `screenshot_${Date.now()}.png`;
          const path = await (helper as any).takeScreenshot(name);
          if (path) screenshots.push(path);
          results.push({ step: i + 1, action, success: true });
          continue;
        }

        // Unknown action
        results.push({ step: i + 1, action, success: false, error: `Unknown action: ${action}` });
      } catch (e: any) {
        results.push({ step: i + 1, action, success: false, error: e?.message || String(e) });
        break;
      }
    }

    const executionTime = Date.now() - startedAt;
    res.json({ success: results.every(r => r.success), results, screenshots, executionTime });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Execute single step
app.post('/tools/execute-step', async (req, res) => {
  try {
    const { step, screenshotDir, sessionId } = req.body || {};
    const helper = sessionId ? activeSessions.get(sessionId) : undefined;
    if (!helper) {
      return res.status(400).json({ success: false, error: 'Invalid or missing sessionId' });
    }
    const driver = (helper as any).getDriver ? (helper as any).getDriver() : null;
    if (!driver) {
      return res.status(500).json({ success: false, error: 'Driver not initialized' });
    }

    const action = step?.action;
    let screenshot: string | null = null;
    try {
      if (action === 'wait') {
        const timeoutMs = Math.max(0, Math.floor((step?.timeout || 1) * 1000));
        await new Promise(r => setTimeout(r, timeoutMs));
      } else if (action === 'tap') {
        const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
        await el.click();
      } else if (action === 'send_keys') {
        const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
        await el.setValue(step?.text ?? '');
      } else if (action === 'wait_for') {
        const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
        await el.waitForDisplayed({ timeout: (step?.timeout || 10) * 1000 });
      } else if (action === 'screenshot') {
        const name = step?.filename || `screenshot_${Date.now()}.png`;
        screenshot = await (helper as any).takeScreenshot(name);
      } else if (action === 'start_app') {
        // Actually start/relaunch the app using AppiumHelper's startActivity
        const appPackage = step?.appPackage || step?.package || (helper as any).appConfig?.package;
        const appActivity = step?.appActivity || step?.activity || (helper as any).appConfig?.activity;
        if (appPackage && appActivity) {
          await helper.startActivity(appPackage, appActivity);
        } else {
          // If no package/activity provided, try to launch the app associated with the session
          try {
            await (helper as any).launchApp();
          } catch (e: any) {
            throw new Error(`Failed to start app: ${e?.message || String(e)}`);
          }
        }
      } else if (action === 'assert_visible' || action === 'assert_exists') {
        // Assert that element is visible/exists
        const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
        const displayed = await el.isDisplayed();
        if (!displayed) {
          throw new Error(`Element not visible: ${JSON.stringify(step?.locator)}`);
        }
      } else if (action === 'assert_text') {
        // Assert that element text matches expected value
        const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
        const actualText = await el.getText();
        const expectedText = step?.text || step?.expected_text || '';
        if (actualText.trim() !== expectedText.trim()) {
          throw new Error(`Text mismatch: expected '${expectedText}', got '${actualText}'`);
        }
      } else if (action === 'input_text' || action === 'send_keys') {
        // Alias for send_keys
        const el = await findElementWithFallback(helper, step?.locator, step?.fallback_locators);
        await el.setValue(step?.text ?? step?.input_text ?? '');
      } else {
        return res.status(400).json({ success: false, error: `Unknown action: ${action}` });
      }

      res.json({ success: true, screenshot });
    } catch (e: any) {
      res.status(500).json({ success: false, error: e?.message || String(e) });
    }
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Wait for element with OCR fallback
app.post('/tools/wait-for-element', async (req, res) => {
  try {
    const { locator, fallback_locators, timeout, sessionId, useOcr = true } = req.body || {};
    
    // Try to get helper - use sessionId if provided, otherwise try default session
    let helper = sessionId ? activeSessions.get(sessionId) : getDefaultSession();
    if (!helper) {
      return res.status(400).json({ success: false, error: 'Invalid or missing sessionId. No active Appium session found.' });
    }
    
    try {
      // Try element-based approach first
      if (locator && locator.value) {
        try {
          const el = await findElementWithFallback(helper, locator, fallback_locators);
          await el.waitForDisplayed({ timeout: (timeout || 10) * 1000 });
          res.json({ success: true, method: 'element' });
          return;
        } catch (elementError: any) {
          // Element not found, try OCR fallback
          if (useOcr) {
            const searchText = locator?.value || fallback_locators?.[0]?.value || locator?.text;
            if (searchText) {
              try {
                const found = await (helper as any).waitForTextOnScreen(searchText, (timeout || 10) * 1000);
                if (found) {
                  res.json({ success: true, method: 'ocr', text: searchText });
                  return;
                } else {
                  res.json({
                    success: false,
                    error: `Text '${searchText}' not found on screen within ${timeout || 10} seconds`
                  });
                  return;
                }
              } catch (ocrError: any) {
                res.json({
                  success: false,
                  error: `Element and OCR wait failed: ${ocrError instanceof Error ? ocrError.message : String(ocrError)}`
                });
                return;
              }
            }
          }
          // No OCR or no search text
          res.json({
            success: false,
            error: `Element wait failed: ${elementError instanceof Error ? elementError.message : String(elementError)}`
          });
          return;
        }
      } else {
        // No locator provided, try OCR directly if text is available
        if (useOcr) {
          const searchText = locator?.value || fallback_locators?.[0]?.value || locator?.text;
          if (searchText) {
            try {
              const found = await (helper as any).waitForTextOnScreen(searchText, (timeout || 10) * 1000);
              if (found) {
                res.json({ success: true, method: 'ocr', text: searchText });
                return;
              } else {
                res.json({
                  success: false,
                  error: `Text '${searchText}' not found on screen within ${timeout || 10} seconds`
                });
                return;
              }
            } catch (ocrError: any) {
              res.json({
                success: false,
                error: `OCR wait failed: ${ocrError instanceof Error ? ocrError.message : String(ocrError)}`
              });
              return;
            }
          }
        }
        res.json({
          success: false,
          error: 'No locator or search text provided'
        });
        return;
      }
    } catch (error: any) {
      console.error('wait-for-element endpoint error:', error);
      res.json({
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error'
      });
    }
  } catch (error: any) {
    console.error('wait-for-element outer error:', error);
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Take screenshot with session
app.post('/tools/take-screenshot', async (req, res) => {
  try {
    const { filename, sessionId } = req.body || {};
    const helper = sessionId ? activeSessions.get(sessionId) : undefined;
    if (!helper) {
      return res.status(400).json({ success: false, error: 'Invalid or missing sessionId' });
    }
    const path = await (helper as any).takeScreenshot(filename || `screenshot_${Date.now()}.png`);
    res.json({ success: !!path, screenshotPath: path });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Close Appium session
app.post('/tools/close-appium-session', async (req, res) => {
  try {
    const { sessionId } = req.body || {};
    const helper = sessionId ? activeSessions.get(sessionId) : undefined;
    if (helper) {
      try { await (helper as any).closeDriver(); } catch {}
      activeSessions.delete(sessionId);
    }
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Get devices
app.get('/tools/get-devices', async (req, res) => {
  try {
    // Minimal placeholder; could be enhanced to run adb and xcode tools
    res.json({ success: true, devices: [] });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// OCR-based tap with fallback
app.post('/tools/tap-ocr', async (req, res) => {
  try {
    const { text, locator, fallback_locators, sessionId, useOcr = true } = req.body || {};
    const helper = sessionId ? activeSessions.get(sessionId) : undefined;
    if (!helper) {
      return res.status(400).json({ success: false, error: 'Invalid or missing sessionId' });
    }
    
    try {
      // Try element-based approach first
      if (locator) {
        const el = await findElementWithFallback(helper, locator, fallback_locators);
        await el.click();
        res.json({ success: true, method: 'element' });
        return;
      }
    } catch (elementError) {
      console.log('Element-based tap failed, trying OCR...');
    }
    
    if (useOcr && text) {
      try {
        // OCR fallback - find and tap text on screen
        const coordinates = await (helper as any).findTextOnScreen(text);
        if (coordinates) {
          await (helper as any).tapCoordinates(coordinates.x, coordinates.y);
          res.json({ success: true, method: 'ocr', text: text, coordinates });
        } else {
          throw new Error(`Text '${text}' not found on screen`);
        }
      } catch (ocrError) {
        res.status(500).json({
          success: false,
          error: `Element and OCR tap failed: ${ocrError instanceof Error ? ocrError.message : String(ocrError)}`
        });
      }
    } else {
      throw new Error('No locator or text provided for tap action');
    }
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// OCR-based input with fallback
app.post('/tools/input-ocr', async (req, res) => {
  try {
    const { text, inputText, locator, fallback_locators, sessionId, useOcr = true } = req.body || {};
    const helper = sessionId ? activeSessions.get(sessionId) : undefined;
    if (!helper) {
      return res.status(400).json({ success: false, error: 'Invalid or missing sessionId' });
    }
    
    try {
      // Try element-based approach first
      if (locator) {
        const el = await findElementWithFallback(helper, locator, fallback_locators);
        await el.setValue(inputText || text);
        res.json({ success: true, method: 'element' });
        return;
      }
    } catch (elementError) {
      console.log('Element-based input failed, trying OCR...');
    }
    
    if (useOcr && text) {
      try {
        // OCR fallback - find input field and enter text
        const coordinates = await (helper as any).findTextOnScreen(text);
        if (coordinates) {
          await (helper as any).tapCoordinates(coordinates.x, coordinates.y);
          await (helper as any).typeText(inputText || text);
          res.json({ success: true, method: 'ocr', text: text, inputText: inputText || text, coordinates });
        } else {
          throw new Error(`Input field '${text}' not found on screen`);
        }
      } catch (ocrError) {
        res.status(500).json({
          success: false,
          error: `Element and OCR input failed: ${ocrError instanceof Error ? ocrError.message : String(ocrError)}`
        });
      }
    } else {
      throw new Error('No locator or text provided for input action');
    }
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Get perception summary (XML + OCR combined)
app.post('/tools/get-perception-summary', async (req, res) => {
  try {
    const { sessionId, useOcr = false } = req.body || {}; 
    // useOcr can be explicitly set, but OCR will also auto-trigger if XML is sparse
    const helper = sessionId ? activeSessions.get(sessionId) : getDefaultSession();
    if (!helper) {
      return res.status(400).json({ success: false, error: 'Invalid or missing sessionId' });
    }
    
    const summary = await (helper as any).generatePerceptionSummary(useOcr);
    res.json({ success: true, ...summary });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Verify action with text diff
app.post('/tools/verify-with-diff', async (req, res) => {
  try {
    const { expectedKeywords, beforeScreenshot, afterScreenshot, sessionId } = req.body || {};
    const helper = sessionId ? activeSessions.get(sessionId) : getDefaultSession();
    if (!helper) {
      return res.status(400).json({ success: false, error: 'Invalid or missing sessionId' });
    }
    
    if (!beforeScreenshot || !afterScreenshot) {
      return res.status(400).json({ success: false, error: 'Both before and after screenshots required' });
    }
    
    // Extract OCR text from both screenshots
    const { TextDiff } = await import('./lib/ocr/textDiff.js');
    const textDiff = new TextDiff();
    
    const beforeOCR = await (helper as any).extractTextFromScreenshot(beforeScreenshot);
    const afterOCR = await (helper as any).extractTextFromScreenshot(afterScreenshot);
    
    // Verify with expected keywords
    const verification = textDiff.verifyAction(
      expectedKeywords || [],
      beforeOCR.text,
      afterOCR.text
    );
    
    res.json({
      success: verification.success,
      diff_score: verification.diff_score,
      keywords_found: verification.keywords_found,
      keywords_missing: verification.keywords_missing,
      before_text: beforeOCR.text,
      after_text: afterOCR.text
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Generic tool dispatcher leveraging AppiumHelper-backed implementations
app.post('/tools/run', async (req, res) => {
  try {
    const { tool, args, sessionId } = req.body || {};
    if (!tool) return res.status(400).json({ success: false, error: 'Missing tool' });
    
    // Use provided sessionId or default to first active session
    const helper = sessionId ? activeSessions.get(sessionId) : getDefaultSession();
    if (!helper) {
      return res.status(400).json({ 
        success: false, 
        error: 'No active Appium session. Please initialize a session first using /tools/initialize-appium' 
      });
    }
    
    // Validate session before executing tool (especially for get_page_source)
    if (tool === 'get_page_source') {
      try {
        const driver = helper.getDriver();
        if (!driver) {
          return res.status(400).json({
            success: false,
            error: 'Appium driver not initialized. The session may have expired. Please reinitialize the session using /tools/initialize-appium'
          });
        }
      } catch (driverCheckError: any) {
        // Driver check failed - session likely expired or driver not initialized
        const errorMsg = driverCheckError instanceof Error ? driverCheckError.message : String(driverCheckError);
        return res.status(400).json({
          success: false,
          error: `Appium session error: ${errorMsg}. The session may have expired. Please reinitialize the session using /tools/initialize-appium`
        });
      }
    }
    
    const result = await runNamedTool(helper, tool, args || {});
    res.json(result);
  } catch (error) {
    console.error('Tools/run endpoint error:', error);
    const msg = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase();
    const isSelectorIssue = msg.includes('invalid selector') || msg.includes('invalid xpath') || msg.includes('selector') && msg.includes('invalid');
    const isSessionIssue = msg.includes('session') || msg.includes('not initialized') || msg.includes('connection') || msg.includes('expired');
    
    // Return 400 for session/driver issues instead of 500
    const statusCode = isSelectorIssue ? 400 : (isSessionIssue ? 400 : 500);
    res.status(statusCode).json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error'
    });
  }
});

// Simple endpoints for main.py compatibility (using default session)
// Get the first active session or return error
function getDefaultSession(): AppiumHelper | null {
  if (activeSessions.size === 0) {
    return null;
  }
  // Return the first (most recent) session
  const session = activeSessions.values().next().value;
  return session || null;
}

// Note: All simple endpoints (like /click, /send_keys, /get_page_source, etc.) have been removed
// All tools are now available through /tools/run endpoint
// Example: POST /tools/run with {"tool": "click", "args": {"strategy": "id", "value": "button"}}

// Start the HTTP server
// Bind to 0.0.0.0 to accept connections from localhost, 127.0.0.1, and other interfaces
app.listen(PORT, '0.0.0.0', () => {
  console.log(`MCP Appium HTTP Server running on http://0.0.0.0:${PORT}`);
  console.log(`  Accessible via: http://localhost:${PORT} or http://127.0.0.1:${PORT}`);
  console.log('Available endpoints:');
  console.log('  GET  /health');
  console.log('  POST /tools/run - Universal tool endpoint (all tools available here)');
  console.log('  POST /tools/initialize-appium');
  console.log('  POST /tools/execute-yaml-test');
  console.log('  POST /tools/execute-step');
  console.log('  POST /tools/take-screenshot');
  console.log('  POST /tools/close-appium-session');
  console.log('  GET  /tools/get-devices');
  console.log('  POST /tools/tap-ocr');
  console.log('  POST /tools/input-ocr');
  console.log('  POST /tools/wait-for-element');
  console.log('');
  console.log('All tools are accessible via POST /tools/run with:');
  console.log('  {"tool": "tool_name", "args": {...}}');
  console.log('');
  console.log('Available tools: click, send_keys, get_page_source, take_screenshot,');
  console.log('  scroll, swipe, long_press, get_element_text, clear_element,');
  console.log('  press_home_button, press_back_button, launch_app, close_app,');
  console.log('  reset_app, scroll_to_element, get_orientation, set_orientation,');
  console.log('  hide_keyboard, lock_device, unlock_device, get_battery_info,');
  console.log('  get_contexts, switch_context, open_notifications, is_app_installed,');
  console.log('  get_current_package_activity, and more...');
});

export { app };
