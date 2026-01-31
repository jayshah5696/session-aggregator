"""Data scrubbing and redaction utility."""

import re
from typing import Pattern


class DataScrubber:
    """Redacts sensitive information from text."""

    def __init__(self, patterns: list[tuple[str, str]] | None = None):
        """Initialize with custom patterns.

        Args:
            patterns: List of (name, regex_pattern) tuples.
        """
        self.patterns: list[tuple[str, Pattern]] = []

        # Default patterns
        default_patterns = [
            # API Keys (Generic High Entropy)
            (
                "API_KEY",
                r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key)[\s=:]+([a-zA-Z0-9_\-]{20,})",
            ),
            # OpenAI
            ("OPENAI_KEY", r"sk-[a-zA-Z0-9]{20,}"),
            # GitHub
            ("GITHUB_TOKEN", r"(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}"),
            # AWS
            ("AWS_ACCESS_KEY", r"AKIA[0-9A-Z]{16}"),
            ("AWS_SECRET_KEY", r"(?i)aws_secret_access_key[\s=:]+([a-zA-Z0-9/+=]{40})"),
            # Private IP
            (
                "PRIVATE_IP",
                r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b",
            ),
            # Email
            ("EMAIL", r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        ]

        if patterns:
            for name, pattern in patterns:
                self.patterns.append((name, re.compile(pattern)))

        for name, pattern in default_patterns:
            self.patterns.append((name, re.compile(pattern)))

    def scrub(self, text: str) -> str:
        """Redact sensitive information from text.

        Args:
            text: Input text.

        Returns:
            Scrubbed text.
        """
        if not text:
            return text

        scrubbed = text
        for name, regex in self.patterns:
            # Replace matches with [REDACTED:NAME]
            # Use a callback to preserve non-captured groups if needed,
            # but for simple scrubbing, we just replace the whole match or specific groups.

            # Simple approach: if groups exist, replace the last group (value), else whole match
            def replace_func(match):
                if match.groups():
                    # If regex has groups, we assume the last group is the secret value
                    # We reconstruct the string replacing the secret group
                    full_match = match.group(0)
                    secret = match.group(len(match.groups()))
                    return full_match.replace(secret, f"[REDACTED:{name}]")
                else:
                    return f"[REDACTED:{name}]"

            scrubbed = regex.sub(replace_func, scrubbed)

        return scrubbed

    def scrub_object(self, obj: any) -> any:
        """Recursively scrub strings in JSON-like objects (dicts, lists)."""
        if isinstance(obj, str):
            return self.scrub(obj)
        elif isinstance(obj, dict):
            return {k: self.scrub_object(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.scrub_object(i) for i in obj]
        return obj
