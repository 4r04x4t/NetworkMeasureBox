"""Unit tests for UI Theme selection and persistence."""
import configparser
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from nmb.config import Config, load_config, save_config
from nmb.web.templates import get_dashboard_html, get_logout_html


class TestThemePersistence(unittest.TestCase):
    def test_config_theme_default_and_serialization(self):
        cfg = Config()
        self.assertEqual(cfg.web.theme, "default")

        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".conf") as f:
            conf_path = f.name

        try:
            cfg.web.theme = "prtd"
            save_config(cfg, Path(conf_path))

            loaded_cfg = load_config(Path(conf_path))
            self.assertEqual(loaded_cfg.web.theme, "prtd")
        finally:
            Path(conf_path).unlink(missing_ok=True)

    def test_get_dashboard_html_injects_initial_theme(self):
        html_default = get_dashboard_html()
        self.assertIn('data-theme="default"', html_default)
        self.assertIn('var serverTheme = "default"', html_default)

        html_prtd = get_dashboard_html(initial_theme="prtd")
        self.assertIn('data-theme="prtd"', html_prtd)
        self.assertIn('var serverTheme = "prtd"', html_prtd)

        # Check theme-card elements and active badge
        self.assertIn('data-theme-name="prtd"', html_prtd)
        self.assertIn('theme-card-badge', html_prtd)
        self.assertIn('updateThemeCardsHighlight', html_prtd)

    def test_get_logout_html_preserves_theme(self):
        logout_amoled = get_logout_html(initial_theme="amoled")
        self.assertIn('data-theme="amoled"', logout_amoled)
        self.assertIn('var serverTheme = "amoled"', logout_amoled)
        # Verify logout doesn't erase nmb_theme from localStorage
        self.assertIn("localStorage.setItem('nmb_theme'", logout_amoled)


if __name__ == "__main__":
    unittest.main()
