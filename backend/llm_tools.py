"""
LLM Tools Definition Module

Defines the tools schema for the Anthropic Claude LLM API.
This module contains the tools_list_claude that describes available functions to the LLM.
"""
tools_list_claude = [
    {
        "name": "get_page_source",
        "description": "Get the XML layout of the current screen. This is the PRIMARY method to understand what's on the screen. Always use this first before taking any action.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_page_configuration",
        "description": "FALLBACK: Generate a structured JSON configuration of the current screen with aliases, roles, and ranked locators. Only use this if get_page_source fails to provide sufficient information or if you need structured element aliases for complex element matching. Prefer get_page_source in most cases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "maxElements": {
                    "type": "number",
                    "description": "Maximum number of elements to include (default 60, max 150)."
                },
                "includeStaticText": {
                    "type": "boolean",
                    "description": "If true, include non-interactive labels and text nodes."
                }
            }
        }
    },
    {
        "name": "wait_for_element",
        "description": "Wait until an element is visible. Use immediately after critical actions (e.g., Login) to assert the next screen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"},
                "timeoutMs": {"type": "number", "description": "Timeout in milliseconds (default 5000)"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "wait_for_text_ocr",
        "description": "Assert that specific text is visible using OCR fallback. Prefer wait_for_element first; use this when UI hierarchy does not expose text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "Text to find on screen"},
                "timeoutSeconds": {"type": "number", "description": "Timeout in seconds (default 5)"}
            },
            "required": ["value"]
        }
    },
    {
        "name": "ensure_focus_and_type",
        "description": "Reliably type into an input: wait -> click (focus) -> send_keys -> optional hide keyboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"},
                "text": {"type": "string"},
                "timeoutMs": {"type": "number"},
                "hideKeyboard": {"type": "boolean", "description": "Hide keyboard after typing (default true)"}
            },
            "required": ["strategy", "value", "text"]
        }
    },
    {
        "name": "assert_activity",
        "description": "Wait until the current Android activity contains the expected name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expectedActivity": {"type": "string"},
                "timeoutSeconds": {"type": "number", "description": "Timeout in seconds (default 5)"}
            },
            "required": ["expectedActivity"]
        }
    },
    {
        "name": "take_screenshot",
        "description": "Take a screenshot of the current screen. Use this to capture visual state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Optional filename for the screenshot"}
            }
        }
    },
    {
        "name": "get_current_package_activity",
        "description": "Get the current app's package name and activity name.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "click",
        "description": "Click on a UI element found by strategy and value. IMPORTANT: Before clicking, call get_page_source and verify the element exists in the current XML snapshot. Use resource-id first (most reliable), then content-desc, then text, with xpath as a last resort. Example: To click a Login button, call get_page_source, find the node with resource-id 'com.app:id/login_button' or text='Login', then call click with strategy='id' and value='com.app:id/login_button'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "send_keys",
        "description": "Send text input to a UI element. Use this to type text into input fields, search boxes, etc. CRITICAL: The target MUST be an editable field (EditText/TextField) rather than a container like ChipGroup or Layout. Before using, call get_page_source and verify the node has class `android.widget.EditText` (or iOS text field). If you only see a container ID (ends with _chip_group, _container, etc.), inspect the XML to find the descendant EditText and use that locator instead. Example: To type 'test@example.com' in an email field, first confirm the EditText’s resource-id in the XML, then call send_keys with strategy='id' and value='com.app:id/email_field'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"},
                "text": {"type": "string", "description": "The text to type into the element"}
            },
            "required": ["strategy", "value", "text"]
        }
    },
    {
        "name": "clear_element",
        "description": "Clear the text content from an editable element.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "get_element_text",
        "description": "Get the visible text content from a specified UI element.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "scroll",
        "description": "Scroll the screen in a direction (up, down, left, right). Direction refers to WHERE YOU WANT TO GO: scroll('down') = go down the page (performs swipe UP to reveal content below), scroll('up') = go up the page (performs swipe DOWN to reveal content above).",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "distance": {"type": "number", "description": "Scroll distance (0.0 to 1.0, default 0.5)"}
            },
            "required": ["direction"]
        }
    },
    {
        "name": "swipe",
        "description": "Swipe from one point to another on the screen. Use for gestures like swiping between screens.",
        "input_schema": {
            "type": "object",
            "properties": {
                "startX": {"type": "number", "description": "Start X coordinate"},
                "startY": {"type": "number", "description": "Start Y coordinate"},
                "endX": {"type": "number", "description": "End X coordinate"},
                "endY": {"type": "number", "description": "End Y coordinate"},
                "duration": {"type": "number", "description": "Swipe duration in milliseconds (default 800)"}
            },
            "required": ["startX", "startY", "endX", "endY"]
        }
    },
    {
        "name": "long_press",
        "description": "Long press (press and hold) on a UI element. Use for context menus or drag operations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"},
                "duration": {"type": "number", "description": "Press duration in milliseconds (default 1000)"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "press_home_button",
        "description": "Press the device's home button. Use to return to the home screen.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "press_back_button",
        "description": "Press the device's back button. Use to go back or close dialogs.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "launch_app",
        "description": "Launch an Android app by its package name. CRITICAL: Use this BEFORE trying to interact with an app that isn't currently open. Common packages: YouTube=com.google.android.youtube, WhatsApp=com.whatsapp, Calculator=com.google.android.calculator, Chrome=com.android.chrome, Settings=com.android.settings. After launching, always call get_page_source to inspect the new screen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "packageName": {"type": "string", "description": "Android app package name (required if launching specific app). Examples: 'com.google.android.youtube' for YouTube, 'com.whatsapp' for WhatsApp."},
                "activityName": {"type": "string", "description": "App activity name (optional). Usually not needed, Appium can determine it automatically."}
            }
        }
    },
    {
        "name": "close_app",
        "description": "Close the current app. Use to exit an application.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "reset_app",
        "description": "Reset the app (terminate and relaunch). Use to restart an app to its initial state.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "scroll_to_element",
        "description": "Scrolls the screen to find an element. IMPORTANT: This function automatically checks if the element is already visible first - if it is, no scrolling is needed. Only scrolls if the element is not found. Uses safe scroll coordinates that avoid the notification bar. Automatically tries both directions if needed. Before using this, inspect the latest get_page_source output; if the element is already present, click/type directly instead. If a search box is available, use search instead of scroll_to_element.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string", "description": "The element to scroll to (e.g., app name, button text)"},
                "maxScrolls": {"type": "number", "description": "Maximum number of scroll attempts (default 10)"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "get_orientation",
        "description": "Get the device orientation (PORTRAIT or LANDSCAPE).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "set_orientation",
        "description": "Set the device orientation (PORTRAIT or LANDSCAPE).",
        "input_schema": {
            "type": "object",
            "properties": {
                "orientation": {"type": "string", "enum": ["PORTRAIT", "LANDSCAPE"]}
            },
            "required": ["orientation"]
        }
    },
    {
        "name": "hide_keyboard",
        "description": "Hide the keyboard if visible. Use after typing text to dismiss the keyboard.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "lock_device",
        "description": "Lock the device screen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "duration": {"type": "number", "description": "Lock duration in seconds (optional)"}
            }
        }
    },
    {
        "name": "unlock_device",
        "description": "Unlock the device screen.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_battery_info",
        "description": "Get device battery information (level and state).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_contexts",
        "description": "Get available contexts (Native/WebView). Use to check if the app has WebView contexts.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "switch_context",
        "description": "Switch between contexts (Native/WebView). Use when the app has both native and web content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Context name to switch to (e.g., 'NATIVE_APP' or 'WEBVIEW_...')"}
            },
            "required": ["context"]
        }
    },
    {
        "name": "open_notifications",
        "description": "Open the notifications panel. Use to view or interact with device notifications.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "is_app_installed",
        "description": "Check if an app is installed on the device.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bundleId": {"type": "string", "description": "App package name or bundle ID"}
            },
            "required": ["bundleId"]
        }
    },
    {
        "name": "get_perception_summary",
        "description": "Get perception summary combining XML page source and OCR text extraction. Provides both structured UI elements and visual text for comprehensive screen understanding.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "verify_action_with_diff",
        "description": "Verify an action succeeded by comparing before/after screenshots using text diff analysis. Returns similarity score and keyword presence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expectedKeywords": {"type": "array", "items": {"type": "string"}, "description": "Keywords that should appear after the action"},
                "beforeScreenshot": {"type": "string", "description": "Path to screenshot taken before action"},
                "afterScreenshot": {"type": "string", "description": "Path to screenshot taken after action"}
            },
            "required": ["expectedKeywords", "beforeScreenshot", "afterScreenshot"]
        }
    },
    {
        "name": "element_exists",
        "description": "Check if an element exists on the current screen without waiting. Returns true/false. Use this to verify element presence before interacting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "get_element_attributes",
        "description": "Get all attributes of an element (resource-id, text, content-desc, class, etc.). Useful for debugging and understanding element properties.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "get_device_time",
        "description": "Get the current device time. Useful for timestamping actions or checking device clock.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pull_file",
        "description": "Pull a file from the device to the local machine. Use to retrieve logs, screenshots, or data files from the device.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file on the device (e.g., /sdcard/file.txt)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "push_file",
        "description": "Push a file from the local machine to the device. Use to upload test data or configuration files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Destination path on the device"},
                "data": {"type": "string", "description": "Base64-encoded file content"}
            },
            "required": ["path", "data"]
        }
    },
    {
        "name": "execute_mobile_command",
        "description": "Execute a custom mobile command (iOS or Android). Use for advanced operations not covered by standard tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Mobile command name (without 'mobile:' prefix)"},
                "args": {"type": "array", "items": {"type": "string"}, "description": "Command arguments (optional)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "perform_w3c_gesture",
        "description": "Perform a W3C standard gesture (tap, longPress, dragAndDrop, pinchZoom, etc.). Use for advanced multi-touch gestures.",
        "input_schema": {
            "type": "object",
            "properties": {
                "gesture": {"type": "object", "description": "W3C gesture definition"}
            },
            "required": ["gesture"]
        }
    },
    {
        "name": "tap_element",
        "description": "Tap on an element (alternative to click). Works the same as click but uses tap terminology.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "scroll_screen",
        "description": "Scroll the entire screen in a direction. Alternative to scroll() with different semantics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]}
            },
            "required": ["direction"]
        }
    },
    {
        "name": "shake_device",
        "description": "Shake the device. Useful for testing shake gestures or triggering shake-related features.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "is_device_locked",
        "description": "Check if the device is currently locked.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_current_context",
        "description": "Get the current context (NATIVE_APP or WEBVIEW_...). Use to check if you're in native or web context.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "press_key_code",
        "description": "Press a key code (Android key codes). Use for hardware keys or special key combinations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keycode": {"type": "number", "description": "Android key code (e.g., 3=HOME, 4=BACK, 24=VOLUME_UP)"}
            },
            "required": ["keycode"]
        }
    },
    {
        "name": "send_key_event",
        "description": "Send a key event to the device. Alternative to press_key_code with different semantics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keycode": {"type": "number", "description": "Key code to send"}
            },
            "required": ["keycode"]
        }
    },
    # Additional Mobile Tools
    {
        "name": "find_by_text",
        "description": "Find an element by its visible text. Returns element information if found.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to search for"},
                "exactMatch": {"type": "boolean", "description": "Whether to match text exactly (default: true)"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "find_elements_by_text",
        "description": "Find all elements matching the given text. Returns array of matching elements.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to search for"},
                "exactMatch": {"type": "boolean", "description": "Whether to match text exactly (default: true)"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "tap_element_by_text",
        "description": "Tap on an element by its visible text. Convenient when you know the text but not the ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text of the element to tap"},
                "exactMatch": {"type": "boolean", "description": "Whether to match text exactly (default: true)"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "get_element_tree",
        "description": "Get the element tree/hierarchy starting from a specific element. Useful for understanding nested UI structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "has_text_in_screen",
        "description": "Check if specific text is present anywhere on the current screen. Returns true/false.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to search for"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "get_current_package",
        "description": "Get the current app's package name (Android) or bundle ID (iOS).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_current_activity",
        "description": "Get the current Android activity name. iOS returns bundle ID.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "smart_tap",
        "description": "Intelligent tap that tries multiple strategies to find and tap an element. More robust than regular tap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "perform_element_action",
        "description": "Perform a specific action on an element (tap, longPress, sendKeys, clear, getAttribute, etc.). Flexible action dispatcher.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["tap", "longPress", "sendKeys", "clear", "getAttribute", "isDisplayed", "isEnabled", "waitForVisible", "waitForInvisible", "swipe"], "description": "Action to perform"},
                "locatorType": {"type": "string", "enum": ["xpath", "id", "accessibilityId", "classname", "name", "text", "androidUIAutomator", "iOSPredicate", "iOSClassChain"], "description": "Locator strategy"},
                "locatorValue": {"type": "string", "description": "Locator value"},
                "actionParams": {"type": "object", "description": "Additional parameters for the action (e.g., text for sendKeys)"},
                "timeoutMs": {"type": "number", "description": "Timeout in milliseconds (default: 10000)"}
            },
            "required": ["action", "locatorType", "locatorValue"]
        }
    },
    {
        "name": "send_keys_to_device",
        "description": "Send keys directly to the device (not to a specific element). Useful for hardware keys or global input.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {"type": "string", "description": "Keys to send (e.g., 'HOME', 'BACK', 'ENTER')"}
            },
            "required": ["keys"]
        }
    },
    {
        "name": "save_ui_hierarchy",
        "description": "Save the current UI hierarchy (XML) to a file. Useful for debugging and analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Filename to save the hierarchy (optional)"}
            }
        }
    },
    # iOS-Specific Tools
    {
        "name": "find_by_ios_class_chain",
        "description": "Find element using iOS Class Chain locator. iOS-specific, more reliable than XPath for iOS.",
        "input_schema": {
            "type": "object",
            "properties": {
                "classChain": {"type": "string", "description": "iOS Class Chain selector"}
            },
            "required": ["classChain"]
        }
    },
    {
        "name": "find_by_ios_predicate",
        "description": "Find element using iOS Predicate String. iOS-specific, powerful for complex queries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "predicate": {"type": "string", "description": "iOS Predicate String (e.g., 'name == \"Button\"')"}
            },
            "required": ["predicate"]
        }
    },
    {
        "name": "tap_by_ios_class_chain",
        "description": "Tap element using iOS Class Chain. iOS-specific alternative to regular tap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "classChain": {"type": "string", "description": "iOS Class Chain selector"}
            },
            "required": ["classChain"]
        }
    },
    {
        "name": "tap_by_ios_predicate",
        "description": "Tap element using iOS Predicate String. iOS-specific alternative to regular tap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "predicate": {"type": "string", "description": "iOS Predicate String"}
            },
            "required": ["predicate"]
        }
    },
    {
        "name": "send_keys_by_ios_class_chain",
        "description": "Send text to element using iOS Class Chain. iOS-specific alternative to send_keys.",
        "input_schema": {
            "type": "object",
            "properties": {
                "classChain": {"type": "string", "description": "iOS Class Chain selector"},
                "text": {"type": "string", "description": "Text to type"}
            },
            "required": ["classChain", "text"]
        }
    },
    {
        "name": "send_keys_by_ios_predicate",
        "description": "Send text to element using iOS Predicate String. iOS-specific alternative to send_keys.",
        "input_schema": {
            "type": "object",
            "properties": {
                "predicate": {"type": "string", "description": "iOS Predicate String"},
                "text": {"type": "string", "description": "Text to type"}
            },
            "required": ["predicate", "text"]
        }
    },
    {
        "name": "list_ios_simulators",
        "description": "List all available iOS simulators. Use to check available iOS devices for testing.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "perform_touch_id",
        "description": "Simulate Touch ID authentication (iOS). Use when app requires biometric authentication.",
        "input_schema": {
            "type": "object",
            "properties": {
                "match": {"type": "boolean", "description": "Whether Touch ID should match (default: true)"}
            }
        }
    },
    # ADB Tools
    {
        "name": "list_devices",
        "description": "List all connected Android devices via ADB. Use to check device availability before automation.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "install_app",
        "description": "Install an Android APK file on a device. Use to install apps before testing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deviceId": {"type": "string", "description": "Device ID (from list_devices)"},
                "apkPath": {"type": "string", "description": "Local path to the APK file"}
            },
            "required": ["deviceId", "apkPath"]
        }
    },
    {
        "name": "uninstall_app",
        "description": "Uninstall an app from the device by package name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deviceId": {"type": "string", "description": "Device ID (optional, uses default if not provided)"},
                "packageName": {"type": "string", "description": "Package name to uninstall (e.g., com.example.app)"}
            },
            "required": ["packageName"]
        }
    },
    {
        "name": "list_installed_packages",
        "description": "List all installed packages on the device. Useful for finding app package names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deviceId": {"type": "string", "description": "Device ID (optional)"}
            }
        }
    },
    {
        "name": "execute_adb_command",
        "description": "Execute a custom ADB command. Use for advanced Android operations not covered by standard tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "ADB command to execute (without 'adb' prefix, e.g., 'shell pm list packages')"}
            },
            "required": ["command"]
        }
    },
    # Inspector & Analysis Tools
    {
        "name": "capture_ui_locators",
        "description": "Capture and extract UI locators from the current screen. Helps identify available selectors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "elementType": {"type": "string", "description": "Filter by element type (optional)"}
            }
        }
    },
    {
        "name": "extract_locators",
        "description": "Extract locators (selectors) from UI XML. Returns available locator strategies for elements.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Element selector to extract locators for"},
                "strategy": {"type": "string", "description": "Current selector strategy"}
            },
            "required": ["selector", "strategy"]
        }
    },
    {
        "name": "generate_element_locators",
        "description": "Generate multiple locator strategies for an element. Helps find alternative selectors if one fails.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Element selector"},
                "strategy": {"type": "string", "description": "Current selector strategy"}
            },
            "required": ["selector", "strategy"]
        }
    },
    {
        "name": "generate_test_script",
        "description": "Generate an Appium test script from a list of actions. Useful for creating reusable test scripts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platformName": {"type": "string", "enum": ["Android", "iOS"], "description": "Target platform"},
                "appPackage": {"type": "string", "description": "App package (Android, optional)"},
                "bundleId": {"type": "string", "description": "Bundle ID (iOS, optional)"},
                "actions": {"type": "array", "items": {"type": "object"}, "description": "List of actions to include in script"}
            },
            "required": ["platformName", "actions"]
        }
    },
    {
        "name": "inspect_element",
        "description": "Inspect a specific element and get detailed information about it (attributes, bounds, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "inspect_and_tap",
        "description": "Inspect an element and then tap it. Combines inspection and action in one call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"}
            },
            "required": ["strategy", "value"]
        }
    },
    {
        "name": "inspect_and_act",
        "description": "Inspect an element and perform a specified action on it. Flexible inspection + action tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "enum": ["id", "text", "xpath", "accessibility_id"]},
                "value": {"type": "string"},
                "action": {"type": "string", "description": "Action to perform (tap, longPress, etc.)"}
            },
            "required": ["strategy", "value", "action"]
        }
    },
    # Recording & Media Tools
    {
        "name": "start_recording",
        "description": "Start recording the device screen. Useful for capturing video of automation sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "options": {"type": "object", "description": "Recording options (optional)"}
            }
        }
    },
    {
        "name": "stop_recording",
        "description": "Stop screen recording and return the recorded video (base64 encoded).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "appium_screenshot",
        "description": "Take a screenshot using Appium (alternative to take_screenshot).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Base name for screenshot file (optional)"}
            }
        }
    },
    # App Management
    {
        "name": "launch_appium_app",
        "description": "Launch the app associated with the current Appium session.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "close_appium",
        "description": "Close the Appium session. Use to clean up after automation.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # Xcode Tools (iOS Simulator Management)
    {
        "name": "xcode_boot_simulator",
        "description": "Boot an iOS simulator. Use before iOS automation if simulator is not running.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_shutdown_simulator",
        "description": "Shutdown an iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_get_ios_simulators",
        "description": "Get list of all iOS simulators with their status and details.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "xcode_get_simulator_status",
        "description": "Get the current status of a specific iOS simulator (booted, shutdown, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_get_simulator_info",
        "description": "Get detailed information about a specific iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_install_app",
        "description": "Install an app (.app bundle) on an iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "appPath": {"type": "string", "description": "Path to .app bundle"}
            },
            "required": ["udid", "appPath"]
        }
    },
    {
        "name": "xcode_uninstall_app",
        "description": "Uninstall an app from iOS simulator by bundle ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "bundleId": {"type": "string", "description": "Bundle ID to uninstall"}
            },
            "required": ["udid", "bundleId"]
        }
    },
    {
        "name": "xcode_launch_app",
        "description": "Launch an app on iOS simulator by bundle ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "bundleId": {"type": "string", "description": "Bundle ID to launch"}
            },
            "required": ["udid", "bundleId"]
        }
    },
    {
        "name": "xcode_terminate_app",
        "description": "Terminate a running app on iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "bundleId": {"type": "string", "description": "Bundle ID to terminate"}
            },
            "required": ["udid", "bundleId"]
        }
    },
    {
        "name": "xcode_take_screenshot",
        "description": "Take a screenshot of iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "filename": {"type": "string", "description": "Screenshot filename (optional)"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_record_video",
        "description": "Record video of iOS simulator screen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "outputPath": {"type": "string", "description": "Output video file path"}
            },
            "required": ["udid", "outputPath"]
        }
    },
    {
        "name": "xcode_list_installed_apps",
        "description": "List all installed apps on iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_create_simulator",
        "description": "Create a new iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Simulator name"},
                "deviceTypeId": {"type": "string", "description": "Device type (e.g., 'iPhone15,2')"},
                "runtimeId": {"type": "string", "description": "iOS runtime ID"}
            },
            "required": ["name", "deviceTypeId", "runtimeId"]
        }
    },
    {
        "name": "xcode_delete_simulator",
        "description": "Delete an iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_erase_simulator",
        "description": "Erase (reset) an iOS simulator to factory settings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_get_device_types",
        "description": "Get list of available iOS device types (iPhone models, iPad models, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "xcode_get_runtimes",
        "description": "Get list of available iOS runtime versions.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "xcode_get_path",
        "description": "Get the path to Xcode installation.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "xcode_get_system_info",
        "description": "Get system information from iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_get_simulator_logs",
        "description": "Get logs from iOS simulator. Useful for debugging app crashes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_wait_for_simulator",
        "description": "Wait until iOS simulator is in a specific state (booted, shutdown, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "state": {"type": "string", "description": "Desired state (e.g., 'Booted')"}
            },
            "required": ["udid", "state"]
        }
    },
    {
        "name": "xcode_set_simulator_location",
        "description": "Set the simulated location (GPS coordinates) for iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "latitude": {"type": "number", "description": "Latitude"},
                "longitude": {"type": "number", "description": "Longitude"}
            },
            "required": ["udid", "latitude", "longitude"]
        }
    },
    {
        "name": "xcode_clear_simulator_location",
        "description": "Clear the simulated location for iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_set_hardware_keyboard",
        "description": "Enable or disable hardware keyboard for iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "enabled": {"type": "boolean", "description": "Whether to enable hardware keyboard"}
            },
            "required": ["udid", "enabled"]
        }
    },
    {
        "name": "xcode_push_notification",
        "description": "Push a notification to iOS simulator. Useful for testing notification handling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "bundleId": {"type": "string", "description": "App bundle ID"},
                "payload": {"type": "object", "description": "Notification payload"}
            },
            "required": ["udid", "bundleId", "payload"]
        }
    },
    {
        "name": "xcode_open_url",
        "description": "Open a URL in iOS simulator (Safari or default browser).",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "url": {"type": "string", "description": "URL to open"}
            },
            "required": ["udid", "url"]
        }
    },
    {
        "name": "xcode_add_media_to_simulator",
        "description": "Add photos or videos to iOS simulator's photo library.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "mediaPath": {"type": "string", "description": "Path to media file"}
            },
            "required": ["udid", "mediaPath"]
        }
    },
    {
        "name": "xcode_copy_to_simulator",
        "description": "Copy files to iOS simulator's file system.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "sourcePath": {"type": "string", "description": "Source file path"},
                "destinationPath": {"type": "string", "description": "Destination path on simulator"}
            },
            "required": ["udid", "sourcePath", "destinationPath"]
        }
    },
    {
        "name": "xcode_shake_device",
        "description": "Simulate shake gesture on iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_trigger_memory_warning",
        "description": "Trigger a memory warning on iOS simulator. Useful for testing app behavior under memory pressure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"}
            },
            "required": ["udid"]
        }
    },
    {
        "name": "xcode_get_privacy_permission",
        "description": "Get privacy permission status (camera, location, etc.) for an app on iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "bundleId": {"type": "string", "description": "App bundle ID"},
                "service": {"type": "string", "description": "Privacy service (e.g., 'camera', 'location')"}
            },
            "required": ["udid", "bundleId", "service"]
        }
    },
    {
        "name": "xcode_grant_privacy_permission",
        "description": "Grant privacy permission to an app on iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "bundleId": {"type": "string", "description": "App bundle ID"},
                "service": {"type": "string", "description": "Privacy service to grant"}
            },
            "required": ["udid", "bundleId", "service"]
        }
    },
    {
        "name": "xcode_revoke_privacy_permission",
        "description": "Revoke privacy permission from an app on iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "bundleId": {"type": "string", "description": "App bundle ID"},
                "service": {"type": "string", "description": "Privacy service to revoke"}
            },
            "required": ["udid", "bundleId", "service"]
        }
    },
    {
        "name": "xcode_reset_privacy_permission",
        "description": "Reset privacy permissions for an app on iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "bundleId": {"type": "string", "description": "App bundle ID"}
            },
            "required": ["udid", "bundleId"]
        }
    },
    {
        "name": "xcode_set_simulator_preference",
        "description": "Set a preference value for iOS simulator.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "domain": {"type": "string", "description": "Preference domain"},
                "key": {"type": "string", "description": "Preference key"},
                "value": {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}, {"type": "object"}], "description": "Preference value (can be string, number, boolean, or object)"}
            },
            "required": ["udid", "domain", "key", "value"]
        }
    },
    {
        "name": "xcode_configure_simulator_preferences",
        "description": "Configure multiple simulator preferences at once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "udid": {"type": "string", "description": "Simulator UDID"},
                "preferences": {"type": "object", "description": "Dictionary of preferences to set"}
            },
            "required": ["udid", "preferences"]
        }
    },
    {
        "name": "xcode_check_cli_installed",
        "description": "Check if Xcode command line tools are installed.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "xcode_install_cli",
        "description": "Install Xcode command line tools (requires user interaction).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]

# All 110+ tools from appium-mcp are now available to the LLM
# Tools are organized by category:
# - Core mobile automation (click, send_keys, scroll, etc.)
# - iOS-specific (find_by_ios_predicate, tap_by_ios_class_chain, etc.)
# - ADB tools (list_devices, install_app, uninstall_app, etc.)
# - Inspector tools (capture_ui_locators, extract_locators, etc.)
# - Xcode tools (iOS simulator management - 38 tools)
# - Recording & media (start_recording, stop_recording)
# All tools are accessible through the HTTP server's /tools/run endpoint

