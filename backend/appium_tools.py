"""
Appium Tools Module

Contains all functions for executing Appium operations via the MCP server.
These functions wrap HTTP requests to the Appium MCP server.
"""
import requests
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Load URL from environment, with a default
# Use 127.0.0.1 instead of localhost for better Windows compatibility
MCP_SERVER_URL = os.getenv('MCP_SERVER_URL', 'http://127.0.0.1:8080')


def initialize_appium_session(capabilities: dict = None):
    """Initialize an Appium session. If capabilities are not provided, uses defaults."""
    print("--- 🔧 Initializing Appium session...")
    try:
        # Default capabilities for Android (can be overridden)
        default_capabilities = {
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:noReset": True
        }
        
        # Merge with provided capabilities
        payload = default_capabilities
        if capabilities:
            payload.update(capabilities)
        
        response = requests.post(f"{MCP_SERVER_URL}/tools/initialize-appium", json=payload)
        response.raise_for_status()
        result = response.json()
        if result.get('success'):
            print(f"--- ✅ Appium session initialized successfully")
            return result.get('sessionId')
        else:
            print(f"--- ❌ Failed to initialize session: {result.get('error')}")
            return None
    except requests.RequestException as e:
        print(f"Error initializing Appium session: {e}")
        return None


def _is_session_crashed_error(error_msg: str) -> bool:
    """Check if error indicates session crash."""
    if not error_msg:
        return False
    error_lower = error_msg.lower()
    crash_indicators = [
        'instrumentation process is not running',
        'cannot be proxied to uiautomator2',
        'probably crashed',
        'session.*crashed',
        'instrumentation.*crashed'
    ]
    return any(indicator in error_lower for indicator in crash_indicators)


def _try_recover_session() -> bool:
    """Attempt to recover crashed session by reinitializing."""
    try:
        print("\n--- [RECOVERY] Detected session crash. Attempting to recover...")
        # Detect device type
        device_type = "Android"
        automation_name = "UiAutomator2"
        
        try:
            import subprocess
            adb_result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if adb_result.returncode == 0 and "device" in adb_result.stdout:
                device_type = "Android"
                automation_name = "UiAutomator2"
                print("--- [INFO] Android device detected for recovery")
        except:
            pass
        
        default_capabilities = {
            "platformName": device_type,
            "appium:automationName": automation_name,
            "appium:noReset": True,
        }
        
        session_id = initialize_appium_session(default_capabilities)
        if session_id:
            print(f"--- [OK] Session recovered: {session_id}")
            return True
        else:
            print("--- [ERROR] Failed to recover session")
            return False
    except Exception as e:
        print(f"--- [ERROR] Session recovery failed: {e}")
        return False


def get_page_source():
    """Gets the XML page source from the appium-mcp server."""
    try:
        payload = {"tool": "get_page_source", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        
        # Parse response
        try:
            result = response.json()
        except:
            # If response is not JSON, treat as error
            error_msg = f"Invalid response from server: {response.text[:200]}"
            print(f"❌ Error: Failed to get page source: {error_msg}")
            return {"success": False, "error": error_msg}
        
        # Check for error responses (even with 200 status)
        if result.get('success') is False:
            error_msg = result.get('error', 'Unknown error')
            # Check if this is a session crash
            if _is_session_crashed_error(error_msg):
                print(f"❌ Error: Session crashed - {error_msg}")
                # Try to recover session
                if _try_recover_session():
                    # Retry once after recovery
                    time.sleep(1)
                    retry_response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload, timeout=10)
                    retry_result = retry_response.json() if retry_response.headers.get('content-type', '').startswith('application/json') else {}
                    if retry_result.get('success'):
                        return retry_result.get('value') or retry_result.get('xml', '')
                    else:
                        return {"success": False, "error": retry_result.get('error', 'Session recovery failed')}
                else:
                    return {"success": False, "error": "Session crashed and recovery failed. Please restart Appium server."}
            print(f"❌ Error: Failed to get page source: {error_msg}")
            return {"success": False, "error": error_msg}
        
        # Handle HTTP error status codes
        if response.status_code == 400:
            error_msg = result.get('error', 'Unknown error')
            if _is_session_crashed_error(error_msg):
                if _try_recover_session():
                    time.sleep(1)
                    retry_response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload, timeout=10)
                    retry_result = retry_response.json() if retry_response.headers.get('content-type', '').startswith('application/json') else {}
                    if retry_result.get('success'):
                        return retry_result.get('value') or retry_result.get('xml', '')
            print(f"❌ Error: Failed to get page source: {error_msg}")
            return {"success": False, "error": error_msg}
        if response.status_code == 500:
            error_msg = result.get('error', f'500 Server Error: {response.text[:200]}')
            if _is_session_crashed_error(error_msg):
                if _try_recover_session():
                    time.sleep(1)
                    retry_response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload, timeout=10)
                    retry_result = retry_response.json() if retry_response.headers.get('content-type', '').startswith('application/json') else {}
                    if retry_result.get('success'):
                        return retry_result.get('value') or retry_result.get('xml', '')
            print(f"❌ Error: Failed to get page source: {error_msg}")
            return {"success": False, "error": error_msg}
        
        response.raise_for_status() 
        # Success case - return XML string
        return result.get('value') or result.get('xml', '')
    except requests.RequestException as e:
        error_msg = str(e)
        print(f"❌ Error: Failed to get page source: {error_msg}")
        return {"success": False, "error": error_msg}


