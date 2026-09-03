"""Compatibility import for the Telegram platform adapter.

The maintained implementation lives in the plugin tree. Afsol integrations
written against the pre-plugin ``gateway.platforms.telegram`` import keep
working through this deliberately thin shim.
"""

from plugins.platforms.telegram.adapter import TelegramAdapter

__all__ = ["TelegramAdapter"]
