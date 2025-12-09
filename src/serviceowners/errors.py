from __future__ import annotations


class ServiceOwnersError(Exception):
    """Base exception for serviceowners."""


class ConfigError(ServiceOwnersError):
    """Configuration is missing or invalid."""


class ParseError(ServiceOwnersError):
    """Failed to parse a config file."""


class GitError(ServiceOwnersError):
    """Git invocation failed."""


class GitHubError(ServiceOwnersError):
    """GitHub API call failed."""


class UsageError(ServiceOwnersError):
    """Invalid CLI usage (user error)."""
