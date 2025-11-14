import type { ChainablePromiseElement, ChainablePromiseArray } from "webdriverio";
import {
  remote,
  RemoteOptions,
  Browser,
} from "webdriverio";
import * as fs from "fs/promises";
import * as path from "path";

/**
 * Custom error class for Appium operations
 */
export class AppiumError extends Error {
  constructor(message: string, public readonly cause?: Error) {
    super(message);
    this.name = "AppiumError";
  }
}

/**
 * W3C compliant Appium capabilities for different platforms
 */
export interface AppiumCapabilities {
  // Standard W3C capabilities (no prefix required)
  platformName: "Android" | "iOS";
  browserName?: string;
  browserVersion?: string;
  platformVersion?: string;

  // Appium-specific capabilities (require appium: prefix)
  "appium:deviceName"?: string;
  "appium:udid"?: string;
  "appium:automationName"?:
    | "UiAutomator2"
    | "XCUITest"
    | "Espresso"
    | "Flutter";
  "appium:app"?: string;
  "appium:appPackage"?: string;
  "appium:appActivity"?: string;
  "appium:bundleId"?: string;
  "appium:noReset"?: boolean;
  "appium:fullReset"?: boolean;
  "appium:newCommandTimeout"?: number;
  "appium:commandTimeouts"?: Record<string, number>;
  "appium:orientation"?: "PORTRAIT" | "LANDSCAPE";
  "appium:autoAcceptAlerts"?: boolean;
  "appium:autoDismissAlerts"?: boolean;
  "appium:language"?: string;
  "appium:locale"?: string;
  "appium:printPageSourceOnFindFailure"?: boolean;

  // Allow additional appium: prefixed capabilities
  [key: `appium:${string}`]: any;

  // Legacy format support (will be automatically converted)
  deviceName?: string;
  udid?: string;
  automationName?: "UiAutomator2" | "XCUITest" | "Espresso" | "Flutter";
  app?: string;
  appPackage?: string;
  appActivity?: string;
  bundleId?: string;
  noReset?: boolean;
  fullReset?: boolean;
  newCommandTimeout?: number;

  // Allow any additional properties for flexibility
  [key: string]: any;
}

/**
 * W3C Actions API types for advanced gestures
 */
interface W3CPointerAction {
  type: "pointer";
  id: string;
  parameters: {
    pointerType: "touch" | "pen" | "mouse";
  };
  actions: Array<{
    type: "pointerMove" | "pointerDown" | "pointerUp" | "pause";
    duration?: number;
    x?: number;
    y?: number;
    button?: number;
    origin?: "viewport" | "pointer";
  }>;
}

interface W3CKeyAction {
  type: "key";
  id: string;
  actions: Array<{
    type: "keyDown" | "keyUp" | "pause";
    value?: string;
    duration?: number;
  }>;
}

interface W3CWheelAction {
  type: "wheel";
  id: string;
  actions: Array<{
    type: "scroll" | "pause";
    x?: number;
    y?: number;
    deltaX?: number;
    deltaY?: number;
    duration?: number;
    origin?: "viewport" | "pointer";
  }>;
}

type W3CAction = W3CPointerAction | W3CKeyAction | W3CWheelAction;

/**
 * Helper class for W3C compliant Appium operations
 */
export class AppiumHelper {
  private driver: Browser | null = null;
  private screenshotDir: string;
  private readonly maxRetries: number = 3;
  private readonly retryDelay: number = 1000;
  private lastCapabilities: AppiumCapabilities | null = null;
  private lastAppiumUrl: string | null = null;

  constructor(screenshotDir: string = "./test-screenshots") {
    this.screenshotDir = screenshotDir;
  }

  /**
   * Convert legacy capabilities to W3C compliant format
   */
  private formatCapabilitiesForW3C(
    capabilities: AppiumCapabilities
  ): Record<string, any> {
    const w3cCapabilities: Record<string, any> = {};

    // List of standard W3C capabilities that don't need appium: prefix
    const standardW3CCaps = [
      "platformName",
      "browserName",
      "browserVersion",
      "platformVersion",
      "acceptInsecureCerts",
      "pageLoadStrategy",
      "proxy",
      "setWindowRect",
      "timeouts",
      "unhandledPromptBehavior",
    ];

    for (const [key, value] of Object.entries(capabilities)) {
      if (value === undefined || value === null) {
        continue;
      }

      if (standardW3CCaps.includes(key)) {
        w3cCapabilities[key] = value;
      } else if (key.startsWith("appium:")) {
        w3cCapabilities[key] = value;
      } else {
        w3cCapabilities[`appium:${key}`] = value;
      }
    }

    return w3cCapabilities;
  }