def get_page_configuration(maxElements: int = 60, includeStaticText: bool = False):
    """
    Builds a structured JSON page configuration extracted from the current Appium XML.

    Args:
        maxElements: Maximum number of elements to include in the config (default 60, clamped between 10-150)
        includeStaticText: If True, include non-interactive text labels in addition to interactive elements

    Returns:
        dict: {
            "success": bool,
            "config": { ... structured data ... }
        }
    """
    print(f"--- [CFG] ACT: Generating page configuration (maxElements={maxElements}, includeStaticText={includeStaticText})")

    xml_result = get_page_source()
    xml_text = ""
    if isinstance(xml_result, str):
        xml_text = xml_result
    elif isinstance(xml_result, dict):
        if xml_result.get('success'):
            xml_text = xml_result.get('value') or xml_result.get('xml') or ""
        else:
            return {"success": False, "error": xml_result.get('error', 'Failed to get page source')}
    else:
        xml_text = str(xml_result or "")

    if not xml_text.strip():
        return {"success": False, "error": "Empty page source"}

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as parse_error:
        return {"success": False, "error": f"XML parse error: {parse_error}"}

    def _to_bool(value) -> bool:
        if value is None:
            return False
        return str(value).strip().lower() in ("true", "1", "yes")

    def _slugify(value: str) -> str:
        if not value:
            return ""
        slug = re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_')
        if len(slug) > 64:
            slug = slug[:64]
        return slug

    def _parse_bounds(bounds: str) -> Optional[Dict[str, int]]:
        if not bounds:
            return None
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not match:
            return None
        x1, y1, x2, y2 = map(int, match.groups())
        width = max(0, x2 - x1)
        height = max(0, y2 - y1)
        return {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "width": width,
            "height": height,
            "center": {"x": x1 + width // 2, "y": y1 + height // 2}
        }

    parent_map = {}
    for parent in root.iter():
        for child in list(parent):
            parent_map[child] = parent

    container_keywords = ("layout", "viewgroup", "recyclerview", "scrollview", "viewpager", "listview", "coordinatorlayout")
    alias_counts = {}
    candidates = []
    total_elements = 0

    def _build_xpath(element: ET.Element) -> str:
        segments = []
        current = element
        safety_counter = 0
        while current is not None and safety_counter < 10:
            parent = parent_map.get(current)
            class_name = (current.get('class') or current.get('type') or current.tag or 'node')
            class_name_short = class_name.split('.')[-1]
            if parent is None:
                segments.append(f"/{class_name_short}")
                break
            siblings = [child for child in list(parent) if (child.get('class') or child.get('type') or child.tag) == (current.get('class') or current.get('type') or current.tag)]
            try:
                index = siblings.index(current) + 1
            except ValueError:
                index = 1
            segments.append(f"{class_name_short}[{index}]")
            current = parent
            safety_counter += 1
        segments.reverse()
        xpath = ''.join(segments)
        if not xpath.startswith("/"):
            xpath = "/" + xpath
        return xpath

    def _summarize_element(element: ET.Element, position: int) -> Optional[Dict]:
        class_name = element.get('class') or element.get('type') or element.tag or ''
        class_lower = class_name.lower()
        text = (element.get('text') or "").strip()
        label = (element.get('label') or element.get('name') or "").strip()
        content_desc = (element.get('content-desc') or label).strip()
        resource_id = (element.get('resource-id') or "").strip()
        clickable = _to_bool(element.get('clickable'))
        focusable = _to_bool(element.get('focusable'))
        
        # HEURISTIC: Search icons are functionally clickable even if XML doesn't mark them as such
        # Common search icon patterns: startIcon, searchIcon, search_icon, icon_search, etc.
        if not clickable:
            resource_id_lower = resource_id.lower()
            content_desc_lower = content_desc.lower()
            search_icon_patterns = ['starticon', 'searchicon', 'search_icon', 'icon_search', 'search_button', 'btn_search']
            if any(pattern in resource_id_lower for pattern in search_icon_patterns) or \
               any(pattern in content_desc_lower for pattern in search_icon_patterns):
                clickable = True  # Search icons are functionally clickable
        enabled = not element.get('enabled') or _to_bool(element.get('enabled'))
        checkable = _to_bool(element.get('checkable'))
        checked = _to_bool(element.get('checked'))
        visible_attr = element.get('displayed') or element.get('visible')
        visible = True if visible_attr is None else _to_bool(visible_attr)
        long_clickable = _to_bool(element.get('long-clickable'))
        scrollable = _to_bool(element.get('scrollable'))
        is_editable = _is_editable_element(element)
        has_text = bool(text or content_desc)
        has_id = bool(resource_id)
        is_container = any(keyword in class_lower for keyword in container_keywords)
        is_interactive = clickable or focusable or is_editable or checkable or long_clickable

        include_element = False
        if is_editable or checkable:
            include_element = True
        elif clickable:
            include_element = True
        elif has_id:
            include_element = True
        elif has_text and includeStaticText:
            include_element = True

        if not include_element:
            return None
        if is_container and not is_interactive and not (has_text and includeStaticText):
            return None

        role = "input" if is_editable else \
            ("toggle" if ("switch" in class_lower or "checkbox" in class_lower or checkable) else
             ("button" if ("button" in class_lower or clickable) else
              ("image" if "image" in class_lower else "text")))

        priority = 0
        if is_editable:
            priority += 6
        if clickable:
            priority += 5
        if checkable:
            priority += 4
        if has_id:
            priority += 3
        if has_text:
            priority += 2
        if content_desc:
            priority += 2
        if focusable:
            priority += 1
        if scrollable:
            priority += 1

        def _alias_source() -> str:
            if resource_id:
                return resource_id.split('/')[-1]
            if content_desc:
                return content_desc
            if text:
                return text
            if class_name:
                return class_name.split('.')[-1]
            return f"element_{position}"

        alias_base = _slugify(_alias_source())
        if not alias_base:
            alias_base = f"{role}_{position}"
        alias_counts.setdefault(alias_base, 0)
        alias_counts[alias_base] += 1
        alias = alias_base if alias_counts[alias_base] == 1 else f"{alias_base}_{alias_counts[alias_base]}"

        locators = []
        if resource_id:
            locators.append({"strategy": "id", "value": resource_id, "confidence": "high"})
        if content_desc:
            locators.append({"strategy": "accessibility_id", "value": content_desc, "confidence": "high" if not resource_id else "medium"})
        if text:
            locators.append({"strategy": "text", "value": text, "confidence": "medium"})

        xpath = _build_xpath(element)
        if xpath:
            locators.append({"strategy": "xpath", "value": xpath, "confidence": "fallback"})

        primary_locator = locators[0] if locators else None
        bounds = _parse_bounds(element.get('bounds', ''))

        summary_parts = []
        if text:
            summary_parts.append(f"text='{text}'")
        if content_desc and content_desc != text:
            summary_parts.append(f"desc='{content_desc}'")
        if resource_id:
            summary_parts.append(f"id='{resource_id.split('/')[-1]}'")
        summary_text = ", ".join(summary_parts) if summary_parts else class_name.split('.')[-1]

        element_summary = {
            "alias": alias,
            "role": role,
            "summary": summary_text,
            "primaryLocator": primary_locator,
            "locators": locators,
            "resourceId": resource_id or None,
            "text": text or None,
            "contentDescription": content_desc or None,
            "className": class_name or None,
            "xpath": xpath or None,
            "bounds": bounds,
            "clickable": clickable,
            "focusable": focusable,
            "enabled": enabled,
            "visible": visible,
            "isEditable": is_editable,
            "checkable": checkable,
            "checked": checked,
            "longClickable": long_clickable,
            "scrollable": scrollable,
            "priority": priority
        }
        return element_summary

    for idx, node in enumerate(root.iter()):
        total_elements += 1
        candidate = _summarize_element(node, idx)
        if candidate:
            candidates.append(candidate)

    if not candidates:
        return {
            "success": True,
            "config": {
                "metadata": {
                    "generatedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                    "elementCount": total_elements,
                    "reportedElements": 0,
                    "package": None,
                    "activity": None,
                    "filters": {
                        "maxElements": maxElements,
                        "includeStaticText": includeStaticText
                    }
                },
                "elements": [],
                "roleIndex": {}
            }
        }

    max_elements = max(10, min(int(maxElements or 60), 150))
    candidates.sort(key=lambda item: item.get('priority', 0), reverse=True)
    selected = candidates[:max_elements]

    # Remove internal priority field before returning
    for item in selected:
        item.pop('priority', None)

    role_index: Dict[str, List[str]] = {}
    for item in selected:
        role = item.get('role', 'other')
        role_index.setdefault(role, []).append(item['alias'])

    package_info = {}
    try:
        pkg_result = get_current_package_activity()
        if isinstance(pkg_result, dict):
            package_info = pkg_result
    except Exception:
        package_info = {}

    package_name = package_info.get('package') or package_info.get('packageName') or package_info.get('currentPackage')
    activity_name = package_info.get('activity') or package_info.get('activityName') or package_info.get('currentActivity')

    platform_hint = (
        os.getenv('DEVICE_PLATFORM') or
        os.getenv('PLATFORM_NAME') or
        os.getenv('TARGET_PLATFORM') or
        package_info.get('platform')
    )

    config = {
        "metadata": {
            "generatedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "package": package_name,
            "activity": activity_name,
            "platform": platform_hint,
            "elementCount": total_elements,
            "reportedElements": len(selected),
            "filters": {
                "maxElements": max_elements,
                "includeStaticText": includeStaticText
            }
        },
        "elements": selected,
        "roleIndex": role_index
    }

    return {"success": True, "config": config}


# Editable element detection helpers
ANDROID_EDITABLE_CLASSES = (
    "edittext",
    "autocompletetextview",
    "textinputedittext",
    "searchautocompletetextview",
    "multiautocompletetextview",
    "widget.edittext",
)
IOS_EDITABLE_TYPES = (
    "xcuielementtypetextfield",
    "xcuielementtypesearchfield",
    "xcuielementtypetextview",
    "xcuielementtypesecuretextfield",
)


def _is_editable_element(elem: ET.Element) -> bool:
    class_attr = (elem.get('class') or elem.get('className') or "").lower()
    type_attr = (elem.get('type') or "").lower()
    editable_attr = (elem.get('editable') or elem.get('focusable') or "").lower()
    if any(keyword in class_attr for keyword in ANDROID_EDITABLE_CLASSES):
        return True
    if editable_attr in ("true", "1"):
        if "textview" in class_attr or "textfield" in type_attr:
            return True
    if type_attr and type_attr in IOS_EDITABLE_TYPES:
        return True
    return False


def _collect_elements_matching_strategy(root: ET.Element, strategy: str, value: str) -> List[ET.Element]:
    matches = []
    strategy = (strategy or "").lower()
    value = value or ""
    if not value:
        return matches
    for elem in root.iter():
        res_id = elem.get('resource-id') or ""
        content_desc = elem.get('content-desc') or ""
        text = elem.get('text') or ""
        name = elem.get('name') or elem.get('label') or ""
        if strategy == "id":
            if res_id == value or res_id.endswith(value.split("/")[-1]):
                matches.append(elem)
        elif strategy in ("accessibility_id", "content-desc"):
            if content_desc == value:
                matches.append(elem)
        elif strategy == "text":
            if text == value:
                matches.append(elem)
        elif strategy == "name":
            if name == value:
                matches.append(elem)
    return matches


def _build_locator_from_element(elem: ET.Element) -> Tuple[str, str]:
    res_id = elem.get('resource-id')
    content_desc = elem.get('content-desc')
    text = elem.get('text')
    name = elem.get('name') or elem.get('label')
    class_name = elem.get('class') or elem.get('type')
    index = elem.get('index')
    if res_id:
        return ("id", res_id)
    if content_desc:
        return ("accessibility_id", content_desc)
    if text:
        return ("text", text)
    if name:
        return ("name", name)
    if class_name:
        if index and index.isdigit():
            return ("xpath", f"(//{class_name})[{int(index) + 1}]")
        return ("xpath", f"//{class_name}")
    return ("xpath", "//android.widget.EditText")


def resolve_editable_locator(strategy: str, value: str) -> Tuple[str, str]:
    """
    If a locator points to a non-editable container, find a descendant/sibling EditText/TextField.
    Returns possibly updated (strategy, value).
    
    Enhanced to handle:
    - Container patterns (_chip_group, _container, _wrapper, _layout)
    - Gmail peoplekit patterns
    - Generic EditText detection
    - Resource ID pattern matching
    """
    try:
        xml_result = get_page_source()
        xml_text = ""
        if isinstance(xml_result, str):
            xml_text = xml_result
        elif isinstance(xml_result, dict) and xml_result.get('success'):
            xml_text = xml_result.get('value', '')
        if not xml_text:
            return strategy, value
        root = ET.fromstring(xml_text)
    except Exception:
        return strategy, value

    # Check if target element exists
    matches = _collect_elements_matching_strategy(root, strategy, value)
    if not matches:
        # Element not found - try to find by container pattern matching
        value_lower = value.lower()
        container_patterns = ['_chip_group', '_container', '_wrapper', '_layout', '_viewgroup', '_recycler']
        if any(pattern in value_lower for pattern in container_patterns):
            # Try to find EditText with similar resource-id pattern
            base_id = value
            for pattern in container_patterns:
                base_id = base_id.replace(pattern, '')
            # Try common input patterns
            input_patterns = [
                f"{base_id}_input",
                f"{base_id}_text_input",
                f"{base_id}_edit_text",
                f"{base_id}_field",
                f"{base_id}_autocomplete_input",
                f"{base_id}_input_field",
                f"{base_id}_textfield",
                f"{base_id}_compose_text_field"
            ]
            for pattern in input_patterns:
                for elem in root.iter():
                    res_id = elem.get('resource-id', '')
                    if pattern.lower() in res_id.lower() and _is_editable_element(elem):
                        return _build_locator_from_element(elem)
        return strategy, value

    target_elem = matches[0]
    
    # If target is already editable, return as-is
    if _is_editable_element(target_elem):
        return strategy, value

    # Strategy 1: Search descendants (most common case)
    for descendant in target_elem.iter():
        if descendant is target_elem:
            continue
        if _is_editable_element(descendant):
            resolved = _build_locator_from_element(descendant)
            print(f"--- [RESOLVE] Found editable descendant: {resolved[0]}={resolved[1]}")
            return resolved

    # Strategy 2: Search for EditText with similar resource-id pattern
    res_id = target_elem.get('resource-id', '') or ''
    if res_id:
        # Extract base ID (remove container suffixes)
        base_id = res_id
        container_suffixes = ['_chip_group', '_container', '_wrapper', '_layout', '_viewgroup', '_recycler', '_search_box']
        for suffix in container_suffixes:
            if base_id.endswith(suffix):
                base_id = base_id[:-len(suffix)]
                break
        
        # Try common input patterns based on base ID
        input_patterns = [
            f"{base_id}_input",
            f"{base_id}_text_input",
            f"{base_id}_edit_text",
            f"{base_id}_field",
            f"{base_id}_autocomplete_input",
            f"{base_id}_input_field",
            f"{base_id}_textfield",
            f"{base_id}_compose_text_field"
        ]
        
        # Also try partial matches
        if '/' in base_id:
            id_part = base_id.split('/')[-1]
            input_patterns.extend([
                f"{id_part}_input",
                f"{id_part}_text_input",
                f"{id_part}_edit_text"
            ])
        
        for pattern in input_patterns:
            for elem in root.iter():
                elem_res_id = elem.get('resource-id', '')
                if pattern.lower() in elem_res_id.lower() and _is_editable_element(elem):
                    resolved = _build_locator_from_element(elem)
                    print(f"--- [RESOLVE] Found editable by pattern match: {resolved[0]}={resolved[1]}")
                    return resolved

    # Strategy 3: Search siblings/nearby elements sharing resource prefix
    res_prefix = value.split(":")[-1] if ":" in value else value
    if res_prefix:
        # Try to find EditText with similar prefix
        for elem in root.iter():
            elem_res_id = elem.get('resource-id', '')
            if res_prefix.lower() in elem_res_id.lower() and _is_editable_element(elem):
                resolved = _build_locator_from_element(elem)
                print(f"--- [RESOLVE] Found editable by prefix match: {resolved[0]}={resolved[1]}")
                return resolved

    # Strategy 4: Search for any visible EditText in the input area (last resort)
    # Get bounds of target element to find nearby EditText
    target_bounds = target_elem.get('bounds', '')
    if target_bounds:
        # Find EditText elements and check if they're near the target
        for elem in root.iter():
            if _is_editable_element(elem):
                elem_bounds = elem.get('bounds', '')
                if elem_bounds:
                    # Simple heuristic: if bounds overlap or are close, use it
                    resolved = _build_locator_from_element(elem)
                    print(f"--- [RESOLVE] Found nearby editable: {resolved[0]}={resolved[1]}")
                    return resolved

    # Strategy 5: Fallback - first visible editable element on screen
    for elem in root.iter():
        if _is_editable_element(elem):
            # Check if visible (has bounds and enabled)
            bounds = elem.get('bounds', '')
            enabled = elem.get('enabled', 'true').lower() != 'false'
            if bounds and enabled:
                resolved = _build_locator_from_element(elem)
                print(f"--- [RESOLVE] Found fallback editable: {resolved[0]}={resolved[1]}")
                return resolved

    # No editable element found - return original
    print(f"--- [WARN] Could not resolve editable element for {strategy}={value}")
    return strategy, value


def _normalize_for_match(value: str) -> str:
    """Normalize text for fuzzy matching: remove whitespace and lowercase."""
    if not value:
        return ""
    return re.sub(r"\s+", "", value).lower()


def _find_additional_xml_locators(target_text: str) -> list[dict]:
    """Generate additional locator candidates by parsing XML for near-matches."""
    normalized_target = _normalize_for_match(target_text)
    if not normalized_target:
        return []

    page_source = get_page_source()
    if not page_source or (isinstance(page_source, str) and page_source.startswith("Error")):
        return []

    try:
        root = ET.fromstring(page_source)
    except ET.ParseError:
        return []

    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for elem in root.iter():
        resource_id = elem.get('resource-id', '') or ''
        text_attr = elem.get('text', '') or ''
        content_desc = elem.get('content-desc', '') or ''

        candidate_attrs = [
            (text_attr, 'text'),
            (content_desc, 'accessibility_id'),
        ]

        for attr_value, strategy in candidate_attrs:
            if not attr_value:
                continue
            normalized_attr = _normalize_for_match(attr_value)
            if not normalized_attr:
                continue

            if normalized_target in normalized_attr:
                if resource_id:
                    key = ('id', resource_id)
                    if key not in seen:
                        candidates.append({'strategy': 'id', 'value': resource_id})
                        seen.add(key)

                key = (strategy, attr_value)
                if key not in seen:
                    candidates.append({'strategy': strategy, 'value': attr_value})
                    seen.add(key)

        if resource_id:
            normalized_resource = _normalize_for_match(resource_id)
            if normalized_resource and normalized_target in normalized_resource:
                key = ('id', resource_id)
                if key not in seen:
                    candidates.append({'strategy': 'id', 'value': resource_id})
                    seen.add(key)

    return candidates


def _extract_target_from_xpath(xpath: str) -> tuple[str, str] | None:
    """Extract attribute name and value from simple XPath expressions."""
    if not xpath:
        return None

    equality_pattern = re.compile(r"@([a-zA-Z\-]+)\s*=\s*['\"]([^'\"]+)['\"]")
    contains_pattern = re.compile(r"contains\(\s*@([a-zA-Z\-]+)\s*,\s*['\"]([^'\"]+)['\"]\)")

    match = equality_pattern.search(xpath)
    if match:
        return match.group(1), match.group(2)

    match = contains_pattern.search(xpath)
    if match:
        return match.group(1), match.group(2)

    return None


def click(strategy: str, value: str):
    """Tells the appium-mcp server to click an element."""
    print(f"--- 💪 ACT: Clicking element (strategy={strategy}, value={value})")
    try:
        payload = {"tool": "click", "args": {"strategy": strategy, "value": value}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"--- ❌ RESULT: {{'success': False, 'error': '{error_msg}'}}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            result = {"success": False, "error": str(result)}

        success = result.get('success')
        print_prefix = "✅" if success else "⚠️"
        print(f"--- {print_prefix} RESULT: {result}")

        if success:
            return result

        # Attempt intelligent fallbacks when the primary locator fails
        fallback_candidates: list[dict[str, str]] = []
        seen_locators: set[tuple[str, str]] = {(strategy, value)}
        attempted_fallbacks: list[tuple[str, str]] = []
        target_text: str | None = None

        if strategy == "xpath":
            extracted = _extract_target_from_xpath(value)
            if extracted:
                attr_name, attr_value = extracted
                target_text = attr_value
                attr_map = {
                    "content-desc": ("accessibility_id", attr_value),
                    "content_desc": ("accessibility_id", attr_value),
                    "text": ("text", attr_value),
                    "resource-id": ("id", attr_value),
                    "resource_id": ("id", attr_value),
                    "id": ("id", attr_value),
                }

                mapped = attr_map.get(attr_name)
                if mapped:
                    fallback_candidates.append({"strategy": mapped[0], "value": mapped[1]})

                if attr_name in ("content-desc", "content_desc", "text"):
                    fallback_candidates.append({
                        "strategy": "xpath",
                        "value": f"//*[contains(@{attr_name.replace('_', '-')}, '{attr_value}')]"
                    })
                    fallback_candidates.append({
                        "strategy": "xpath",
                        "value": f"//*[@{attr_name.replace('_', '-') }='{attr_value}']"
                    })
            else:
                target_text = value
        elif strategy in ("accessibility_id", "text", "id"):
            target_text = value
            attr_name = {
                "accessibility_id": "content-desc",
                "text": "text",
                "id": "resource-id"
            }.get(strategy)

            if attr_name:
                fallback_candidates.append({
                    "strategy": "xpath",
                    "value": f"//*[@{attr_name}='{value}']"
                })
                fallback_candidates.append({
                    "strategy": "xpath",
                    "value": f"//*[contains(@{attr_name}, '{value}')]"
                })
        else:
            target_text = value

        if target_text:
            derived_locators = _find_additional_xml_locators(target_text)
            for locator in derived_locators:
                fallback_candidates.append(locator)

        aggregated_errors: list[str] = []

        for locator in fallback_candidates:
            key = (locator.get("strategy", ""), locator.get("value", ""))
            if not key[0] or not key[1] or key in seen_locators:
                continue
            seen_locators.add(key)
            attempted_fallbacks.append(key)

            print(f"--- 🔄 Fallback: Trying click with strategy={key[0]}, value={key[1]}")

            wait_res = wait_for_element(strategy=key[0], value=key[1], timeoutMs=2000)
            if isinstance(wait_res, dict) and wait_res.get('success'):
                try:
                    fallback_payload = {"tool": "click", "args": {"strategy": key[0], "value": key[1]}}
                    fallback_response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=fallback_payload)
                    if fallback_response.status_code == 400:
                        error_msg = fallback_response.json().get('error', 'Unknown error')
                        print(f"--- ❌ RESULT: {{'success': False, 'error': '{error_msg}'}}")
                        aggregated_errors.append(error_msg)
                        continue
                    fallback_response.raise_for_status()
                    fallback_result = fallback_response.json()
                    fallback_success = isinstance(fallback_result, dict) and fallback_result.get('success')
                    print_prefix_fb = "✅" if fallback_success else "⚠️"
                    print(f"--- {print_prefix_fb} RESULT: {fallback_result}")
                    if fallback_success:
                        return fallback_result
                    aggregated_errors.append(str(fallback_result))
                except requests.RequestException as inner_error:
                    error_text = str(inner_error)
                    print(f"--- ❌ RESULT: {{'success': False, 'error': '{error_text}'}}")
                    aggregated_errors.append(error_text)
            else:
                aggregated_errors.append(str(wait_res))

        if aggregated_errors:
            result["error"] = result.get("error") or "; ".join(aggregated_errors)
            if attempted_fallbacks:
                result["fallbackAttempts"] = attempted_fallbacks

        return result
    except requests.RequestException as e:
        print(f"--- ❌ RESULT: {{'success': False, 'error': '{str(e)}'}}")
        return f"Error: {e}"


def find_edittext_from_container(container_id: str) -> tuple[str, str] | None:
    """Helper function to find EditText element from a container ID by parsing page source.
    Returns (strategy, value) tuple if found, None otherwise.
    """
    import xml.etree.ElementTree as ET
    
    container_patterns = ['_chip_group', '_search_box', '_container', '_wrapper', '_layout']
    if not any(pattern in container_id.lower() for pattern in container_patterns):
        return None  # Not a container, skip
    
    try:
        # Get page source
        page_source = get_page_source()
        if not page_source or isinstance(page_source, str) and page_source.startswith("Error"):
            return None
        
        # Parse XML
        root = ET.fromstring(page_source)
        
        # Find the container element
        container_elem = None
        for elem in root.iter():
            resource_id = elem.get('resource-id', '')
            if container_id in resource_id:
                container_elem = elem
                break
        
        if not container_elem:
            return None
        
        # Strategy 1: Find EditText descendant with similar resource-id pattern
        base_id = container_id.replace('_chip_group', '').replace('_container', '').replace('_wrapper', '').replace('_layout', '').replace('_search_box', '')
        input_patterns = [
            f"{base_id}_input",
            f"{base_id}_text_input",
            f"{base_id}_edit_text",
            f"{base_id}_field",
            f"{base_id}_autocomplete_input",
            f"{base_id}_input_field"
        ]
        
        # Search for EditText elements in the tree
        for elem in root.iter():
            if elem.tag == 'EditText' or 'EditText' in elem.get('class', ''):
                resource_id = elem.get('resource-id', '')
                for pattern in input_patterns:
                    if pattern in resource_id:
                        print(f"🔍 Found EditText: {resource_id} (from container {container_id})")
                        return ('id', resource_id)
        
        # Strategy 2: Find any EditText descendant of the container
        def find_edittext_descendant(parent):
            for child in parent:
                if child.tag == 'EditText' or 'EditText' in child.get('class', ''):
                    resource_id = child.get('resource-id', '')
                    if resource_id:
                        return ('id', resource_id)
                result = find_edittext_descendant(child)
                if result:
                    return result
            return None
        
        result = find_edittext_descendant(container_elem)
        if result:
            print(f"🔍 Found EditText descendant: {result[1]} (from container {container_id})")
            return result
        
        return None
    except Exception as e:
        print(f"⚠️  Error finding EditText from container: {e}")
        return None


def send_keys(strategy: str, value: str, text: str):
    """Sends text input to a UI element."""
    # Special handling for "\n" - convert to Enter key event instead of literal text
    if text == '\\n' or text == '\n' or text == '\\n':
        print(f"--- ⌨️  ACT: Sending Enter key event (instead of literal '\\n') to element (strategy={strategy}, value={value})")
        try:
            # First, ensure the element is focused by clicking it (so Enter key goes to the right field)
            click_payload = {"tool": "click", "args": {"strategy": strategy, "value": value}}
            click_response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=click_payload, timeout=30)
            if click_response.status_code == 200:
                import time
                time.sleep(0.2)  # Brief delay for focus
            
            # Use send-key-event tool to send Enter key
            # Use keycode 66 for Android KEYCODE_ENTER (most reliable)
            payload = {"tool": "send-key-event", "args": {"keycode": 66}}
            response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            print(f"--- ✅ RESULT: {result}")
            return result
        except requests.RequestException as e:
            print(f"--- ❌ RESULT: {{'success': False, 'error': '{str(e)}'}}")
            return {"success": False, "error": f"Failed to send Enter key: {str(e)}"}
    
    # Warn if value looks like a container (common patterns)
    container_patterns = ['_chip_group', '_search_box', '_container', '_wrapper', '_layout']
    is_container = any(pattern in value.lower() for pattern in container_patterns)
    
    edittext_info = None
    if is_container:
        print(f"⚠️  WARNING: Selected element '{value}' may be a container, not an EditText.")
        # Try to find EditText automatically
        edittext_info = find_edittext_from_container(value)
        if edittext_info:
            strategy, value = edittext_info
            print(f"✅ Auto-detected EditText: {value} (strategy={strategy})")
        else:
            print(f"⚠️  Could not auto-detect EditText. Server will try to find descendant EditText automatically.")
    
    original_value = value  # Keep original for retry
    print(f"--- ⌨️  ACT: Sending keys '{text}' to element (strategy={strategy}, value={value})")
    try:
        payload = {"tool": "send_keys", "args": {"strategy": strategy, "value": value, "text": text}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"--- ❌ RESULT: {{'success': False, 'error': '{error_msg}'}}")
            # If it failed and we used a container, try to find EditText and retry
            if is_container and edittext_info is None:
                edittext_info = find_edittext_from_container(original_value)
                if edittext_info:
                    strategy, value = edittext_info
                    print(f"🔄 Retrying with auto-detected EditText: {value}")
                    payload = {"tool": "send_keys", "args": {"strategy": strategy, "value": value, "text": text}}
                    response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
                    if response.status_code == 200:
                        result = response.json()
                        print(f"--- ✅ RESULT: {result}")
                        return result
            return f"Error: {error_msg}"
        response.raise_for_status()
        result = response.json()
        print(f"--- ✅ RESULT: {result}")
        return result
    except requests.RequestException as e:
        print(f"--- ❌ RESULT: {{'success': False, 'error': '{str(e)}'}}")
        return f"Error: {e}"


