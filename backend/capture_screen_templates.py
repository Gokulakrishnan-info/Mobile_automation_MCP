"""
Utility script to capture page configuration snapshots for specific apps/screens
and store them as reusable templates under backend/screen_templates/.

Usage:
    python capture_screen_templates.py

Modes:
  • Interactive (default): prompts you for each screen and waits while you manually
    navigate before capturing `get_page_configuration`.
  • Scenario-driven (auto): provide a JSON scenario file describing how to reach
    every screen. The script will execute the listed actions (clicks, waits, etc.)
    for each screen, capture its configuration automatically, and store everything
    in a single template file per app.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import appium_tools as appium

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "screen_templates")
DEFAULT_MAX_ELEMENTS = 150
SCENARIO_KEY_ACTIONS = ("actions", "steps", "before", "preCaptureActions")
SCENARIO_KEY_AFTER = ("after", "postActions", "postCaptureActions")

ACTION_DISPATCH = {
    "launch_app": appium.launch_app,
    "close_app": appium.close_app,
    "reset_app": appium.reset_app,
    "click": appium.click,
    "send_keys": appium.send_keys,
    "ensure_focus_and_type": appium.ensure_focus_and_type,
    "wait_for_element": appium.wait_for_element,
    "wait_for_text_ocr": appium.wait_for_text_ocr,
    "scroll": appium.scroll,
    "scroll_to_element": appium.scroll_to_element,
    "swipe": appium.swipe,
    "long_press": appium.long_press,
    "press_back_button": appium.press_back_button,
    "press_home_button": appium.press_home_button,
    "get_page_source": appium.get_page_source,
    "get_page_configuration": appium.get_page_configuration,
    "get_current_package_activity": appium.get_current_package_activity,
    "take_screenshot": appium.take_screenshot,
    "assert_activity": appium.assert_activity,
    "clear_element": appium.clear_element,
    "get_element_text": appium.get_element_text,
}


def sanitize_filename(name: str) -> str:
    """Convert an app/screen name into a filesystem-friendly slug."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    slug = slug.strip("_").lower()
    return slug or "app_template"


# Common app name to package name mappings
APP_PACKAGE_MAPPINGS = {
    "jiohotstar": "in.startv.hotstar",
    "hotstar": "in.startv.hotstar",
    "disney hotstar": "in.startv.hotstar",
    "netflix": "com.netflix.mediaclient",
    "prime video": "com.amazon.avod.thirdpartyclient",
    "amazon prime": "com.amazon.avod.thirdpartyclient",
    "disney+": "com.disney.disneyplus",
    "disney plus": "com.disney.disneyplus",
    "zee5": "com.zee5.app",
    "sony liv": "com.sonyliv",
    "voot": "com.voot.android",
    "youtube": "com.google.android.youtube",
    "whatsapp": "com.whatsapp",
    "swag labs": "com.swaglabsmobileapp",
    "swaglabs": "com.swaglabsmobileapp",
    "calculator": "com.google.android.calculator",
    "chrome": "com.android.chrome",
    "browser": "com.android.chrome",
    "settings": "com.android.settings",
    "phone": "com.android.dialer",
    "messages": "com.android.mms",
    "gmail": "com.google.android.gm",
    "maps": "com.google.android.apps.maps",
    "play store": "com.android.vending",
}


