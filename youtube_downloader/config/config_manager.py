from typing import Any, Dict, Optional, Union
import os
import json
from pathlib import Path
from .default_config import DEFAULT_CONFIG, MODERN_YT_DLP_OPTS

class ConfigManager:
    """The ACJ's Enterprise-grade configuration manager with validation and environment support"""

    def __init__(self, config_file: Optional[str] = None) -> None:
        self.config: Dict[str, Any] = DEFAULT_CONFIG.copy()
        self.modern_ydl_opts: Dict[str, Any] = MODERN_YT_DLP_OPTS.copy()
        self.config_file: str = config_file or os.getenv('YTD_CONFIG_FILE', 'download_config.json')
        self._load_from_env()
        self.load_config()
        self._validate_config()

    def _load_from_env(self) -> None:
        """Load configuration from environment variables"""
        env_mappings = {
            'YTD_OUTPUT_PATH': 'output_path',
            'YTD_MAX_WORKERS': 'max_workers',
            'YTD_AUDIO_ONLY': 'audio_only',
            'YTD_MAX_RETRIES': 'max_retries',
            'YTD_TIMEOUT': 'download_timeout',
            'YTD_COOKIES_FILE': 'cookies_file',
            'YTD_RATE_LIMIT': 'throttled_rate',
            'YTD_SPONSORBLOCK': 'enable_sponsorblock',
        }

        for env_var, config_key in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                # Type conversion
                if config_key in ['max_workers', 'max_retries', 'download_timeout', 'throttled_rate']:
                    try:
                        self.config[config_key] = int(value)
                    except ValueError:
                        pass
                elif config_key in ['audio_only', 'enable_sponsorblock']:
                    self.config[config_key] = value.lower() in ('true', '1', 'yes', 'on')
                else:
                    self.config[config_key] = value

    def _validate_config(self) -> None:
        """Validate configuration values"""
        if self.config.get('max_workers', 0) <= 0:
            self.config['max_workers'] = 1
        if self.config.get('max_retries', 0) < 0:
            self.config['max_retries'] = 0
        if self.config.get('download_timeout', 0) <= 0:
            self.config['download_timeout'] = 3600

        # Ensure output path exists
        output_path = Path(self.config.get('output_path', './downloads'))
        output_path.mkdir(parents=True, exist_ok=True)
        self.config['output_path'] = str(output_path)

    def load_config(self) -> None:
        """Load configuration from file if exists"""
        config_path = Path(self.config_file)
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
            except (json.JSONDecodeError, IOError, UnicodeDecodeError) as e:
                print(f"Warning: Could not load config file {self.config_file}: {e}")

    def save_config(self) -> None:
        """Save current configuration to file"""
        try:
            config_path = Path(self.config_file)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"Warning: Could not save config file {self.config_file}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value"""
        self.config[key] = value
        self._validate_config()

    def get_modern_ydl_opts(self) -> Dict[str, Any]:
        """Get modern yt-dlp options"""
        return self.modern_ydl_opts.copy()

    def update_ydl_opts(self, updates: Dict[str, Any]) -> None:
        """Update yt-dlp options"""
        self.modern_ydl_opts.update(updates)

    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration as dict"""
        return self.config.copy()

    def reset_to_defaults(self) -> None:
        """Reset configuration to defaults"""
        self.config = DEFAULT_CONFIG.copy()
        self.modern_ydl_opts = MODERN_YT_DLP_OPTS.copy()
        self._load_from_env()
        self._validate_config()