def wait_for_element(strategy: str, value: str, timeoutMs: int = 5000):
    """Wait until an element is visible. Returns { success: true/false }."""
    print(f"--- ⏳ ACT: Waiting for element (strategy={strategy}, value={value}, timeout={timeoutMs}ms)")
    try:
        payload = {"tool": "wait_for_element", "args": {"strategy": strategy, "value": value, "timeoutMs": timeoutMs}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"--- ❌ RESULT: {{'success': False, 'error': '{error_msg}'}}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        result = response.json()
        print(f"--- ✅ RESULT: {result}")
        return result
    except requests.RequestException as e:
        print(f"--- ❌ RESULT: {{'success': False, 'error': '{str(e)}'}}")
        return f"Error: {e}"


def wait_for_text_ocr(value: str, timeoutSeconds: int = 5, sessionId: str = None):
    """Wait for text to be visible using HYBRID approach: XML first, OCR fallback.
    Returns { success: true/false, method: 'element'|'ocr' }.
    
    Strategy:
    1. Try XML-based strategies first (text, content-desc, xpath) - FAST and RELIABLE
    2. AUTOMATICALLY falls back to OCR if XML fails - works for custom-rendered UIs
    """
    print(f"⏳ Assert (Hybrid XML→OCR): Waiting for '{value}' (timeout: {timeoutSeconds}s)")
    try:
        # Ensure we have a sessionId; try to initialize one if missing
        if not sessionId:
            print("⚠️  Warning: No session ID provided. Attempting to initialize a session...")
            try:
                new_session_id = initialize_appium_session()
                if new_session_id:
                    sessionId = new_session_id
                    print(f"🔧 Using newly initialized session ID: {sessionId}")
                else:
                    print("❌ Could not initialize a new Appium session; assertion may fail.")
            except Exception as _:
                pass
        
        # STEP 1: Try XML-based strategies first (FAST and RELIABLE)
        print(f"   Step 1: Trying XML-based detection (text, content-desc, xpath)...")
        
        # Try multiple XML strategies in order of reliability
        lower_value = value.lower()
        xml_strategies = [
            {"strategy": "text", "value": value},
            {"strategy": "accessibility_id", "value": value},
            {"strategy": "xpath", "value": f"//*[@text='{value}']"},
            {"strategy": "xpath", "value": f"//*[contains(@text, '{value}')]"},
            {"strategy": "xpath", "value": f"//*[@content-desc='{value}']"},
            {"strategy": "xpath", "value": f"//*[contains(@content-desc, '{value}')]"},
        ]

        if lower_value != value:
            xml_strategies.extend([
                {
                    "strategy": "xpath",
                    "value": f"//*[contains(translate(@text, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lower_value}')]"
                },
                {
                    "strategy": "xpath",
                    "value": f"//*[contains(translate(@content-desc, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lower_value}')]"
                },
            ])
        
        for strategy_config in xml_strategies:
            try:
                result = wait_for_element(
                    strategy=strategy_config["strategy"],
                    value=strategy_config["value"],
                    timeoutMs=int(timeoutSeconds * 1000)
                )
                if isinstance(result, dict) and result.get('success'):
                    print(f"   ✅ Found via XML ({strategy_config['strategy']})")
                    return {"success": True, "method": "element", "strategy": strategy_config["strategy"]}
            except Exception:
                continue

        derived_locators = _find_additional_xml_locators(value)
        if derived_locators:
            print("   Step 1b: Derived locator candidates from XML (fuzzy match).")
            for locator in derived_locators:
                try:
                    result = wait_for_element(
                        strategy=locator["strategy"],
                        value=locator["value"],
                        timeoutMs=int(timeoutSeconds * 1000)
                    )
                    if isinstance(result, dict) and result.get('success'):
                        print(f"   ✅ Found via derived XML locator ({locator['strategy']} = {locator['value']})")
                        return {"success": True, "method": "element", "strategy": locator["strategy"]}
                except Exception:
                    continue
        
        # STEP 2: XML failed - AUTOMATICALLY try OCR fallback (works for custom UIs)
        print(f"   Step 2: XML not found, automatically trying OCR fallback...")
        
        payload = {
            "locator": {"by": "text", "value": value},
            "fallback_locators": [],
            "timeout": timeoutSeconds,
            "sessionId": sessionId,
            "useOcr": True
        }
        response = requests.post(f"{MCP_SERVER_URL}/tools/wait-for-element", json=payload)
        
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"   ❌ OCR also failed: {error_msg}")
            return {"success": False, "error": f"Text '{value}' not found via XML or OCR", "method": "none"}
        
        response.raise_for_status()
        result = response.json()
        
        if result.get('success'):
            print(f"   ✅ Found via OCR (XML fallback worked)")
        else:
            print(f"   ❌ OCR failed: {result.get('error', 'Unknown error')}")
        
        return result
        
    except requests.RequestException as e:
        print(f"   ❌ Assert failed: {e}")
        return {"success": False, "error": str(e), "method": "none"}


