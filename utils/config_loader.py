import os
import yaml

def load_config(config_path=None):
    """
    Load a YAML config file, automatically extract `api_keys` and `settings`,
    and flatten `settings` to the top level for easy access.

    Parameters:
        config_path (str, optional): Path to the config file. Defaults to
                                     quant-company-insights-agent/config.yaml.

    Returns:
        dict: Dictionary containing flattened `settings`, `api_keys`, and other top-level entries.
    """
    if config_path is None:
        # Default path relative to this file: utils/ → project root → quant-company-insights-agent/config.yaml
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "..", "quant-company-insights-agent", "config.yaml")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Start with api_keys
    result = {
        "api_keys": config.get("api_keys", {})
    }

    # Flatten settings to the top level
    settings = config.get("settings", {})
    result.update(settings)

    # Include any other top-level entries that are not api_keys or settings
    for key, value in config.items():
        if key not in result and key != "settings":
            result[key] = value

    return result