def find_package_name(app_name: str) -> Optional[str]:
    """
    Attempt to find the package name for an app using:
    1. Common mappings dictionary
    2. ADB package list search
    Returns the package name if found, None otherwise.
    """
    app_name_lower = app_name.lower().strip()
    
    # First, try the mappings
    if app_name_lower in APP_PACKAGE_MAPPINGS:
        return APP_PACKAGE_MAPPINGS[app_name_lower]
    
    # Try partial matches in mappings
    for key, package in APP_PACKAGE_MAPPINGS.items():
        if key in app_name_lower or app_name_lower in key:
            return package
    
    # Try ADB to search installed packages
    try:
        result = subprocess.run(
            ["adb", "shell", "pm", "list", "packages"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            packages = result.stdout.splitlines()
            # Search for packages containing app name keywords
            keywords = app_name_lower.split()
            for pkg_line in packages:
                if "package:" in pkg_line:
                    pkg = pkg_line.replace("package:", "").strip()
                    pkg_lower = pkg.lower()
                    # Check if any keyword matches the package name
                    if any(kw in pkg_lower for kw in keywords if len(kw) > 2):
                        return pkg
                    # Also check if app name is in package (e.g., "hotstar" in "in.startv.hotstar")
                    if any(kw in pkg_lower for kw in keywords):
                        return pkg
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass  # ADB not available or failed
    
    return None


def find_main_activity(package_name: str) -> Optional[str]:
    """
    Attempt to find the main launch activity for a package using ADB.
    Returns the activity name if found, None otherwise.
    """
    if not package_name:
        return None
    
    try:
        # Method 1: Use dumpsys to get main activity
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "package", package_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            output = result.stdout
            # Look for main activity in the output
            # Pattern: Activity filter: ... android.intent.action.MAIN
            lines = output.splitlines()
            in_activity_section = False
            for i, line in enumerate(lines):
                if "Activity filter" in line or "android.intent.action.MAIN" in line:
                    # Look for activity name in nearby lines
                    for j in range(max(0, i - 5), min(len(lines), i + 10)):
                        activity_line = lines[j]
                        # Match pattern like: com.package.name/.MainActivity
                        match = re.search(rf"({re.escape(package_name)}/[^\s]+)", activity_line)
                        if match:
                            activity = match.group(1)
                            # Remove package prefix if present
                            if "/" in activity:
                                return activity.split("/", 1)[1]
                            return activity
        
        # Method 2: Try to resolve main activity directly
        result2 = subprocess.run(
            ["adb", "shell", "cmd", "package", "resolve-activity", "--brief", package_name, "android.intent.action.MAIN"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result2.returncode == 0 and result2.stdout.strip():
            activity = result2.stdout.strip().split()[-1]  # Last part is usually the activity
            if "/" in activity:
                return activity.split("/", 1)[1]
            return activity
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass  # ADB not available or failed
    
    # Fallback: Try common activity patterns
    common_activities = [
        f"{package_name}.MainActivity",
        f"{package_name.replace('.app', '')}.MainActivity",
        f"{package_name.split('.')[-1]}.MainActivity",
    ]
    # We can't verify these exist, but return the most likely one
    return common_activities[0] if common_activities else None


def prompt_non_empty(prompt: str) -> str:
    """Prompt until user enters a non-empty value."""
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a value.")


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt for yes/no, returning a boolean."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        choice = input(f"{prompt} {suffix} ").strip().lower()
        if not choice:
            return default
        if choice in {"y", "yes"}:
            return True
        if choice in {"n", "no"}:
            return False
        print("Please answer 'y' or 'n'.")


def prompt_path(prompt: str) -> Optional[str]:
    """Prompt for a file path and return absolute path if provided."""
    raw = input(prompt).strip()
    if not raw:
        return None
    expanded = os.path.expanduser(raw)
    abs_path = os.path.abspath(expanded)
    if not os.path.exists(abs_path):
        print(f"⚠️  Path does not exist: {abs_path}")
        return None
    return abs_path


def load_scenario_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "screens" not in data or not isinstance(data["screens"], list):
        raise ValueError("Scenario file must contain a 'screens' list.")
    return data


def _result_ok(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, dict):
        return result.get("success", True)
    if isinstance(result, str):
        return not result.lower().startswith("error")
    return True


def run_action(action_def: Dict[str, Any], context: str) -> bool:
    """Execute a single scripted action."""
    tool_name = (action_def.get("tool") or action_def.get("action") or "").strip()
    if not tool_name:
        print(f"[{context}] ⚠️  Skipping unnamed action: {action_def}")
        return True

    tool_key = tool_name.lower()
    args = action_def.get("args", {})

    if tool_key in {"wait", "sleep", "pause"}:
        seconds = action_def.get("seconds") or action_def.get("duration") or args.get("seconds") or args.get("duration") or 1
        print(f"[{context}] ⏱️  Waiting {seconds} second(s)")
        time.sleep(float(seconds))
        return True

    if tool_key == "comment":
        message = action_def.get("message") or args.get("message") or ""
        print(f"[{context}] 📝 {message}")
        return True

    func = ACTION_DISPATCH.get(tool_key)
    if not func:
        print(f"[{context}] ⚠️  Unsupported action '{tool_name}'.")
        return False

    print(f"[{context}] ▶️  {tool_name}({args})")
    try:
        result = func(**args)
    except TypeError as exc:
        print(f"[{context}] ❌ Argument error for {tool_name}: {exc}")
        return False
    except Exception as exc:
        print(f"[{context}] ❌ Action {tool_name} raised: {exc}")
        return False

    ok = _result_ok(result)
    if not ok:
        print(f"[{context}] ⚠️  Action {tool_name} reported failure: {result}")
    return ok


def run_actions(action_list: List[Dict[str, Any]], context: str) -> bool:
    for idx, action in enumerate(action_list, start=1):
        if not run_action(action, f"{context}#{idx}"):
            return False
    return True


def capture_current_screen(include_static: bool = True, max_elements: int = DEFAULT_MAX_ELEMENTS) -> Optional[Dict[str, Any]]:
    result = appium.get_page_configuration(maxElements=max_elements, includeStaticText=include_static)
    if not isinstance(result, dict) or not result.get("success"):
        print(f"⚠️  Failed to capture page configuration: {result}")
        return None
    return result.get("config")


def capture_screen_interactive(screen_name: str) -> Dict[str, Any] | None:
    """Interactive prompt to capture a specific screen."""
    include_static = prompt_yes_no("Include static text (non-interactive labels) in this capture?", True)
    print(f"\n🛈 Navigate to the '{screen_name}' screen now, then press Enter to capture.")
    input("Press Enter when ready...")
    return capture_current_screen(include_static)


def capture_screens_from_scenario(template_data: Dict[str, Any], scenario: Dict[str, Any]) -> int:
    """Execute scenario-driven captures and populate template_data['screens']."""
    defaults = scenario.get("defaults", {})
    default_capture = defaults.get("capture", {})
    max_elements_default = int(default_capture.get("maxElements", DEFAULT_MAX_ELEMENTS))
    include_static_default = bool(default_capture.get("includeStaticText", True))

    global_actions = scenario.get("globalActions") or []
    if global_actions:
        print("\n=== Running global actions ===")
        if not run_actions(global_actions, "global"):
            print("⚠️  Global actions failed; continuing with screens.")

    captured = 0
    screens = scenario.get("screens", [])
    for screen in screens:
        name = screen.get("name")
        if not name:
            print("⚠️  Encountered screen entry without a name. Skipping.")
            continue

        description = screen.get("description", "")
        capture_settings = screen.get("capture", {})
        include_static = capture_settings.get("includeStaticText", include_static_default)
        max_elements = capture_settings.get("maxElements", max_elements_default)

        before_actions = None
        for key in SCENARIO_KEY_ACTIONS:
            if key in screen and isinstance(screen[key], list):
                before_actions = screen[key]
                break
        before_actions = before_actions or []

        after_actions = None
        for key in SCENARIO_KEY_AFTER:
            if key in screen and isinstance(screen[key], list):
                after_actions = screen[key]
                break
        after_actions = after_actions or []

        print(f"\n=== Capturing screen: {name} ===")
        if before_actions:
            print(f"[{name}] Running {len(before_actions)} pre-capture action(s)")
            if not run_actions(before_actions, name):
                print(f"[{name}] ❌ Pre-capture actions failed. Skipping capture.")
                continue

        config = capture_current_screen(include_static=include_static, max_elements=max_elements)
        if not config:
            retry = screen.get("retryOnFailure", False)
            if retry:
                print(f"[{name}] Retrying capture once...")
                config = capture_current_screen(include_static=include_static, max_elements=max_elements)
        if not config:
            print(f"[{name}] ⚠️  Unable to capture screen configuration.")
            continue

        template_data["screens"][name] = {
            "description": description,
            "config": config,
        }
        captured += 1
        print(f"[{name}] ✅ Capture stored")

        if after_actions:
            print(f"[{name}] Running {len(after_actions)} post-capture action(s)")
            run_actions(after_actions, f"{name}-after")

    return captured


def main() -> None:
    os.makedirs(TEMPLATES_DIR, exist_ok=True)

    print("=== Screen Template Capture ===")
    app_name = prompt_non_empty("Enter application name (e.g., 'JioHotstar'): ")
    app_slug = sanitize_filename(app_name)

    # Auto-detect package name
    detected_package = find_package_name(app_name)
    if detected_package:
        print(f"🔍 Auto-detected package: {detected_package}")
        package_name = detected_package
    else:
        print("ℹ️  Could not auto-detect package name.")
        package_name = input("Enter package name (optional, e.g., com.example.app): ").strip() or None
    
    # Auto-detect main activity
    activity_name = None
    if package_name:
        print(f"🔍 Detecting main activity for {package_name}...")
        detected_activity = find_main_activity(package_name)
        if detected_activity:
            print(f"🔍 Auto-detected activity: {detected_activity}")
            activity_name = detected_activity
        else:
            print("ℹ️  Could not auto-detect activity. Will try launching without it.")
    
    # Scenario path is optional - skip if not provided
    scenario_path = prompt_path("Enter scenario JSON path for auto-capture (optional, press Enter to skip): ")
    scenario_data: Optional[Dict[str, Any]] = None
    if scenario_path:
        try:
            scenario_data = load_scenario_file(scenario_path)
            print(f"Loaded scenario with {len(scenario_data.get('screens', []))} screen(s).")
            package_name = scenario_data.get("packageName") or package_name
            activity_name = scenario_data.get("activityName") or activity_name
        except Exception as exc:
            print(f"⚠️  Failed to load scenario: {exc}")
            scenario_data = None

    print("\nInitializing Appium session...")
    session_id = appium.initialize_appium_session()
    if not session_id:
        print("❌ Unable to start Appium session. Please ensure appium-mcp server/device are reachable.")
        sys.exit(1)

    if package_name:
        print(f"Launching app {package_name} ...")
        launch_result = appium.launch_app(packageName=package_name, activityName=activity_name or None)
        if isinstance(launch_result, str) and launch_result.startswith("Error"):
            print(f"⚠️  Launch may have failed: {launch_result}")

    pkg_info = appium.get_current_package_activity()
    if isinstance(pkg_info, dict) and pkg_info.get("success"):
        current_pkg = pkg_info.get("package") or pkg_info.get("packageName")
        current_act = pkg_info.get("activity") or pkg_info.get("activityName")
    else:
        current_pkg = package_name
        current_act = activity_name

    template_data: Dict[str, Any] = {
        "appName": app_name,
        "packageName": current_pkg,
        "initialActivity": current_act,
        "capturedAt": datetime.utcnow().isoformat() + "Z",
        "screens": {},
        "scenarioSource": scenario_path,
    }

    if scenario_data:
        captured = capture_screens_from_scenario(template_data, scenario_data)
    else:
        print("\nEnter screen names to capture. Type 'done' when finished.")
        while True:
            screen_name = input("Screen name (or 'done'): ").strip()
            if not screen_name:
                continue
            if screen_name.lower() in {"done", "exit", "quit"}:
                break

            description = input("Optional description for this screen: ").strip()
            config = capture_screen_interactive(screen_name)
            if not config:
                retry = prompt_yes_no("Capture failed. Try again?", True)
                if retry:
                    continue
                else:
                    print(f"Skipping screen '{screen_name}'.")
                    continue

            template_data["screens"][screen_name] = {
                "description": description,
                "config": config,
            }
            print(f"✅ Captured '{screen_name}'.\n")
        captured = len(template_data["screens"])

    if not template_data["screens"]:
        print("No screens captured. Nothing to save.")
        if package_name:
            appium.close_app()
        return

    output_path = os.path.join(TEMPLATES_DIR, f"{app_slug}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(template_data, f, indent=2, ensure_ascii=False)

    print(f"\n📁 Saved {captured} screen template(s) to {output_path}")

    if prompt_yes_no("Close the app now?", True):
        close_result = appium.close_app()
        if isinstance(close_result, str) and close_result.startswith("Error"):
            print(f"⚠️  Failed to close app: {close_result}")

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")