def ensure_focus_and_type(strategy: str, value: str, text: str, timeoutMs: int = 5000, hideKeyboard: bool = True):
    """Reliably type into an input: try click (focus) -> send_keys -> optional hide_keyboard.
    Returns the send_keys result. Waits for element if needed, but doesn't fail if wait fails.
    Automatically tries fallback strategies if the primary strategy fails.
    """
    print(f"--- 🔧 ACT: Ensuring focus and typing '{text}' (strategy={strategy}, value={value})")
    
    # Auto-detect correct strategy if value starts with "test-"
    if value.startswith("test-") and strategy not in ("content-desc", "accessibility_id"):
        print(f"⚠️  WARNING: Value '{value}' starts with 'test-' but strategy is '{strategy}'. Trying 'content-desc' as fallback.")
        fallback_strategy = "content-desc"
    else:
        fallback_strategy = None
    
    # Try to wait for element (non-blocking if it fails)
    strategies_to_try = [(strategy, value)]
    if fallback_strategy:
        strategies_to_try.append((fallback_strategy, value))
    
    element_found = False
    working_strategy = strategy
    working_value = value
    for strat, val in strategies_to_try:
        try:
            wait_res = wait_for_element(strategy=strat, value=val, timeoutMs=timeoutMs)
            if isinstance(wait_res, dict) and wait_res.get('success'):
                element_found = True
                working_strategy = strat
                working_value = val
                print(f"✅ Element found using strategy '{strat}'")
                break
        except Exception:
            continue
    
    if not element_found:
        print(f"⚠️  Element not found with initial strategy, continuing anyway (element might still be clickable)")
    
    # Focus the element (click) - try multiple strategies if needed
    click_success = False
    for strat, val in strategies_to_try:
        click_res = click(strategy=strat, value=val)
        if isinstance(click_res, dict) and click_res.get('success'):
            click_success = True
            working_strategy = strat
            working_value = val
            break
    
    if not click_success:
        print(f"⚠️  Click failed with initial strategy, trying send_keys anyway")
    
    # Check if target is a container before typing
    value_lower = working_value.lower()
    container_patterns = ['_chip_group', '_container', '_wrapper', '_layout', '_viewgroup', '_recycler', '_search_box']
    is_container = any(pattern in value_lower for pattern in container_patterns)
    
    # If container was clicked, wait a moment for UI to update, then refresh XML
    if is_container and click_success:
        print(f"--- [CONTAINER] Detected container element, waiting for UI to update...")
        time.sleep(0.5)  # Brief wait for UI to update after tap
    
    # Resolve actual editable target if needed (especially for containers)
    resolved_strategy, resolved_value = resolve_editable_locator(working_strategy, working_value)
    if (resolved_strategy, resolved_value) != (working_strategy, working_value):
        print(f"--- [SMART] Redirecting text input to editable field via {resolved_strategy}={resolved_value}")
        # Update working values to use resolved locator
        working_strategy = resolved_strategy
        working_value = resolved_value
    
    # Type the text (this is the critical operation) - use the resolved strategy/value
    type_res = send_keys(strategy=working_strategy, value=working_value, text=text)
    
    # Optionally hide keyboard
    if hideKeyboard:
        try:
            hide_keyboard()
        except Exception:
            pass
    
    return type_res


