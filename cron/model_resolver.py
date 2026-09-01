import logging
from typing import Any

from hermes_cli.config import load_config

logger = logging.getLogger(__name__)


def _extract_model_name(model_cfg: Any) -> str:
    """Return the configured primary model name from a model config value."""
    if isinstance(model_cfg, str):
        return model_cfg
    if isinstance(model_cfg, dict):
        return (
            model_cfg.get("default")
            or model_cfg.get("model")
            or model_cfg.get("name")
            or ""
        )
    return ""


def get_current_model_from_config() -> str:
    """Get the current model identifier from the user's active configuration."""
    try:
        config = load_config()
        model = _extract_model_name(config.get("model"))
        return model or "anthropic/claude-opus-4.6"
    except Exception as e:
        logger.error("Failed to load active model from config: %s", e)
        return "anthropic/claude-opus-4.6"