  /**
   * Initialize the Appium driver with W3C compliant capabilities
   */
  async initializeDriver(
    capabilities: AppiumCapabilities,
    appiumUrl: string = "http://localhost:4723"
  ): Promise<Browser> {
    try {
      this.lastCapabilities = { ...capabilities };
      this.lastAppiumUrl = appiumUrl;

      const w3cCapabilities = this.formatCapabilitiesForW3C(capabilities);
      console.log(
        "W3C Formatted Capabilities:",
        JSON.stringify(w3cCapabilities, null, 2)
      );

      const parsedUrl = new URL(appiumUrl);
      const options: RemoteOptions = {
        hostname: parsedUrl.hostname,
        port: parseInt(parsedUrl.port) || 4723,
        path: parsedUrl.pathname || "/",
        protocol: parsedUrl.protocol.replace(":", "") as "http" | "https",
        connectionRetryCount: 3,
        connectionRetryTimeout: 30000,
        logLevel: "error",
        capabilities: w3cCapabilities,
        strictSSL: false,
      };

      console.log(`Connecting to Appium server: ${appiumUrl}`);
      this.driver = await remote(options);

      const sessionId = this.driver.sessionId;
      console.log(
        `✅ Appium driver initialized successfully with session ID: ${sessionId}`
      );

      return this.driver;
    } catch (error) {
      console.error("Failed to initialize Appium driver:", error);
      throw new AppiumError(
        `Failed to initialize Appium driver: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * W3C Session Management
   */
  async validateSession(): Promise<boolean> {
    if (!this.driver) return false;

    try {
      await this.driver.getPageSource();
      return true;
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);

      if (
        errorMessage.includes("NoSuchDriverError") ||
        errorMessage.includes("terminated") ||
        errorMessage.includes("invalid session id")
      ) {
        console.log("Session terminated, attempting recovery...");

        if (this.lastCapabilities && this.lastAppiumUrl) {
          try {
            try {
              await this.driver.deleteSession();
            } catch {}
            this.driver = null;

            await this.initializeDriver(
              this.lastCapabilities,
              this.lastAppiumUrl
            );
            console.log("✅ Session recovery successful");
            return true;
          } catch {
            console.error("❌ Session recovery failed");
            return false;
          }
        }
      }
      return false;
    }
  }

  async safeExecute<T>(
    operation: () => Promise<T>,
    errorMessage: string
  ): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      if (await this.validateSession()) {
        try {
          return await operation();
        } catch (retryError) {
          throw new AppiumError(
            `${errorMessage}: ${
              retryError instanceof Error
                ? retryError.message
                : String(retryError)
            }`,
            retryError instanceof Error ? retryError : undefined
          );
        }
      }

      throw new AppiumError(
        `${errorMessage}: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  getDriver(): Browser {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }
    return this.driver;
  }

  async closeDriver(): Promise<void> {
    if (this.driver) {
      try {
        await this.driver.deleteSession();
        console.log("✅ Appium session closed successfully");
      } catch (error) {
        console.warn(
          "⚠️ Error while closing Appium session:",
          error instanceof Error ? error.message : String(error)
        );
      } finally {
        this.driver = null;
      }
    }
  }

  /**
   * W3C Element Location Strategies
   */
  async findElement(
    selector: string,
    strategy: string = "xpath",
    timeoutMs: number = 10000
  ): Promise<WebdriverIO.Element> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    return this.safeExecute(async () => {
      const startTime = Date.now();
      let lastError: Error | undefined;

      while (Date.now() - startTime < timeoutMs) {
        try {
          let element: WebdriverIO.Element;

          switch (strategy.toLowerCase()) {
            case "id":
              element = await this.driver!.$(`[id=\"${selector}\"]`);
              break;
            case "xpath":
              element = await this.driver!.$(selector);
              break;
            case "accessibility id":
              element = await this.driver!.$(`~${selector}`);
              break;
            case "class name":
              element = await this.driver!.$(`.${selector}`);
              break;
            case "tag name":
              element = await this.driver!.$(`<${selector}>`);
              break;
            case "name":
              element = await this.driver!.$(`[name=\"${selector}\"]`);
              break;
            case "link text":
              element = await this.driver!.$(`=${selector}`);
              break;
            case "partial link text":
              element = await this.driver!.$(`*=${selector}`);
              break;
            case "css selector":
              element = await this.driver!.$(selector);
              break;
            // Mobile-specific strategies
            case "android uiautomator":
              element = await this.driver!.$(`android=${selector}`);
              break;
            case "ios predicate string":
              element = await this.driver!.$(
                `-ios predicate string:${selector}`
              );
              break;
            case "ios class chain":
              element = await this.driver!.$(`-ios class chain:${selector}`);
              break;
            case "android viewtag":
              element = await this.driver!.$(`android.viewtag=${selector}`);
              break;
            case "android datamatcher":
              element = await this.driver!.$(`android.datamatcher=${selector}`);
              break;
            case "windows uiautomation":
              element = await this.driver!.$(`windows=${selector}`);
              break;
            default:
              element = await this.driver!.$(selector);
          }

          await element.waitForExist({ timeout: Math.min(timeoutMs, 5000) });
          return element;
        } catch (error) {
          lastError = error instanceof Error ? error : new Error(String(error));
          await new Promise((resolve) => setTimeout(resolve, this.retryDelay));
        }
      }

      throw new AppiumError(
        `Failed to find element with selector ${selector} using strategy ${strategy} after ${timeoutMs}ms: ${lastError?.message}`,
        lastError
      );
    }, `Failed to find element with selector ${selector}`);
  }

  async findElements(
    selector: string,
    strategy: string = "xpath"
  ): Promise<WebdriverIO.ElementArray> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      let elements: WebdriverIO.ElementArray;

      switch (strategy.toLowerCase()) {
        case "id":
          elements = await this.driver.$$(`[id=\"${selector}\"]`);
          break;
        case "xpath":
          elements = await this.driver.$$(selector);
          break;
        case "accessibility id":
          elements = await this.driver.$$(`~${selector}`);
          break;
        case "class name":
          elements = await this.driver.$$(`.${selector}`);
          break;
        case "tag name":
          elements = await this.driver.$$(`<${selector}>`);
          break;
        case "name":
          elements = await this.driver.$$(`[name=\"${selector}\"]`);
          break;
        case "link text":
          elements = await this.driver.$$(`=${selector}`);
          break;
        case "partial link text":
          elements = await this.driver.$$(`*=${selector}`);
          break;
        case "css selector":
          elements = await this.driver.$$(selector);
          break;
        case "android uiautomator":
          elements = await this.driver.$$(`android=${selector}`);
          break;
        case "ios predicate string":
          elements = await this.driver.$$(`-ios predicate string:${selector}`);
          break;
        case "ios class chain":
          elements = await this.driver.$$(`-ios class chain:${selector}`);
          break;
        default:
          elements = await this.driver.$$(selector);
      }

      return elements;
    } catch (error) {
      throw new AppiumError(
        `Failed to find elements with selector ${selector}: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * W3C Element Interaction Actions
   */
  async click(selector: string, strategy: string = "xpath"): Promise<boolean> {
    return this.tapElement(selector, strategy);
  }

  async tapElement(
    selector: string,
    strategy: string = "xpath"
  ): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    return this.safeExecute(async () => {
      let lastError: Error | undefined;
      console.log(`🎯 Attempting to tap element with ${strategy}: ${selector}`);

      for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
        try {
          const element = await this.findElement(selector, strategy, 10000);
          await element.waitForDisplayed({ timeout: 5000 });

          // Method 1: Standard W3C element click
          try {
            await element.click();
            await new Promise((resolve) => setTimeout(resolve, 300));
            console.log("✅ Standard click successful");
            return true;
          } catch (clickError) {
            console.log(`❌ Standard click failed: ${clickError}`);
          }

          // Method 2: W3C Actions API
          try {
            const location = await element.getLocation();
            const size = await element.getSize();
            const centerX = Math.round(location.x + size.width / 2);
            const centerY = Math.round(location.y + size.height / 2);

            const w3cActions: W3CPointerAction[] = [
              {
                type: "pointer",
                id: "finger1",
                parameters: { pointerType: "touch" },
                actions: [
                  {
                    type: "pointerMove",
                    duration: 0,
                    x: centerX,
                    y: centerY,
                    origin: "viewport",
                  },
                  { type: "pointerDown", button: 0 },
                  { type: "pause", duration: 100 },
                  { type: "pointerUp", button: 0 },
                ],
              },
            ];

            await this.driver!.performActions(w3cActions);
            await new Promise((resolve) => setTimeout(resolve, 300));
            console.log("✅ W3C Actions tap successful");
            return true;
          } catch (w3cError) {
            console.log(`❌ W3C Actions failed: ${w3cError}`);
          }

          // Method 3: Mobile tap command
          try {
            const location = await element.getLocation();
            const size = await element.getSize();
            const centerX = Math.round(location.x + size.width / 2);
            const centerY = Math.round(location.y + size.height / 2);

            await this.driver!.executeScript("mobile: tap", [
              { x: centerX, y: centerY },
            ]);
            await new Promise((resolve) => setTimeout(resolve, 300));
            console.log("✅ Mobile tap successful");
            return true;
          } catch (mobileError) {
            lastError =
              mobileError instanceof Error
                ? mobileError
                : new Error(String(mobileError));
          }
        } catch (error) {
          lastError = error instanceof Error ? error : new Error(String(error));
          console.log(`❌ Tap attempt ${attempt} failed: ${lastError.message}`);

          if (attempt < this.maxRetries) {
            await new Promise((resolve) =>
              setTimeout(resolve, this.retryDelay * attempt)
            );
          }
        }
      }

      throw new AppiumError(
        `Failed to tap element after ${this.maxRetries} attempts: ${lastError?.message}`,
        lastError
      );
    }, `Failed to tap element with selector ${selector}`);
  }

  async sendKeys(
    selector: string,
    text: string,
    strategy: string = "xpath"
  ): Promise<boolean> {
    return this.safeExecute(async () => {
      let lastError: Error | undefined;
      for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
        try {
          let element = await this.findElement(selector, strategy);
          
          // Check if element is displayed
          const isDisplayed = await element.isDisplayed();
          if (!isDisplayed) {
            throw new Error(`Element found but not displayed. Element may be hidden or off-screen.`);
          }

          // If the located element is not an editable input, try to resolve to a descendant EditText
          try {
            const tagName = await element.getTagName();
            if (!/edittext/i.test(tagName)) {
              console.log(`⚠️  Element is not an EditText (tag: ${tagName}), searching for descendant EditText...`);
              
              // Strategy 1: Try direct descendant EditText
              try {
                const descendantInput = await element.$('descendant::android.widget.EditText[1]');
                if (await descendantInput.isExisting()) {
                  element = descendantInput;
                  console.log(`✅ Found descendant EditText, using it instead of container`);
                } else {
                  throw new Error('No descendant EditText found');
                }
              } catch (e1) {
                // Strategy 2: Try by class name
                try {
                  const xpathInput = await element.$(`descendant::*[@class='android.widget.EditText'][1]`);
                  if (await xpathInput.isExisting()) {
                    element = xpathInput;
                    console.log(`✅ Found EditText via class name, using it instead of container`);
                  } else {
                    throw new Error('No EditText found by class');
                  }
                } catch (e2) {
                  // Strategy 3: Try finding any input-like element with common patterns
                  try {
                    const resourceId = await element.getAttribute('resource-id');
                    if (resourceId) {
                      // If container has resource-id, try to find EditText with similar pattern
                      const baseId = resourceId.replace(/_chip_group|_container|_wrapper|_layout|_search_box/g, '');
                      const inputPatterns = [
                        `${baseId}_input`,
                        `${baseId}_text_input`,
                        `${baseId}_edit_text`,
                        `${baseId}_field`,
                        `${baseId}_autocomplete_input`,
                        `${baseId}_input_field`
                      ];
                      
                      for (const pattern of inputPatterns) {
                        try {
                          const inputElement = await this.driver!.$(`android=new UiSelector().resourceId("${pattern}")`);
                          if (await inputElement.isExisting()) {
                            element = inputElement;
                            console.log(`✅ Found EditText with pattern ${pattern}, using it instead of container`);
                            break;
                          }
                        } catch (e) {
                          continue;
                        }
                      }
                    }
                  } catch (e3) {
                    // Strategy 4: Try XPath with resource-id pattern matching
                    try {
                      const resourceId = await element.getAttribute('resource-id');
                      if (resourceId) {
                        const baseId = resourceId.replace(/_chip_group|_container|_wrapper|_layout|_search_box/g, '');
                        const escapedBaseId = baseId.replace(/:/g, '\\:');
                        const xpathPattern = `//android.widget.EditText[contains(@resource-id, '${escapedBaseId}') and (contains(@resource-id, '_input') or contains(@resource-id, '_edit_text') or contains(@resource-id, '_field'))]`;
                        const xpathElement = await this.driver!.$(`xpath=${xpathPattern}`);
                        if (await xpathElement.isExisting()) {
                          element = xpathElement;
                          console.log(`✅ Found EditText via XPath pattern matching, using it instead of container`);
                        }
                      }
                    } catch (e4) {
                      console.log(`⚠️  Could not find descendant EditText using any strategy`);
                    }
                  }
                }
              }
            }
          } catch (descErr) {
            // Non-fatal: continue with original element
            console.log(`⚠️  Could not find descendant EditText, using original element: ${descErr}`);
          }

          // Try to click the element first to focus it (for Android input fields)
          try {
            await element.click();
            await new Promise((resolve) => setTimeout(resolve, 300)); // Small delay for focus
          } catch (clickError) {
            console.log(`⚠️  Could not click element before typing (may not be necessary): ${clickError}`);
          }

          // Clear existing value
          try {
            await element.clearValue();
          } catch (clearError) {
            // Not all elements support clearValue, that's okay
            console.log(`⚠️  Could not clear element value: ${clearError}`);
          }

          // Try setValue first (WebdriverIO standard method)
          try {
            await element.setValue(text);
            console.log(`✅ Send keys successful using setValue`);
            return true;
          } catch (setValueError) {
            // If setValue fails, try alternative: addValue (sometimes works better on Android)
            console.log(`⚠️  setValue failed, trying addValue: ${setValueError}`);
            try {
              await element.addValue(text);
              console.log(`✅ Send keys successful using addValue`);
              return true;
            } catch (addValueError) {
              // If both fail, throw the last error
              throw new Error(`Both setValue and addValue failed. Element may not be an input field. setValue error: ${setValueError}, addValue error: ${addValueError}`);
            }
          }
        } catch (error) {
          lastError = error instanceof Error ? error : new Error(String(error));
          console.log(`❌ Send keys attempt ${attempt}/${this.maxRetries} failed: ${lastError.message}`);
          if (attempt < this.maxRetries) {
            await new Promise((resolve) =>
              setTimeout(resolve, this.retryDelay)
            );
          }
        }
      }
      // All retries exhausted
      console.log(`❌ Send keys failed after ${this.maxRetries} attempts: ${lastError?.message || 'Unknown error'}`);
      return false;
    }, `Failed to send keys to element with selector ${selector}`);
  }

  async clearElement(
    selector: string,
    strategy: string = "xpath"
  ): Promise<boolean> {
    try {
      const element = await this.findElement(selector, strategy);
      await element.clearValue();
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to clear element: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getText(selector: string, strategy: string = "xpath"): Promise<string> {
    try {
      const element = await this.findElement(selector, strategy);
      return await element.getText();
    } catch (error) {
      throw new AppiumError(
        `Failed to get text: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getAttribute(
    selector: string,
    attributeName: string,
    strategy: string = "xpath"
  ): Promise<string | null> {
    try {
      const element = await this.findElement(selector, strategy);
      return await element.getAttribute(attributeName);
    } catch (error) {
      throw new AppiumError(
        `Failed to get attribute: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async isDisplayed(
    selector: string,
    strategy: string = "xpath"
  ): Promise<boolean> {
    try {
      const element = await this.findElement(selector, strategy);
      return await element.isDisplayed();
    } catch {
      return false;
    }
  }

  async isEnabled(
    selector: string,
    strategy: string = "xpath"
  ): Promise<boolean> {
    try {
      const element = await this.findElement(selector, strategy);
      return await element.isEnabled();
    } catch {
      return false;
    }
  }

  async isSelected(
    selector: string,
    strategy: string = "xpath"
  ): Promise<boolean> {
    try {
      const element = await this.findElement(selector, strategy);
      return await element.isSelected();
    } catch {
      return false;
    }
  }

  /**
   * W3C Touch Actions / Gestures
   */
  async swipe(
    startX: number,
    startY: number,
    endX: number,
    endY: number,
    duration: number = 800
  ): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const w3cActions: W3CPointerAction[] = [
        {
          type: "pointer",
          id: "finger1",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: Math.round(startX),
              y: Math.round(startY),
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            {
              type: "pointerMove",
              duration: duration,
              x: Math.round(endX),
              y: Math.round(endY),
              origin: "viewport",
            },
            { type: "pointerUp", button: 0 },
          ],
        },
      ];

      await this.driver.performActions(w3cActions);
      console.log("✅ W3C swipe successful");
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to perform swipe: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async scroll(
    direction: "up" | "down" | "left" | "right",
    distance: number = 0.5
  ): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const size = await this.driver.getWindowSize();
      const midX = size.width / 2;
      const midY = size.height / 2;

      let startX, startY, endX, endY;

      // FIXED: Use middle of screen to avoid notification bar (top) and navigation bar (bottom)
      // Start from 40% of screen height (safe zone) to avoid top notification area
      // End at 60% of screen height (safe zone) to avoid bottom navigation
      switch (direction) {
        case "down":
          // Scroll down = swipe UP (content moves up, revealing content below)
          startX = midX;
          startY = size.height * 0.6; // Start from 60% (lower on screen)
          endX = midX;
          endY = size.height * (0.6 - distance * 0.4); // Swipe UP (decrease Y)
          break;
        case "up":
          // Scroll up = swipe DOWN (content moves down, revealing content above)
          startX = midX;
          startY = size.height * 0.4; // Start from 40% (upper on screen, but safe from notification)
          endX = midX;
          endY = size.height * (0.4 + distance * 0.4); // Swipe DOWN (increase Y)
          break;
        case "right":
          startX = size.width * 0.3;
          startY = midY;
          endX = size.width * (0.3 + distance * 0.4);
          endY = midY;
          break;
        case "left":
          startX = size.width * 0.7;
          startY = midY;
          endX = size.width * (0.7 - distance * 0.4);
          endY = midY;
          break;
      }

      // Ensure coordinates are within screen bounds
      startX = Math.max(50, Math.min(size.width - 50, startX));
      startY = Math.max(100, Math.min(size.height - 100, startY)); // Avoid top 100px (notification) and bottom 100px (nav)
      endX = Math.max(50, Math.min(size.width - 50, endX));
      endY = Math.max(100, Math.min(size.height - 100, endY));

      return await this.swipe(startX, startY, endX, endY, 800);
    } catch (error) {
      throw new AppiumError(
        `Failed to scroll ${direction}: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async scrollScreen(
    direction: "down" | "up" | "left" | "right",
    distance: number = 0.5
  ): Promise<boolean> {
    return this.scroll(direction, distance);
  }

  async scrollToElement(
    selector: string,
    strategy: string = "xpath",
    maxScrolls: number = 10,
    direction: "down" | "up" = "down"
  ): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      // STEP 1: Check if element already exists (no scrolling needed)
      const alreadyExists = await this.elementExists(selector, strategy);
      if (alreadyExists) {
        console.log("✅ Element already visible, no scrolling needed");
        return true;
      }

      // STEP 2: Try scrolling in requested direction
      const tryScrolls = async (dir: "down" | "up") => {
        let lastPageSource = "";
        for (let i = 0; i < maxScrolls; i++) {
          // Check if element exists
          const exists = await this.elementExists(selector, strategy);
          if (exists) {
            console.log(`✅ Element found after ${i + 1} scroll(s) in direction ${dir}`);
            return true;
          }

          // Get current page source to detect if we're stuck (same content)
          const currentPageSource = await this.driver!.getPageSource();
          if (currentPageSource === lastPageSource && i > 0) {
            console.log(`⚠️  Page content unchanged after scroll ${i + 1}, may have reached end`);
            // Still continue, but note we might be stuck
          }
          lastPageSource = currentPageSource;

          // Perform scroll (using safe coordinates that avoid notification bar)
          await this.scroll(dir, 0.4); // Reduced distance for more controlled scrolling
          await new Promise((resolve) => setTimeout(resolve, 300)); // Optimized: 300ms is sufficient for content to load (reduced from 600ms)
        }
        return false;
      };

      // Try requested direction first
      if (await tryScrolls(direction)) return true;
      
      // If not found, try opposite direction
      console.log(`Element not found scrolling ${direction}, trying opposite direction...`);
      const opposite = direction === "down" ? "up" : "down";
      return await tryScrolls(opposite);
    } catch (error) {
      throw new AppiumError(
        `Failed to scroll to element: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async pinch(
    centerX: number,
    centerY: number,
    scale: number = 0.5,
    duration: number = 1000
  ): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const startDistance = 100;
      const endDistance = startDistance * scale;

      const finger1StartX = centerX - startDistance / 2;
      const finger1StartY = centerY;
      const finger1EndX = centerX - endDistance / 2;
      const finger1EndY = centerY;

      const finger2StartX = centerX + startDistance / 2;
      const finger2StartY = centerY;
      const finger2EndX = centerX + endDistance / 2;
      const finger2EndY = centerY;

      const w3cActions: W3CPointerAction[] = [
        {
          type: "pointer",
          id: "finger1",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: finger1StartX,
              y: finger1StartY,
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            {
              type: "pointerMove",
              duration: duration,
              x: finger1EndX,
              y: finger1EndY,
              origin: "viewport",
            },
            { type: "pointerUp", button: 0 },
          ],
        },
        {
          type: "pointer",
          id: "finger2",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: finger2StartX,
              y: finger2StartY,
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            {
              type: "pointerMove",
              duration: duration,
              x: finger2EndX,
              y: finger2EndY,
              origin: "viewport",
            },
            { type: "pointerUp", button: 0 },
          ],
        },
      ];

      await this.driver.performActions(w3cActions);
      console.log("✅ Pinch gesture successful");
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to perform pinch: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async zoom(
    centerX: number,
    centerY: number,
    scale: number = 2.0,
    duration: number = 1000
  ): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const startDistance = 50;
      const endDistance = startDistance * scale;

      const finger1StartX = centerX - startDistance / 2;
      const finger1StartY = centerY;
      const finger1EndX = centerX - endDistance / 2;
      const finger1EndY = centerY;

      const finger2StartX = centerX + startDistance / 2;
      const finger2StartY = centerY;
      const finger2EndX = centerX + endDistance / 2;
      const finger2EndY = centerY;

      const w3cActions: W3CPointerAction[] = [
        {
          type: "pointer",
          id: "finger1",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: finger1StartX,
              y: finger1StartY,
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            {
              type: "pointerMove",
              duration: duration,
              x: finger1EndX,
              y: finger1EndY,
              origin: "viewport",
            },
            { type: "pointerUp", button: 0 },
          ],
        },
        {
          type: "pointer",
          id: "finger2",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: finger2StartX,
              y: finger2StartY,
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            {
              type: "pointerMove",
              duration: duration,
              x: finger2EndX,
              y: finger2EndY,
              origin: "viewport",
            },
            { type: "pointerUp", button: 0 },
          ],
        },
      ];

      await this.driver.performActions(w3cActions);
      console.log("✅ Zoom gesture successful");
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to perform zoom: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async longPress(
    selector: string,
    duration: number = 1000,
    strategy: string = "xpath"
  ): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    return this.safeExecute(async () => {
      const element = await this.findElement(selector, strategy);
      const location = await element.getLocation();
      const size = await element.getSize();
      const centerX = Math.round(location.x + size.width / 2);
      const centerY = Math.round(location.y + size.height / 2);

      const w3cActions: W3CPointerAction[] = [
        {
          type: "pointer",
          id: "finger1",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: centerX,
              y: centerY,
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            { type: "pause", duration: duration },
            { type: "pointerUp", button: 0 },
          ],
        },
      ];

      await this.driver!.performActions(w3cActions);
      console.log("✅ Long press successful");
      return true;
    }, `Failed to long press element with selector ${selector}`);
  }

  async doubleTap(
    selector: string,
    strategy: string = "xpath"
  ): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    return this.safeExecute(async () => {
      const element = await this.findElement(selector, strategy);
      const location = await element.getLocation();
      const size = await element.getSize();
      const centerX = Math.round(location.x + size.width / 2);
      const centerY = Math.round(location.y + size.height / 2);

      const w3cActions: W3CPointerAction[] = [
        {
          type: "pointer",
          id: "finger1",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: centerX,
              y: centerY,
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            { type: "pointerUp", button: 0 },
            { type: "pause", duration: 100 },
            { type: "pointerDown", button: 0 },
            { type: "pointerUp", button: 0 },
          ],
        },
      ];

      await this.driver!.performActions(w3cActions);
      console.log("✅ Double tap successful");
      return true;
    }, `Failed to double tap element with selector ${selector}`);
  }

  /**
   * W3C Navigation and Window Management
   */
  async navigateBack(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.back();
    } catch (error) {
      throw new AppiumError(
        `Failed to navigate back: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async navigateForward(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.forward();
    } catch (error) {
      throw new AppiumError(
        `Failed to navigate forward: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async refresh(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.refresh();
    } catch (error) {
      throw new AppiumError(
        `Failed to refresh: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getCurrentUrl(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getUrl();
    } catch (error) {
      throw new AppiumError(
        `Failed to get current URL: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getTitle(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getTitle();
    } catch (error) {
      throw new AppiumError(
        `Failed to get title: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getWindowSize(): Promise<{ width: number; height: number }> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getWindowSize();
    } catch (error) {
      throw new AppiumError(
        `Failed to get window size: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async setWindowSize(width: number, height: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.setWindowSize(width, height);
    } catch (error) {
      throw new AppiumError(
        `Failed to set window size: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * W3C Screenshots and Visual Testing
   */
  async takeScreenshot(name: string = "screenshot", silent: boolean = false): Promise<string> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      await fs.mkdir(this.screenshotDir, { recursive: true });

      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      const filename = `${name}_${timestamp}.png`;
      const filepath = path.join(this.screenshotDir, filename);

      const screenshot = await this.driver.takeScreenshot();
      await fs.writeFile(filepath, Buffer.from(screenshot, "base64"));

      // Only log if not silent (silent for OCR/internal screenshots)
      if (!silent) {
        console.log(`📸 Screenshot saved: ${filepath}`);
      }
      return filepath;
    } catch (error) {
      throw new AppiumError(
        `Failed to take screenshot: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async takeElementScreenshot(
    selector: string,
    name: string = "element",
    strategy: string = "xpath"
  ): Promise<string> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const element = await this.findElement(selector, strategy);
      await fs.mkdir(this.screenshotDir, { recursive: true });

      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      const filename = `${name}_${timestamp}.png`;
      const filepath = path.join(this.screenshotDir, filename);

      const screenshot = await element.takeScreenshot();
      await fs.writeFile(filepath, Buffer.from(screenshot, "base64"));

      console.log(`📸 Element screenshot saved: ${filepath}`);
      return filepath;
    } catch (error) {
      throw new AppiumError(
        `Failed to take element screenshot: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * W3C Page Source and DOM
   */
  async getPageSource(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    return this.safeExecute(async () => {
      return await this.driver!.getPageSource();
    }, "Failed to get page source");
  }

  /**
   * W3C Timeouts
   */
  async setImplicitTimeout(timeoutMs: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.setTimeout({ implicit: timeoutMs });
    } catch (error) {
      throw new AppiumError(
        `Failed to set implicit timeout: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async setPageLoadTimeout(timeoutMs: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.setTimeout({ pageLoad: timeoutMs });
    } catch (error) {
      throw new AppiumError(
        `Failed to set page load timeout: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async setScriptTimeout(timeoutMs: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.setTimeout({ script: timeoutMs });
    } catch (error) {
      throw new AppiumError(
        `Failed to set script timeout: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * W3C Execute Script
   */
  async executeScript(script: string, args: any[] = []): Promise<any> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.executeScript(script, args);
    } catch (error) {
      throw new AppiumError(
        `Failed to execute script: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async executeAsyncScript(script: string, args: any[] = []): Promise<any> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.executeAsyncScript(script, args);
    } catch (error) {
      throw new AppiumError(
        `Failed to execute async script: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * W3C Cookies (for hybrid/web contexts)
   */
  async addCookie(cookie: {
    name: string;
    value: string;
    domain?: string;
    path?: string;
    secure?: boolean;
    httpOnly?: boolean;
    expiry?: number;
  }): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.addCookie(cookie);
    } catch (error) {
      throw new AppiumError(
        `Failed to add cookie: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getCookies(): Promise<any[]> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getCookies();
    } catch (error) {
      throw new AppiumError(
        `Failed to get cookies: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async deleteCookie(name: string): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.deleteCookie(name);
    } catch (error) {
      throw new AppiumError(
        `Failed to delete cookie: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async deleteAllCookies(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.deleteAllCookies();
    } catch (error) {
      throw new AppiumError(
        `Failed to delete all cookies: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Mobile-Specific W3C Extensions
   */
  async launchApp(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.launchApp();
    } catch (error) {
      throw new AppiumError(
        `Failed to launch app: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async closeApp(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.closeApp();
    } catch (error) {
      throw new AppiumError(
        `Failed to close app: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async resetApp(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      // Use terminateApp + launchApp instead of reset() which doesn't exist
      const currentPackage = await this.getCurrentPackage();
      await this.driver.terminateApp(currentPackage, {});
      await this.driver.launchApp();
    } catch (error) {
      throw new AppiumError(
        `Failed to reset app: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async terminateApp(bundleId: string): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.terminateApp(bundleId, {});
    } catch (error) {
      throw new AppiumError(
        `Failed to terminate app: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async activateApp(bundleId: string): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.activateApp(bundleId);
    } catch (error) {
      throw new AppiumError(
        `Failed to activate app: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getCurrentPackage(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getCurrentPackage();
    } catch (error) {
      throw new AppiumError(
        `Failed to get current package: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getCurrentActivity(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getCurrentActivity();
    } catch (error) {
      throw new AppiumError(
        `Failed to get current activity: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getDeviceTime(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getDeviceTime();
    } catch (error) {
      throw new AppiumError(
        `Failed to get device time: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async isAppInstalled(bundleId: string): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.isAppInstalled(bundleId);
    } catch (error) {
      throw new AppiumError(
        `Failed to check if app is installed: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async installApp(appPath: string): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.installApp(appPath);
    } catch (error) {
      throw new AppiumError(
        `Failed to install app: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async removeApp(bundleId: string): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.removeApp(bundleId);
    } catch (error) {
      throw new AppiumError(
        `Failed to remove app: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Context Management (Native/WebView)
   */
  async getContexts(): Promise<string[]> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      const contexts = await this.driver.getContexts();
      return contexts.map((context) => context.toString());
    } catch (error) {
      throw new AppiumError(
        `Failed to get contexts: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getCurrentContext(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      const context = await this.driver.getContext();
      return context.toString();
    } catch (error) {
      throw new AppiumError(
        `Failed to get current context: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async switchContext(context: string): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.switchContext(context);
    } catch (error) {
      throw new AppiumError(
        `Failed to switch context: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Device Orientation
   */
  async getOrientation(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getOrientation();
    } catch (error) {
      throw new AppiumError(
        `Failed to get orientation: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async setOrientation(orientation: "PORTRAIT" | "LANDSCAPE"): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.setOrientation(orientation);
    } catch (error) {
      throw new AppiumError(
        `Failed to set orientation: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Device Hardware Keys (Android)
   */
  async pressKeyCode(keyCode: number, metaState?: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.pressKeyCode(keyCode, metaState);
    } catch (error) {
      throw new AppiumError(
        `Failed to press key code: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async longPressKeyCode(keyCode: number, metaState?: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.longPressKeyCode(keyCode, metaState);
    } catch (error) {
      throw new AppiumError(
        `Failed to long press key code: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Additional Mobile Methods
   */
  async hideKeyboard(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.hideKeyboard();
    } catch (error) {
      throw new AppiumError(
        `Failed to hide keyboard: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async lockDevice(duration?: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.lock(duration);
    } catch (error) {
      throw new AppiumError(
        `Failed to lock device: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async isDeviceLocked(): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.isLocked();
    } catch (error) {
      throw new AppiumError(
        `Failed to check if device is locked: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async unlockDevice(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.unlock();
    } catch (error) {
      throw new AppiumError(
        `Failed to unlock device: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async openNotifications(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.openNotifications();
    } catch (error) {
      throw new AppiumError(
        `Failed to open notifications: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async pullFile(path: string): Promise<string> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.pullFile(path);
    } catch (error) {
      throw new AppiumError(
        `Failed to pull file: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async pushFile(path: string, data: string): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.pushFile(path, data);
    } catch (error) {
      throw new AppiumError(
        `Failed to push file: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getBatteryInfo(): Promise<{ level: number; state: number }> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      const result = await this.driver.executeScript("mobile: batteryInfo", []);
      return {
        level: result.level || 0,
        state: result.state || 0,
      };
    } catch (error) {
      throw new AppiumError(
        `Failed to get battery info: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getIosSimulators(): Promise<any[]> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const result = await this.driver.executeScript(
        "mobile: listSimulators",
        []
      );
      return (result as any).devices || [];
    } catch (error) {
      throw new AppiumError(
        `Failed to get iOS simulators list: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async findByIosPredicate(
    predicateString: string,
    timeoutMs: number = 10000
  ): Promise<WebdriverIO.Element> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const element = await this.driver.$(
        `-ios predicate string:${predicateString}`
      );
      await element.waitForExist({ timeout: timeoutMs });
      return element;
    } catch (error) {
      throw new AppiumError(
        `Failed to find element with iOS predicate: ${predicateString}`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async findByIosClassChain(
    classChain: string,
    timeoutMs: number = 10000
  ): Promise<WebdriverIO.Element> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const element = await this.driver.$(`-ios class chain:${classChain}`);
      await element.waitForExist({ timeout: timeoutMs });
      return element;
    } catch (error) {
      throw new AppiumError(
        `Failed to find element with iOS class chain: ${classChain}`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async performTouchId(match: boolean): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      await this.driver.executeScript("mobile: performTouchId", [{ match }]);
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to perform Touch ID: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async shakeDevice(): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      await this.driver.executeScript("mobile: shake", []);
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to shake device: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async startRecording(options?: {
    videoType?: string;
    timeLimit?: number;
    videoQuality?: string;
    videoFps?: number;
  }): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const opts = options || {};
      await this.driver.startRecordingScreen(opts);
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to start screen recording: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async stopRecording(): Promise<string> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      const recording = await this.driver.stopRecordingScreen();
      return recording;
    } catch (error) {
      throw new AppiumError(
        `Failed to stop screen recording: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async executeMobileCommand(command: string, args: any[] = []): Promise<any> {
    if (!this.driver) {
      throw new AppiumError(
        "Appium driver not initialized. Call initializeDriver first."
      );
    }

    try {
      return await this.driver.executeScript(`mobile: ${command}`, args);
    } catch (error) {
      throw new AppiumError(
        `Failed to execute mobile command '${command}': ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async sendKeysToDevice(text: string): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.keys(text.split(""));
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to send keys to device: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async sendKeyEvent(keyEvent: string | number): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      if (typeof keyEvent === "string") {
        await this.driver.keys(keyEvent);
      } else {
        await this.driver.pressKeyCode(keyEvent);
      }
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to send key event ${keyEvent}: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getElementAttributes(
    selector: string,
    strategy: string = "xpath"
  ): Promise<Record<string, any>> {
    try {
      const element = await this.findElement(selector, strategy);

      const result: Record<string, any> = {};

      const propertiesToGet = [
        "text",
        "content-desc",
        "resource-id",
        "class",
        "enabled",
        "displayed",
        "selected",
        "checked",
        "focusable",
        "focused",
        "scrollable",
        "clickable",
        "bounds",
        "package",
        "password",
      ];

      for (const prop of propertiesToGet) {
        try {
          result[prop] = await element.getAttribute(prop);
        } catch {
          // Ignore errors for attributes that may not exist
        }
      }

      try {
        result.location = await element.getLocation();
        result.size = await element.getSize();
      } catch {
        // Ignore if not available
      }

      return result;
    } catch (error) {
      throw new AppiumError(
        `Failed to get element attributes: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Static helper for creating W3C capabilities
   */
  static createW3CCapabilities(
    platform: "Android" | "iOS",
    options: {
      deviceName?: string;
      udid?: string;
      app?: string;
      appPackage?: string;
      appActivity?: string;
      bundleId?: string;
      automationName?: "UiAutomator2" | "XCUITest" | "Espresso" | "Flutter";
      noReset?: boolean;
      fullReset?: boolean;
      newCommandTimeout?: number;
      [key: string]: any;
    } = {}
  ): AppiumCapabilities {
    const baseCapabilities: AppiumCapabilities = {
      platformName: platform,
    };

    if (platform === "Android") {
      baseCapabilities["appium:automationName"] =
        options.automationName || "UiAutomator2";
      if (options.appPackage)
        baseCapabilities["appium:appPackage"] = options.appPackage;
      if (options.appActivity)
        baseCapabilities["appium:appActivity"] = options.appActivity;
    } else if (platform === "iOS") {
      baseCapabilities["appium:automationName"] =
        options.automationName || "XCUITest";
      if (options.bundleId)
        baseCapabilities["appium:bundleId"] = options.bundleId;
    }

    // Add common capabilities with appium: prefix
    if (options.deviceName)
      baseCapabilities["appium:deviceName"] = options.deviceName;
    if (options.udid) baseCapabilities["appium:udid"] = options.udid;
    if (options.app) baseCapabilities["appium:app"] = options.app;
    if (options.noReset !== undefined)
      baseCapabilities["appium:noReset"] = options.noReset;
    if (options.fullReset !== undefined)
      baseCapabilities["appium:fullReset"] = options.fullReset;
    if (options.newCommandTimeout)
      baseCapabilities["appium:newCommandTimeout"] = options.newCommandTimeout;

    // Add any additional options with appium: prefix
    for (const [key, value] of Object.entries(options)) {
      if (
        ![
          "deviceName",
          "udid",
          "app",
          "appPackage",
          "appActivity",
          "bundleId",
          "automationName",
          "noReset",
          "fullReset",
          "newCommandTimeout",
        ].includes(key)
      ) {
        if (!key.startsWith("appium:")) {
          baseCapabilities[`appium:${key}` as keyof AppiumCapabilities] = value;
        } else {
          baseCapabilities[key as keyof AppiumCapabilities] = value;
        }
      }
    }

    return baseCapabilities;
  }

  async inspectElement(
    selector: string,
    strategy: string = "xpath"
  ): Promise<any> {
    try {
      const element = await this.findElement(selector, strategy);
      const attributes = await this.getElementAttributes(selector, strategy);

      // Get additional inspection data
      const elementData: Record<string, any> = {
        ...attributes,
        tagName: await element.getTagName(),
        isDisplayed: await element.isDisplayed(),
        isEnabled: await element.isEnabled(),
        isSelected: await element.isSelected(),
      };

      // Try to get additional properties
      try {
        elementData.rect = await element.getElementRect(element.elementId);
      } catch {
        // Fallback to location and size
        try {
          elementData.location = await element.getLocation();
          elementData.size = await element.getSize();
        } catch {}
      }

      return elementData;
    } catch (error) {
      throw new AppiumError(
        `Failed to inspect element: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getElementTree(): Promise<any> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      const pageSource = await this.driver.getPageSource();

      // For XML-based page sources, return structured data
      try {
        // Simple XML parsing for mobile contexts
        const xmlData = {
          source: pageSource,
          timestamp: new Date().toISOString(),
          type: "mobile_hierarchy",
        };

        return xmlData;
      } catch {
        // Return raw source if parsing fails
        return {
          source: pageSource,
          timestamp: new Date().toISOString(),
          type: "raw",
        };
      }
    } catch (error) {
      throw new AppiumError(
        `Failed to get element tree: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async hasTextInSource(text: string): Promise<boolean> {
    try {
      const pageSource = await this.getPageSource();
      return pageSource.includes(text);
    } catch (error) {
      throw new AppiumError(
        `Failed to check for text in source: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async findElementsByText(text: string): Promise<WebdriverIO.ElementArray> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      // Try multiple strategies for finding text
      const strategies = [
        `//*[@text='${text}']`,
        `//*[contains(@text,'${text}')]`,
        `//*[@content-desc='${text}']`,
        `//*[contains(@content-desc,'${text}')]`,
        `*=${text}`, // WebDriverIO partial text match
        `=${text}`, // WebDriverIO exact text match
      ];

      for (const strategy of strategies) {
        try {
          const elements = await this.driver.$$(strategy);
          if (elements.length > 0) {
            return elements;
          }
        } catch {
          // Continue to next strategy
        }
      }

      // Return empty array if no elements found
      return [] as unknown as WebdriverIO.ElementArray;
    } catch (error) {
      throw new AppiumError(
        `Failed to find elements by text '${text}': ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Helper Utilities
   */
  async waitForElement(
    selector: string,
    strategy: string = "xpath",
    timeoutMs: number = 10000
  ): Promise<WebdriverIO.Element> {
    const startTime = Date.now();
    let lastError: Error | undefined;

    while (Date.now() - startTime < timeoutMs) {
      try {
        const element = await this.findElement(selector, strategy, 1000);
        if (await element.isDisplayed()) {
          return element;
        }
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
      }

      await new Promise((resolve) => setTimeout(resolve, 500));
    }

    throw new AppiumError(
      `Element not found within ${timeoutMs}ms: ${selector}`,
      lastError
    );
  }

  async waitForElementToDisappear(
    selector: string,
    strategy: string = "xpath",
    timeoutMs: number = 10000
  ): Promise<boolean> {
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
      try {
        const exists = await this.elementExists(selector, strategy);
        if (!exists) {
          return true;
        }
      } catch {
        return true; // Element doesn't exist, so it's "disappeared"
      }

      await new Promise((resolve) => setTimeout(resolve, 500));
    }

    return false;
  }

  async elementExists(
    selector: string,
    strategy: string = "xpath",
    timeoutMs: number = 2000
  ): Promise<boolean> {
    try {
      const element = await this.findElement(selector, strategy, timeoutMs);
      return await element.isDisplayed();
    } catch {
      return false;
    }
  }

  async waitUntilElementClickable(
    selector: string,
    strategy: string = "xpath",
    timeoutMs: number = 10000
  ): Promise<WebdriverIO.Element> {
    const startTime = Date.now();
    let lastError: Error | undefined;

    while (Date.now() - startTime < timeoutMs) {
      try {
        const element = await this.findElement(selector, strategy, 1000);
        if ((await element.isDisplayed()) && (await element.isEnabled())) {
          return element;
        }
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
      }

      await new Promise((resolve) => setTimeout(resolve, 500));
    }

    throw new AppiumError(
      `Element not clickable within ${timeoutMs}ms: ${selector}`,
      lastError
    );
  }

  async retryAction<T>(
    action: () => Promise<T>,
    maxRetries: number = 3,
    delay: number = 1000
  ): Promise<T> {
    let lastError: Error | undefined;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        return await action();
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));

        if (attempt < maxRetries) {
          console.log(
            `Retry attempt ${attempt} failed, retrying in ${delay}ms...`
          );
          await new Promise((resolve) => setTimeout(resolve, delay * attempt));
        }
      }
    }

    throw new AppiumError(
      `Action failed after ${maxRetries} attempts`,
      lastError
    );
  }

  /**
   * Advanced Mobile Capabilities
   */
  async getNetworkConnection(): Promise<number> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getNetworkConnection();
    } catch (error) {
      throw new AppiumError(
        `Failed to get network connection: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async setNetworkConnection(type: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.setNetworkConnection({ type });
    } catch (error) {
      throw new AppiumError(
        `Failed to set network connection: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async toggleWifi(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.toggleWiFi();
    } catch (error) {
      throw new AppiumError(
        `Failed to toggle wifi: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async toggleData(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.toggleData();
    } catch (error) {
      throw new AppiumError(
        `Failed to toggle data: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async toggleAirplaneMode(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.toggleAirplaneMode();
    } catch (error) {
      throw new AppiumError(
        `Failed to toggle airplane mode: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async toggleLocationServices(): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.toggleLocationServices();
    } catch (error) {
      throw new AppiumError(
        `Failed to toggle location services: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async setGeoLocation(
    latitude: number,
    longitude: number,
    altitude?: number
  ): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.setGeoLocation({
        latitude,
        longitude,
        altitude: altitude || 0,
      });
    } catch (error) {
      throw new AppiumError(
        `Failed to set geo location: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getGeoLocation(): Promise<{
    latitude: number;
    longitude: number;
    altitude: number;
  }> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      const response = await this.driver.getGeoLocation();
      return response as {
        latitude: number;
        longitude: number;
        altitude: number;
      };
    } catch (error) {
      throw new AppiumError(
        `Failed to get geo location: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Cross-platform compatibility helpers
   */
  async tapByCoordinates(x: number, y: number): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      const w3cActions: W3CPointerAction[] = [
        {
          type: "pointer",
          id: "finger1",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: Math.round(x),
              y: Math.round(y),
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            { type: "pause", duration: 100 },
            { type: "pointerUp", button: 0 },
          ],
        },
      ];

      await this.driver.performActions(w3cActions);
      console.log(`✅ Tap at coordinates (${x}, ${y}) successful`);
      return true;
    } catch (error) {
      throw new AppiumError(
        `Failed to tap at coordinates (${x}, ${y}): ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getElementCenter(
    selector: string,
    strategy: string = "xpath"
  ): Promise<{ x: number; y: number }> {
    try {
      const element = await this.findElement(selector, strategy);
      const location = await element.getLocation();
      const size = await element.getSize();

      return {
        x: Math.round(location.x + size.width / 2),
        y: Math.round(location.y + size.height / 2),
      };
    } catch (error) {
      throw new AppiumError(
        `Failed to get element center: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async isKeyboardShown(): Promise<boolean> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.isKeyboardShown();
    } catch (error) {
      // Some drivers don't support this method, so we'll try alternative approaches
      try {
        // Try to detect keyboard by looking for common keyboard elements
        const pageSource = await this.getPageSource();
        return (
          pageSource.toLowerCase().includes("keyboard") ||
          pageSource.toLowerCase().includes("inputmethod")
        );
      } catch {
        return false;
      }
    }
  }

  /**
   * Performance and debugging utilities
   */
  async getPerformanceData(
    packageName: string,
    dataType: string,
    dataReadTimeout?: number
  ): Promise<any[]> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getPerformanceData(
        packageName,
        dataType,
        dataReadTimeout
      );
    } catch (error) {
      throw new AppiumError(
        `Failed to get performance data: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async getPerformanceDataTypes(): Promise<string[]> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.getPerformanceDataTypes();
    } catch (error) {
      throw new AppiumError(
        `Failed to get performance data types: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  // OCR-based methods for visual testing
  private titanOCR: any = null; // Lazy-loaded OCR instance (uses Claude Sonnet Vision)

  /**
   * Get or create OCR instance (Claude Sonnet Vision)
   */
  private async getTitanOCR(): Promise<any> {
    if (!this.titanOCR) {
      const { TitanOCR } = await import('../ocr/titanOCR.js');
      this.titanOCR = new TitanOCR();
    }
    return this.titanOCR;
  }

  async findTextOnScreen(searchText: string): Promise<{ x: number; y: number } | null> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      // Take screenshot for OCR analysis (silent - don't log)
      const screenshotPath = await this.takeScreenshot(`ocr_search_${Date.now()}.png`, true);
      
      // Use Claude Vision OCR to find text coordinates
      const ocr = await this.getTitanOCR();
      const coordinates = await ocr.findTextCoordinates(screenshotPath, searchText);
      
      if (coordinates) {
        return { x: coordinates.x, y: coordinates.y };
      }
      return null;
    } catch (error) {
      console.error('OCR search failed:', error);
      return null;
    }
  }

  async waitForTextOnScreen(searchText: string, timeoutMs: number = 10000): Promise<boolean> {
    const startTime = Date.now();
    
    while (Date.now() - startTime < timeoutMs) {
      try {
        const coordinates = await this.findTextOnScreen(searchText);
        if (coordinates) {
          return true;
        }
      } catch (error) {
        console.log('OCR search attempt failed, retrying...');
      }
      
      // Wait 1 second before retry
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    
    return false;
  }

  async tapCoordinates(x: number, y: number): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      // Use W3C Actions API for coordinate tapping
      const w3cActions: W3CPointerAction[] = [
        {
          type: "pointer",
          id: "finger1",
          parameters: { pointerType: "touch" },
          actions: [
            {
              type: "pointerMove",
              duration: 0,
              x: Math.round(x),
              y: Math.round(y),
              origin: "viewport",
            },
            { type: "pointerDown", button: 0 },
            { type: "pointerUp", button: 0 },
          ],
        },
      ];

      await this.driver.performActions(w3cActions);
      console.log(`✅ Tapped coordinates (${x}, ${y})`);
    } catch (error) {
      throw new AppiumError(
        `Failed to tap coordinates (${x}, ${y}): ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  async typeText(text: string): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      // Use keyboard input
      await this.driver.keys(text);
    } catch (error) {
      throw new AppiumError(
        `Failed to type text '${text}': ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Extract text from screenshot using Claude Sonnet Vision OCR
   */
  async extractTextFromScreenshot(screenshotPath: string): Promise<{ text: string[]; boundingBoxes: any[]; confidence: number }> {
    try {
      const ocr = await this.getTitanOCR();
      return await ocr.extractTextFromScreenshot(screenshotPath);
    } catch (error) {
      console.error('Claude Vision OCR extraction failed:', error);
      return { text: [], boundingBoxes: [], confidence: 0.0 };
    }
  }

  /**
   * Generate perception summary combining XML and OCR data
   * PRIORITIZES XML - OCR is used automatically when XML fails or is sparse
   * PERFORMANCE: XML first (fast), OCR fallback only when needed
   */
  async generatePerceptionSummary(useOcr: boolean = false): Promise<{
    visible_text: string[];
    elements: Array<{ type: string; text: string; coordinates?: { x: number; y: number } }>;
    ocr_confidence: number;
    xml_available: boolean;
  }> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      // STEP 1: Get XML page source (PRIMARY - FAST and RELIABLE)
      const xmlSource = await this.driver.getPageSource();
      
      // Parse XML to extract elements and text
      const elements = this.parseXMLElements(xmlSource);
      
      // Extract visible text from XML (primary source)
      const xmlTexts = elements.map(el => el.text).filter(text => text && text.trim().length > 0);
      
      // STEP 2: Determine if OCR fallback is needed
      // OCR is used automatically if:
      // 1. Explicitly requested (useOcr=true)
      // 2. XML has very few elements (< 5) - likely custom-rendered UI
      // 3. XML has no text elements - likely image-based UI
      const shouldUseOcr = useOcr || xmlTexts.length < 5 || elements.length < 3;
      
      if (!shouldUseOcr) {
        // Fast path: XML only (no screenshot, no OCR) - XML is sufficient
        return {
          visible_text: xmlTexts,
          elements: elements.map(el => ({
            type: el.type,
            text: el.text,
            coordinates: el.coordinates
          })),
          ocr_confidence: 0.0,
          xml_available: true
        };
      }
      
      // Slow path: XML is sparse or explicitly requested - use OCR fallback
      console.log(`XML has ${xmlTexts.length} text elements, ${elements.length} total elements. Using OCR fallback.`);
      let ocrTexts: string[] = [];
      let ocrConfidence = 0.0;
      
      try {
        // Take screenshot for OCR analysis (silent - don't log)
        const screenshotPath = await this.takeScreenshot(`perception_${Date.now()}.png`, true);
        const ocrResult = await this.extractTextFromScreenshot(screenshotPath);
        ocrTexts = ocrResult.text || [];
        ocrConfidence = ocrResult.confidence || 0.0;
        
        // Merge XML and OCR texts, removing duplicates
        const allTexts = new Set(xmlTexts);
        for (const ocrText of ocrTexts) {
          if (ocrText && ocrText.trim().length > 0) {
            allTexts.add(ocrText.trim());
          }
        }
        
        return {
          visible_text: Array.from(allTexts),
          elements: elements.map(el => ({
            type: el.type,
            text: el.text,
            coordinates: el.coordinates
          })),
          ocr_confidence: ocrConfidence,
          xml_available: true
        };
      } catch (ocrError) {
        // OCR failed - use XML only (this is fine, XML is primary)
        console.warn('OCR extraction failed, using XML-only perception summary:', ocrError);
        return {
          visible_text: xmlTexts,
          elements: elements.map(el => ({
            type: el.type,
            text: el.text,
            coordinates: el.coordinates
          })),
          ocr_confidence: 0.0,
          xml_available: true
        };
      }
    } catch (error) {
      console.error('Perception summary generation failed:', error);
      // Return minimal summary on error
      return {
        visible_text: [],
        elements: [],
        ocr_confidence: 0.0,
        xml_available: false
      };
    }
  }

  /**
   * Parse XML to extract UI elements
   */
  private parseXMLElements(xmlSource: string): Array<{ type: string; text: string; coordinates?: { x: number; y: number } }> {
    const elements: Array<{ type: string; text: string; coordinates?: { x: number; y: number } }> = [];
    
    try {
      // Simple XML parsing - extract buttons, text views, etc.
      const buttonMatches = xmlSource.matchAll(/<([^>]+)\s+[^>]*class="[^"]*Button[^"]*"[^>]*>/g);
      const textMatches = xmlSource.matchAll(/<([^>]+)\s+[^>]*class="[^"]*TextView[^"]*"[^>]*>/g);
      
      // Extract text from elements
      const textPattern = /text="([^"]+)"/g;
      const boundsPattern = /bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/;
      
      for (const match of [...buttonMatches, ...textMatches]) {
        const elementXml = match[0];
        const textMatch = elementXml.match(textPattern);
        const boundsMatch = elementXml.match(boundsPattern);
        
        if (textMatch) {
          const text = textMatch[1];
          const elementType = elementXml.includes('Button') ? 'Button' : 'TextView';
          
          let coordinates;
          if (boundsMatch) {
            const x1 = parseInt(boundsMatch[1], 10);
            const y1 = parseInt(boundsMatch[2], 10);
            const x2 = parseInt(boundsMatch[3], 10);
            const y2 = parseInt(boundsMatch[4], 10);
            coordinates = {
              x: Math.floor((x1 + x2) / 2),
              y: Math.floor((y1 + y2) / 2)
            };
          }
          
          elements.push({ type: elementType, text, coordinates });
        }
      }
    } catch (error) {
      console.error('XML parsing failed:', error);
    }
    
    return elements;
  }

  async startActivity(
    appPackage: string,
    appActivity: string,
    appWaitPackage?: string,
    appWaitActivity?: string,
    intentAction?: string,
    intentCategory?: string,
    intentFlags?: string,
    optionalIntentArguments?: any,
    dontStopAppOnReset?: boolean
  ): Promise<void> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      await this.driver.startActivity(
        appPackage,
        appActivity,
        appWaitPackage,
        appWaitActivity,
        intentAction,
        intentCategory,
        intentFlags,
        optionalIntentArguments,
        dontStopAppOnReset?.toString()
      );
    } catch (error) {
      throw new AppiumError(
        `Failed to start activity: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Cleanup and resource management
   */
  async cleanup(): Promise<void> {
    try {
      if (this.driver) {
        // Try to clean up any ongoing actions
        try {
          await this.driver.releaseActions();
        } catch {
          // Ignore errors during cleanup
        }

        // Close the session
        await this.closeDriver();
      }
    } catch (error) {
      console.warn("Error during cleanup:", error);
    }
  }

  /**
   * Get driver capabilities for debugging
   */
  async getCapabilities(): Promise<any> {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }

    try {
      return await this.driver.capabilities;
    } catch (error) {
      throw new AppiumError(
        `Failed to get capabilities: ${
          error instanceof Error ? error.message : String(error)
        }`,
        error instanceof Error ? error : undefined
      );
    }
  }

  /**
   * Session information
   */
  getSessionId(): string {
    if (!this.driver) {
      throw new AppiumError("Appium driver not initialized");
    }
    return this.driver.sessionId;
  }

  isDriverInitialized(): boolean {
    return this.driver !== null;
  }
}

// Export additional types and utilities
export type { W3CAction, W3CPointerAction, W3CKeyAction, W3CWheelAction };

// Default export
export default AppiumHelper;