def assert_activity(expectedActivity: str, timeoutSeconds: int = 10):
    """Poll current activity until it matches expectedActivity or timeout.
    Returns { success: true/false, activity: currentActivity }.
    """
    deadline = time.time() + max(1, int(timeoutSeconds))
    last = None
    while time.time() < deadline:
        res = get_current_package_activity()
        if isinstance(res, dict):
            activity = res.get('activity') or res.get('currentActivity') or res.get('activityName') or str(res)
        else:
            activity = str(res)
        last = activity
        if expectedActivity and expectedActivity in activity:
            return {"success": True, "activity": activity}
        time.sleep(0.5)
    return {"success": False, "activity": last, "error": f"Activity did not match '{expectedActivity}' in {timeoutSeconds}s"}

def scroll(direction: str, distance: float = 0.5):
    """Scrolls the screen in a direction (up, down, left, right)."""
    print(f"📜 Scroll: {direction}")
    try:
        payload = {"tool": "scroll", "args": {"direction": direction, "distance": distance}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error scrolling: {e}")
        return f"Error: {e}"


def swipe(startX: int, startY: int, endX: int, endY: int, duration: int = 800):
    """Swipes from one point to another on the screen."""
    print(f"--- 👆 ACT: Swiping from ({startX}, {startY}) to ({endX}, {endY})")
    try:
        payload = {"tool": "swipe", "args": {"startX": startX, "startY": startY, "endX": endX, "endY": endY, "duration": duration}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error swiping: {e}")
        return f"Error: {e}"


def long_press(strategy: str, value: str, duration: int = 1000):
    """Long presses on a UI element."""
    print(f"--- 👆 ACT: Long pressing element (strategy={strategy}, value={value}, duration={duration}ms)")
    try:
        payload = {"tool": "long_press", "args": {"strategy": strategy, "value": value, "duration": duration}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error long pressing: {e}")
        return f"Error: {e}"


def take_screenshot(filename: str = None):
    """Takes a screenshot of the current screen."""
    print("--- 📸 ACT: Taking screenshot...")
    try:
        args = {"filename": filename} if filename else {}
        payload = {"tool": "take_screenshot", "args": args}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error taking screenshot: {e}")
        return f"Error: {e}"


def get_element_text(strategy: str, value: str):
    """Gets the text content from a UI element."""
    print(f"--- 📖 ACT: Getting text from element (strategy={strategy}, value={value})")
    try:
        payload = {"tool": "get_element_text", "args": {"strategy": strategy, "value": value}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        result = response.json()
        return result.get('text', result)
    except requests.RequestException as e:
        print(f"Error getting element text: {e}")
        return f"Error: {e}"


def clear_element(strategy: str, value: str):
    """Clears the text content from an editable element."""
    print(f"--- 🧹 ACT: Clearing element (strategy={strategy}, value={value})")
    try:
        payload = {"tool": "clear_element", "args": {"strategy": strategy, "value": value}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error clearing element: {e}")
        return f"Error: {e}"


def press_home_button():
    """Presses the device's home button."""
    print("--- 🏠 ACT: Pressing home button")
    try:
        payload = {"tool": "press_home_button", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error pressing home button: {e}")
        return f"Error: {e}"


def press_back_button():
    """Presses the device's back button."""
    print("--- ⬅️  ACT: Pressing back button")
    try:
        payload = {"tool": "press_back_button", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error pressing back button: {e}")
        return f"Error: {e}"


def get_current_package_activity():
    """Gets the current app's package name and activity."""
    print("--- 📱 ACT: Getting current package and activity...")
    try:
        payload = {"tool": "get_current_package_activity", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error getting current package/activity: {e}")
        return f"Error: {e}"


def launch_app(packageName: str = None, activityName: str = None):
    """Launches an app. If packageName is provided, launches that specific app. activityName is optional."""
    print(f"--- 🚀 ACT: Launching app (packageName={packageName}, activityName={activityName})...")
    try:
        args = {}
        if packageName:
            args["packageName"] = packageName
            if activityName:
                args["activityName"] = activityName
        payload = {"tool": "launch_app", "args": args}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error launching app: {e}")
        return f"Error: {e}"


def close_app():
    """Closes the current app."""
    print("--- ❌ ACT: Closing app...")
    try:
        payload = {"tool": "close_app", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error closing app: {e}")
        return f"Error: {e}"


def reset_app():
    """Resets the app (terminates and relaunches)."""
    print("--- 🔄 ACT: Resetting app...")
    try:
        payload = {"tool": "reset_app", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error resetting app: {e}")
        return f"Error: {e}"


def scroll_to_element(strategy: str, value: str, maxScrolls: int = 10):
    """Scrolls to find an element on the screen."""
    print(f"--- 📜 ACT: Scrolling to element (strategy={strategy}, value={value})")
    try:
        payload = {"tool": "scroll_to_element", "args": {"strategy": strategy, "value": value, "maxScrolls": maxScrolls}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error scrolling to element: {e}")
        return f"Error: {e}"


def get_orientation():
    """Gets the device orientation (PORTRAIT or LANDSCAPE)."""
    print("--- 📱 ACT: Getting device orientation...")
    try:
        payload = {"tool": "get_orientation", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        result = response.json()
        return result.get('orientation', result)
    except requests.RequestException as e:
        print(f"Error getting orientation: {e}")
        return f"Error: {e}"


def set_orientation(orientation: str):
    """Sets the device orientation (PORTRAIT or LANDSCAPE)."""
    print(f"--- 🔄 ACT: Setting orientation to {orientation}...")
    try:
        payload = {"tool": "set_orientation", "args": {"orientation": orientation}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error setting orientation: {e}")
        return f"Error: {e}"


def hide_keyboard():
    """Hides the keyboard if visible."""
    print("--- ⌨️  ACT: Hiding keyboard...")
    try:
        payload = {"tool": "hide_keyboard", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error hiding keyboard: {e}")
        return f"Error: {e}"


def lock_device(duration: int = None):
    """Locks the device."""
    print("--- 🔒 ACT: Locking device...")
    try:
        args = {"duration": duration} if duration else {}
        payload = {"tool": "lock_device", "args": args}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error locking device: {e}")
        return f"Error: {e}"


def unlock_device():
    """Unlocks the device."""
    print("--- 🔓 ACT: Unlocking device...")
    try:
        payload = {"tool": "unlock_device", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error unlocking device: {e}")
        return f"Error: {e}"


def get_battery_info():
    """Gets device battery information."""
    print("--- 🔋 ACT: Getting battery info...")
    try:
        payload = {"tool": "get_battery_info", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        result = response.json()
        return result.get('batteryInfo', result)
    except requests.RequestException as e:
        print(f"Error getting battery info: {e}")
        return f"Error: {e}"


def get_contexts():
    """Gets available contexts (Native/WebView)."""
    print("--- 🌐 ACT: Getting contexts...")
    try:
        payload = {"tool": "get-contexts", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error getting contexts: {e}")
        return f"Error: {e}"


def switch_context(context: str):
    """Switches between contexts (Native/WebView)."""
    print(f"--- 🔀 ACT: Switching to context: {context}...")
    try:
        payload = {"tool": "switch-context", "args": {"context": context}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error switching context: {e}")
        return f"Error: {e}"


def open_notifications():
    """Opens the notifications panel."""
    print("--- 🔔 ACT: Opening notifications...")
    try:
        payload = {"tool": "open-notifications", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error opening notifications: {e}")
        return f"Error: {e}"


def is_app_installed(bundleId: str):
    """Checks if an app is installed."""
    print(f"--- 📦 ACT: Checking if app is installed: {bundleId}...")
    try:
        payload = {"tool": "is_app_installed", "args": {"bundleId": bundleId}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"❌ Error: {error_msg}")
            return f"Error: {error_msg}"
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error checking app installation: {e}")
        return f"Error: {e}"


# Export all functions and create the available_functions mapping
def call_generic_tool(tool_name: str, **kwargs):
    """
    Generic tool dispatcher that routes any tool call to the HTTP server.
    This allows the LLM to use all 110+ tools even if they're not explicitly
    defined in available_functions.
    """
    print(f"--- 🔧 Calling generic tool: {tool_name}")
    try:
        # Convert tool name from snake_case to kebab-case for HTTP server
        # HTTP server accepts both formats, but kebab-case is preferred
        tool_name_http = tool_name.replace('_', '-')
        
        payload = {
            "tool": tool_name_http,
            "args": kwargs
        }
        
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if result.get('success'):
            print(f"--- ✅ Tool {tool_name} executed successfully")
            return result
        else:
            error_msg = result.get('error', 'Unknown error')
            print(f"--- ❌ Tool {tool_name} failed: {error_msg}")
            return {"success": False, "error": error_msg}
    except requests.RequestException as e:
        error_msg = f"Error calling tool {tool_name}: {str(e)}"
        print(f"--- ❌ {error_msg}")
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"Unexpected error calling tool {tool_name}: {str(e)}"
        print(f"--- ❌ {error_msg}")
        return {"success": False, "error": error_msg}


available_functions = {
    "get_page_source": get_page_source,
    "get_page_configuration": get_page_configuration,
    "take_screenshot": take_screenshot,
    "get_current_package_activity": get_current_package_activity,
    "click": click,
    "send_keys": send_keys,
    "clear_element": clear_element,
    "get_element_text": get_element_text,
    "scroll": scroll,
    "scroll_to_element": scroll_to_element,
    "swipe": swipe,
    "long_press": long_press,
    "press_home_button": press_home_button,
    "press_back_button": press_back_button,
    "launch_app": launch_app,
    "close_app": close_app,
    "reset_app": reset_app,
    "get_orientation": get_orientation,
    "set_orientation": set_orientation,
    "hide_keyboard": hide_keyboard,
    "lock_device": lock_device,
    "unlock_device": unlock_device,
    "get_battery_info": get_battery_info,
    "get_contexts": get_contexts,
    "switch_context": switch_context,
    "open_notifications": open_notifications,
    "is_app_installed": is_app_installed,
    "wait_for_element": wait_for_element,
    "wait_for_text_ocr": wait_for_text_ocr,
    "ensure_focus_and_type": ensure_focus_and_type,
    "assert_activity": assert_activity,
    # Note: All other tools (110+ total) are routed via call_generic_tool
}


def get_perception_summary(sessionId: str = None, useOcr: bool = False):
    """Get perception summary combining XML and OCR data.
    
    Args:
        sessionId: Optional session ID
        useOcr: If True, forces OCR. If False, OCR is used automatically when XML is sparse (< 5 text elements).
    
    Note: OCR automatically triggers when XML has few elements (custom-rendered UIs).
    """
    print("--- 🧠 ACT: Getting perception summary (XML first, OCR auto-fallback if needed)...")
    try:
        payload = {"sessionId": sessionId, "useOcr": useOcr} if sessionId else {"useOcr": useOcr}
        response = requests.post(f"{MCP_SERVER_URL}/tools/get-perception-summary", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"--- ❌ RESULT: {{'success': False, 'error': '{error_msg}'}}")
            return {"success": False, "error": error_msg}
        response.raise_for_status()
        result = response.json()
        ocr_conf = result.get('ocr_confidence', 0)
        if ocr_conf > 0:
            print(f"--- ✅ RESULT: Perception summary generated (XML + OCR, confidence: {ocr_conf:.2f})")
        else:
            print(f"--- ✅ RESULT: Perception summary generated (XML only - sufficient)")
        return result
    except requests.RequestException as e:
        print(f"--- ❌ RESULT: {{'success': False, 'error': '{str(e)}'}}")
        return {"success": False, "error": str(e)}


def verify_action_with_diff(expectedKeywords: list, beforeScreenshot: str, afterScreenshot: str, sessionId: str = None):
    """Verify action using text diff analysis between before/after screenshots."""
    print(f"--- 🔍 ACT: Verifying action with text diff (keywords: {expectedKeywords})...")
    try:
        payload = {
            "expectedKeywords": expectedKeywords,
            "beforeScreenshot": beforeScreenshot,
            "afterScreenshot": afterScreenshot
        }
        if sessionId:
            payload["sessionId"] = sessionId
        response = requests.post(f"{MCP_SERVER_URL}/tools/verify-with-diff", json=payload)
        if response.status_code == 400:
            error_msg = response.json().get('error', 'Unknown error')
            print(f"--- ❌ RESULT: {{'success': False, 'error': '{error_msg}'}}")
            return {"success": False, "error": error_msg}
        response.raise_for_status()
        result = response.json()
        print(f"--- ✅ RESULT: Diff score: {result.get('diff_score', 0):.2f}, Keywords found: {len(result.get('keywords_found', []))}/{len(expectedKeywords)}")
        return result
    except requests.RequestException as e:
        print(f"--- ❌ RESULT: {{'success': False, 'error': '{str(e)}'}}")
        return {"success": False, "error": str(e)}


# Add new functions to available_functions dict
available_functions["get_perception_summary"] = get_perception_summary
available_functions["verify_action_with_diff"] = verify_action_with_diff
