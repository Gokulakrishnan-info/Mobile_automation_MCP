from __future__ import annotations

from typing import Dict, Any, Iterable, List, Optional, Tuple
import re
import time


class SmartActionExecutor:
    """
    Unified fallback engine that executes high-level tool requests deterministically.

    The LLM issues an action intent once (e.g., click, send_keys). This executor
    takes the intent, generates locator variations, scrolls as needed, retries the
    action using multiple strategies, validates context, and only returns once
    the action has definitively succeeded or failed.
    """

    SUPPORTED_ACTIONS = {"click", "send_keys", "ensure_focus_and_type"}

    def __init__(self,
                 available_functions: Dict[str, Any],
                 expected_inputs: Optional[Dict[str, str]] = None):
        self.available_functions = available_functions
        self.expected_inputs = expected_inputs or {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def can_handle(self, action: str) -> bool:
        return action in self.SUPPORTED_ACTIONS

    def execute(self,
                action: str,
                args: Dict[str, Any],
                *,
                enforce_expected_inputs: bool = True) -> Optional[Dict[str, Any]]:
        """
        Execute a supported action with fallback layers.

        Returns a result dict (success/error) or None if the executor chose not
        to handle the action (in which case legacy retry logic will run).
        """
        if action not in self.SUPPORTED_ACTIONS:
            return None

        if action == "click":
            return self._execute_click(args)
        if action in ("send_keys", "ensure_focus_and_type"):
            return self._execute_text_input(action, args, enforce_expected_inputs=enforce_expected_inputs)

        return None

    # ------------------------------------------------------------------ #
    # Click handling
    # ------------------------------------------------------------------ #
    def _execute_click(self, args: Dict[str, Any]) -> Dict[str, Any]:
        strategy = args.get("strategy")
        value = args.get("value")

        locator_candidates = list(self._build_locator_candidates(strategy, value))
        if not locator_candidates:
            locator_candidates.append((strategy, value))

        # Log fallback candidates for debugging (only if multiple candidates)
        if len(locator_candidates) > 1:
            print(f"--- [SMART] Generated {len(locator_candidates)} locator candidates for click")

        errors: List[str] = []
        for idx, (loc_strategy, loc_value) in enumerate(locator_candidates):
            # Skip wait/scroll on first attempt (fast path for common case)
            # Only prepare screen (wait/scroll) on subsequent attempts
            if idx > 0:
                self._prepare_screen_for_locator(loc_strategy, loc_value, attempt=idx)
                if len(locator_candidates) > 1:
                    print(f"--- [SMART] Fallback attempt {idx + 1}/{len(locator_candidates)}: {loc_strategy}={loc_value[:50]}...")

            result = self.available_functions["click"](strategy=loc_strategy, value=loc_value)
            if isinstance(result, dict) and result.get("success"):
                if idx > 0 and len(locator_candidates) > 1:
                    print(f"--- [SMART] ✅ Success on fallback attempt {idx + 1} with {loc_strategy}={loc_value[:50]}...")
                return result

            error_msg = self._normalize_error(result)
            errors.append(error_msg)

        return {"success": False, "error": errors[-1] if errors else "Unable to click element"}

    # ------------------------------------------------------------------ #
    # Text input handling
    # ------------------------------------------------------------------ #
    def _execute_text_input(self,
                            primary_action: str,
                            args: Dict[str, Any],
                            *,
                            enforce_expected_inputs: bool) -> Dict[str, Any]:
        strategy = args.get("strategy")
        value = args.get("value")
        text = args.get("text", "")

        if enforce_expected_inputs:
            self._enforce_expected_input(strategy, value, text)

        locator_candidates = list(self._build_locator_candidates(strategy, value))
        if not locator_candidates:
            locator_candidates.append((strategy, value))

        # Log fallback candidates for debugging (only if multiple candidates)
        if len(locator_candidates) > 1:
            print(f"--- [SMART] Generated {len(locator_candidates)} locator candidates for text input")

        # Check if this is a container pattern (for timeout optimization)
        container_keywords = ("chip_group", "chipgroup", "container", "wrapper", "layout", "viewgroup")
        is_container = any(keyword in value.lower() for keyword in container_keywords)
        
        for idx, (loc_strategy, loc_value) in enumerate(locator_candidates):
            # Skip wait/scroll on first attempt (fast path for common case)
            # Only prepare screen (wait/scroll) on subsequent attempts
            if idx > 0:
                self._prepare_screen_for_locator(loc_strategy, loc_value, attempt=idx)
                if len(locator_candidates) > 1:
                    print(f"--- [SMART] Fallback attempt {idx + 1}/{len(locator_candidates)}: {loc_strategy}={loc_value[:50]}...")

            focus_result = self.available_functions["click"](strategy=loc_strategy, value=loc_value)
            if isinstance(focus_result, dict) and not focus_result.get("success"):
                continue

            # OPTIMIZATION: Use shorter timeout for container patterns (they often fail quickly)
            # Use full timeout for actual EditText elements (they might need time to appear)
            timeout_ms = 3000 if (is_container and idx < 2) else 10000
            
            result = self.available_functions["ensure_focus_and_type"](
                strategy=loc_strategy,
                value=loc_value,
                text=text,
                timeoutMs=timeout_ms,
                hideKeyboard=False,
            )
            if isinstance(result, dict) and result.get("success"):
                if idx > 0 and len(locator_candidates) > 1:
                    print(f"--- [SMART] ✅ Success on fallback attempt {idx + 1} with {loc_strategy}={loc_value[:50]}...")
                return result

            # Retry with send_keys as fallback
            result = self.available_functions["send_keys"](strategy=loc_strategy, value=loc_value, text=text)
            if isinstance(result, dict) and result.get("success"):
                if idx > 0 and len(locator_candidates) > 1:
                    print(f"--- [SMART] ✅ Success on fallback attempt {idx + 1} with send_keys")
                return result

        return {"success": False, "error": f"Failed to input text into '{value}'"}

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _prepare_screen_for_locator(self, strategy: str, value: str, *, attempt: int) -> None:
        """
        Layer-3/4 style fallback: wait, scroll, and retry context validation.
        """
        wait_fn = self.available_functions.get("wait_for_element")
        if wait_fn:
            try:
                wait_fn(strategy=strategy, value=value, timeoutMs=3000)
            except Exception:
                pass

        scroll_fn = self.available_functions.get("scroll_to_element")
        if scroll_fn and attempt > 0:
            direction = "down" if attempt % 2 == 1 else "up"
            try:
                scroll_fn(strategy=strategy, value=value, direction=direction)
            except Exception:
                pass

    def _build_locator_candidates(self, strategy: str, value: str) -> Iterable[Tuple[str, str]]:
        """
        Layer-1 fallback: build alternate selectors from the original locator.
        
        Generates multiple locator variations to increase success rate:
        - Original locator (tried first)
        - Stripped/partial versions
        - XPath equivalents (exact and contains)
        """
        if not strategy or not value:
            return []

        normalized_value = value.strip()
        normalized_value_lower = normalized_value.lower()
        candidates = [(strategy, normalized_value)]

        # PRIORITY FIX: Check for container patterns FIRST and prioritize descendant EditText
        container_keywords = ("chip_group", "chipgroup", "container", "wrapper", "layout", "viewgroup")
        is_container = any(keyword in normalized_value_lower for keyword in container_keywords)
        
        # If container detected, immediately add descendant EditText as high-priority candidate
        if is_container:
            if strategy == "id":
                # Insert descendant EditText as candidate #2 (right after original)
                candidates.insert(1, ("xpath", f"//*[@resource-id='{normalized_value}']//android.widget.EditText"))
            elif strategy == "xpath":
                # Already xpath - try appending descendant search
                candidates.insert(1, ("xpath", f"{normalized_value}//android.widget.EditText"))
        
        # OPTIMIZATION: For containers, limit to only 2-3 most likely candidates
        # Pre-validation in main.py should have already resolved container to EditText
        # So these fallbacks are just a safety net for edge cases
        if is_container:
            # Keep only: original, descendant EditText, and one generic EditText search
            limited_candidates = [
                candidates[0],  # Original
                candidates[1] if len(candidates) > 1 else None,  # Descendant EditText (if added)
            ]
            # Add one generic EditText search as final fallback
            limited_candidates.append(("xpath", "//android.widget.EditText[contains(@resource-id, 'input') or contains(@resource-id, 'text')]"))
            # Filter out None values
            candidates = [c for c in limited_candidates if c is not None]
            # Deduplicate
            seen = set()
            unique_candidates = []
            for cand in candidates:
                if cand not in seen:
                    seen.add(cand)
                    unique_candidates.append(cand)
            return unique_candidates

        # For ID strategy: generate multiple variations
        if strategy == "id":
            # Extract just the ID part after the last slash (e.g., "button" from "com.app:id/button")
            if "/" in normalized_value:
                id_part = normalized_value.split("/")[-1]
                # Try with just the ID part (some apps use partial resource-ids)
                candidates.append((strategy, id_part))
            
            # Strip package prefix (e.g., com.app:id/foo -> id/foo)
            # This might work for some Appium implementations
            if ":" in normalized_value:
                stripped = normalized_value.split(":", 1)[1]
                if stripped != normalized_value:  # Only add if different
                    candidates.append((strategy, stripped))
            
            # XPath exact match
            candidates.append(("xpath", f"//*[@resource-id='{normalized_value}']"))
            
            # XPath contains (partial match) - useful for dynamic IDs
            if "/" in normalized_value:
                id_part = normalized_value.split("/")[-1]
                candidates.append(("xpath", f"//*[contains(@resource-id, '{id_part}')]"))
            else:
                candidates.append(("xpath", f"//*[contains(@resource-id, '{normalized_value}')]"))

        # For text strategy: generate XPath variations
        elif strategy == "text":
            # XPath exact match
            candidates.append(("xpath", f"//*[@text='{normalized_value}']"))
            # XPath contains (partial match)
            candidates.append(("xpath", f"//*[contains(@text, '{normalized_value}')]"))
            # Try as accessibility_id (some elements have text in content-desc)
            candidates.append(("accessibility_id", normalized_value))

        # For accessibility_id strategy: generate XPath variations
        elif strategy == "accessibility_id":
            # XPath exact match
            candidates.append(("xpath", f"//*[@content-desc='{normalized_value}']"))
            # XPath contains (partial match)
            candidates.append(("xpath", f"//*[contains(@content-desc, '{normalized_value}')]"))
            # Try as text (some elements have content-desc in text)
            candidates.append(("text", normalized_value))

        # For xpath strategy: try to extract and use simpler selectors
        elif strategy == "xpath":
            # Extract attribute and value from XPath if possible
            # Try to extract @attribute='value' or contains(@attribute, 'value')
            exact_match = re.search(r"@(\w+)\s*=\s*['\"]([^'\"]+)['\"]", normalized_value)
            contains_match = re.search(r"contains\(@(\w+),\s*['\"]([^'\"]+)['\"]\)", normalized_value)
            
            if exact_match:
                attr_name, attr_value = exact_match.groups()
                if attr_name == "resource-id":
                    candidates.append(("id", attr_value))
                elif attr_name == "text":
                    candidates.append(("text", attr_value))
                elif attr_name in ("content-desc", "content_desc"):
                    candidates.append(("accessibility_id", attr_value))
            
            if contains_match:
                attr_name, attr_value = contains_match.groups()
                if attr_name == "resource-id":
                    # Try with ID strategy using partial value
                    candidates.append(("id", attr_value))
                elif attr_name == "text":
                    candidates.append(("text", attr_value))
                elif attr_name in ("content-desc", "content_desc"):
                    candidates.append(("accessibility_id", attr_value))

        # Gmail-specific fallbacks (To field, recipients, etc.)
        # PRIORITY FIX: If Gmail container detected, prioritize descendant EditText
        if "peoplekit_autocomplete_chip_group" in normalized_value_lower:
            # The descendant EditText XPath should be tried early (already added above if container detected)
            # Add other Gmail-specific candidates as fallbacks
            gmail_recipient_candidates = [
                ("xpath", "//android.widget.EditText[contains(@resource-id, 'peoplekit')]"),
                ("xpath", "//android.widget.MultiAutoCompleteTextView[contains(@resource-id, 'peoplekit')]"),
                ("xpath", "//android.widget.AutoCompleteTextView[contains(@resource-id, 'peoplekit')]"),
                ("id", "com.google.android.gm:id/peoplekit_autocomplete_input"),
                ("id", "com.google.android.gm:id/peoplekit_compose_text_field"),
                ("id", "com.google.android.gm:id/peoplekit_autocomplete_textview"),
            ]
            candidates.extend(gmail_recipient_candidates)
        
        # Additional container-aware fallbacks (for containers not already handled above)
        if is_container and not ("peoplekit_autocomplete_chip_group" in normalized_value_lower):
            # Generic descendant search for any container reference
            candidates.append(("xpath", "//android.widget.EditText[contains(@resource-id, 'input')]"))
        
        # Generic container fallbacks (for any app with container patterns)
        container_keywords = ("chip_group", "chipgroup", "container", "wrapper", "layout", "viewgroup", "recycler")
        if any(keyword in normalized_value_lower for keyword in container_keywords):
            # Try to find EditText with similar resource-id pattern
            base_id = normalized_value
            for keyword in container_keywords:
                base_id = base_id.replace(f"_{keyword}", "").replace(keyword, "")
            
            # Extract package if present
            if ":" in base_id:
                package_part = base_id.split(":")[0]
                id_part = base_id.split(":")[-1].split("/")[-1] if "/" in base_id else base_id.split(":")[-1]
            else:
                package_part = ""
                id_part = base_id.split("/")[-1] if "/" in base_id else base_id
            
            # Generate input field candidates
            input_candidates = [
                f"{id_part}_input",
                f"{id_part}_text_input",
                f"{id_part}_edit_text",
                f"{id_part}_field",
                f"{id_part}_autocomplete_input",
                f"{id_part}_input_field",
                f"{id_part}_textfield",
            ]
            
            # Add package prefix if present
            if package_part and ":" in normalized_value:
                input_candidates = [f"{package_part}:id/{cand}" for cand in input_candidates]
            
            for cand in input_candidates:
                if strategy == "id":
                    candidates.append((strategy, cand))
                candidates.append(("xpath", f"//android.widget.EditText[contains(@resource-id, '{cand.split('/')[-1]}')]"))
                candidates.append(("xpath", f"//android.widget.MultiAutoCompleteTextView[contains(@resource-id, '{cand.split('/')[-1]}')]"))

        # Deduplicate while preserving order
        seen = set()
        unique_candidates = []
        for cand in candidates:
            if cand not in seen:
                seen.add(cand)
                unique_candidates.append(cand)
        
        # OPTIMIZATION: Limit total candidates to 5-6 for better UX (single-step success)
        # Pre-validation should have already fixed most container issues, so we only need
        # a few fallbacks as safety net. This prevents 20+ attempts and improves speed.
        if len(unique_candidates) > 6:
            # Keep first 6 candidates (original + most likely fallbacks)
            # Priority order: original, exact matches, contains matches, then generic
            priority_candidates = unique_candidates[:6]
            print(f"--- [SMART] Limited candidates from {len(unique_candidates)} to 6 for faster execution")
            return priority_candidates
        
        return unique_candidates

    def _normalize_error(self, result: Any) -> str:
        if isinstance(result, dict):
            return result.get("error", "Unknown error")
        if isinstance(result, str):
            return result
        return str(result)

    def _enforce_expected_input(self, strategy: str, value: str, text: str) -> None:
        """
        Preserve strict user inputs (e.g., username/password must match prompt).
        """
        if not text:
            return

        target = (value or "").lower()
        expected = None
        if any(keyword in target for keyword in ("user", "login", "email")):
            expected = self.expected_inputs.get("username")
        if any(keyword in target for keyword in ("pass", "pwd", "password")):
            expected = self.expected_inputs.get("password")

        if expected is not None and text.strip() != expected.strip():
            raise ValueError(f"Strict input enforcement: expected '{expected}' but got '{text}'. Use exact value from user prompt.")

