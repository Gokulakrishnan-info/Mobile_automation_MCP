"""
LLM Tools Definition Module

Defines the tools schema for the Anthropic Claude LLM API.
This module contains the tools_list_claude that describes available functions to the LLM.
"""
tools_list_claude = [
    {
        "name": "get_page_source",
        "description": "Get the XML layout of the current screen. Call this first to understand what's on the screen.",
        "input_schema": {
            "type": "object",
            "properties": {}
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
        "description": "Click on a UI element found by strategy and value.",
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
        "description": "Send text input to a UI element. Use this to type text into input fields, search boxes, etc.",
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
        "description": "Launch an Android app by its package name. CRITICAL: Use this BEFORE trying to interact with an app that isn't currently open. Common packages: YouTube=com.google.android.youtube, WhatsApp=com.whatsapp, Calculator=com.google.android.calculator, Chrome=com.android.chrome, Settings=com.android.settings. After launching, always call get_page_source to see the app screen.",
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
        "description": "Scrolls the screen to find an element. IMPORTANT: This function automatically checks if the element is already visible first - if it is, no scrolling is needed. Only scrolls if element is not found. Uses safe scroll coordinates that avoid the notification bar. Automatically tries both directions if needed. Before using this, check page source - if element is visible, use click/type directly instead. If search box is available, use search instead of scroll_to_element.",
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
    }
]

