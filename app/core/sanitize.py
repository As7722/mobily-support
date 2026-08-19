"""
Security utilities for input validation and sanitization.
"""
from __future__ import annotations

import re
from html import escape as html_escape
from typing import Optional


# ─── SQL ILIKE Escaping ────────────────────────────────────────────────────
# PostgreSQL ILIKE special characters: % (any chars) and _ (single char)

def escape_ilike_pattern(value: str, max_length: int = 100) -> str:
    """
    Escape special characters in ILIKE patterns and enforce max length.
    
    Args:
        value: User input string
        max_length: Maximum allowed length
        
    Returns:
        Escaped and truncated string safe for ILIKE
        
    Raises:
        ValueError: If input exceeds max_length
    """
    if not value:
        return ""
    
    if len(value) > max_length:
        raise ValueError(f"Input exceeds maximum length of {max_length} characters")
    
    # Escape PostgreSQL ILIKE special characters
    # Backslash must be escaped first
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace("%", "\\%")
    escaped = escaped.replace("_", "\\_")
    
    return escaped


# ─── HTML Escaping for Email Templates ────────────────────────────────────

def escape_html_for_email(text: Optional[str]) -> str:
    """
    Escape HTML in email content to prevent injection attacks.
    
    Args:
        text: Text to escape
        
    Returns:
        HTML-escaped string safe for email templates
    """
    if not text:
        return ""
    
    # Use standard html.escape()
    return html_escape(str(text), quote=True)


# ─── Path Traversal Prevention ────────────────────────────────────────────

def validate_file_path_suffix(path_suffix: str, max_length: int = 500) -> str:
    """
    Validate file path suffix to prevent path traversal attacks.
    
    Args:
        path_suffix: File path suffix (relative path)
        max_length: Maximum allowed length
        
    Returns:
        Validated path suffix
        
    Raises:
        ValueError: If path contains traversal attempts or is invalid
    """
    if not path_suffix:
        raise ValueError("Path suffix cannot be empty")
    
    if len(path_suffix) > max_length:
        raise ValueError(f"Path exceeds maximum length of {max_length}")
    
    # Reject paths starting with /
    if path_suffix.startswith("/"):
        raise ValueError("Path must be relative (cannot start with /)")
    
    # Reject parent directory traversal
    if ".." in path_suffix:
        raise ValueError("Path traversal (..) is not allowed")
    
    # Reject null bytes
    if "\x00" in path_suffix:
        raise ValueError("Path contains null bytes")
    
    # Reject absolute paths or Windows drive letters
    if re.match(r"^[a-zA-Z]:", path_suffix):
        raise ValueError("Absolute Windows paths are not allowed")
    
    return path_suffix


# ─── Input Length Validation ──────────────────────────────────────────────

def validate_string_length(
    value: Optional[str],
    min_length: int = 0,
    max_length: int = 255,
    field_name: str = "field",
) -> str:
    """
    Validate string length constraints.
    
    Args:
        value: String to validate
        min_length: Minimum required length
        max_length: Maximum allowed length
        field_name: Field name for error messages
        
    Returns:
        Validated string
        
    Raises:
        ValueError: If validation fails
    """
    if value is None:
        if min_length > 0:
            raise ValueError(f"{field_name} is required")
        return ""
    
    value_str = str(value).strip()
    
    if len(value_str) < min_length:
        raise ValueError(f"{field_name} must be at least {min_length} characters")
    
    if len(value_str) > max_length:
        raise ValueError(f"{field_name} must not exceed {max_length} characters")
    
    return value_str


# ─── UUID Validation ──────────────────────────────────────────────────────

def validate_uuid(value: Optional[str], field_name: str = "id") -> str:
    """
    Validate UUID string format.
    
    Args:
        value: UUID string to validate
        field_name: Field name for error messages
        
    Returns:
        Validated UUID string
        
    Raises:
        ValueError: If not a valid UUID
    """
    if not value:
        raise ValueError(f"{field_name} is required")
    
    # Simple UUID v4 validation (8-4-4-4-12 hex digits)
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    if not re.match(uuid_pattern, str(value).lower()):
        raise ValueError(f"Invalid {field_name} format")
    
    return str(value)


# ─── Email Validation ─────────────────────────────────────────────────────

def validate_email(email: Optional[str], max_length: int = 255) -> str:
    """
    Basic email validation.
    
    Args:
        email: Email address to validate
        max_length: Maximum allowed length
        
    Returns:
        Validated email address
        
    Raises:
        ValueError: If email is invalid
    """
    if not email:
        raise ValueError("Email is required")
    
    email_str = str(email).strip().lower()
    
    if len(email_str) > max_length:
        raise ValueError(f"Email must not exceed {max_length} characters")
    
    # Basic email regex (RFC 5322 simplified)
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_pattern, email_str):
        raise ValueError("Invalid email format")
    
    return email_str


__all__ = [
    "escape_ilike_pattern",
    "escape_html_for_email",
    "validate_file_path_suffix",
    "validate_string_length",
    "validate_uuid",
    "validate_email",
]
