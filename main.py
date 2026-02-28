"""
Advanced Roleplay Simulator (ARS) - Entry Point
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

# .env laden bevor irgendwelche Module ihre Umgebungsvariablen lesen
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; Variablen koennen auch direkt gesetzt sein

from core.engine import SimulatorEngine
from core.session_config import SessionConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path("logs") / "ars_session.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("ARS.main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ARS",
        description="Advanced Roleplay Simulator — TTRPG engine with AI integration",
    )
    parser.add_argument(
        "--module",
        required=True,
        metavar="RULESET",
        help="Name of the ruleset module to load (e.g. cthulhu_7e)",
    )
    parser.add_argument(
        "--adventure",
        default=None,
        metavar="ADVENTURE",
        help="Optional: adventure/plot file to load from modules/adventures/",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Enable voice I/O via STT/TTS handlers",
    )
    parser.add_argument(
        "--no-barge-in",
        action="store_true",
        help="Disable barge-in (mic monitor during TTS). Use with speakers to avoid echo false-positives.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    # Session configuration overrides
    parser.add_argument(
        "--preset",
        default=None,
        metavar="PRESET",
        help="Load a session preset from modules/presets/ (e.g. coc_classic)",
    )
    parser.add_argument(
        "--difficulty",
        default=None,
        choices=["easy", "normal", "heroic", "hardcore"],
        help="Override difficulty level (easy, normal, heroic, hardcore)",
    )
    parser.add_argument(
        "--atmosphere",
        default=None,
        metavar="TEXT",
        help="Override atmosphere description (e.g. '1920s Cosmic Horror, Noir')",
    )
    parser.add_argument(
        "--persona",
        default=None,
        metavar="TEXT",
        help="Override Keeper persona (e.g. 'Zynisch, mysterioes')",
    )
    parser.add_argument(
        "--language",
        default=None,
        metavar="LANG",
        help="Override language (e.g. de-DE, en-US)",
    )
    parser.add_argument(
        "--setting",
        default=None,
        metavar="SETTING",
        help="Setting module to load (e.g. cthulhu_1920, forgotten_realms)",
    )
    parser.add_argument(
        "--keeper",
        default=None,
        metavar="KEEPER",
        help="Keeper personality module (e.g. arkane_archivar, epischer_barde)",
    )
    parser.add_argument(
        "--extras",
        nargs="*",
        default=None,
        metavar="EXTRA",
        help="Optional extras to load (e.g. noir_atmosphere survival_mode)",
    )
    parser.add_argument(
        "--character",
        default=None,
        metavar="CHARACTER",
        help="Character template to load (e.g. coc_investigator, add_fighter)",
    )
    parser.add_argument(
        "--party",
        default=None,
        metavar="PARTY",
        help="Party module to load (placeholder for future multi-character support)",
    )
    parser.add_argument(
        "--temperature",
        default=None,
        type=float,
        metavar="FLOAT",
        help="Override KI temperature (0.0 - 2.0)",
    )
    parser.add_argument(
        "--techgui",
        action="store_true",
        help="Launch the developer TechGUI instead of the CLI game loop",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Build session configuration: preset as base, CLI args as overrides
    base_config = None
    if args.preset:
        base_config = SessionConfig.from_preset(args.preset)
    session_config = SessionConfig.from_args(args, base=base_config)

    logger.info(
        "Starting ARS — module: %s | difficulty: %s | language: %s",
        args.module, session_config.difficulty, session_config.language,
    )

    engine = SimulatorEngine(module_name=args.module, session_config=session_config)

    if args.techgui:
        # TechGUI-Modus: GUI uebernimmt Lifecycle (init, start, stop)
        from gui.tech_gui import TechGUI
        gui = TechGUI(engine)
        gui._voice_enabled = args.voice
        gui._barge_in = not getattr(args, "no_barge_in", False)
        gui.run()
    else:
        # CLI-Modus: klassischer Game-Loop
        engine.initialize()

        if args.adventure:
            engine.load_adventure(args.adventure)

        if args.voice:
            barge_in = not getattr(args, "no_barge_in", False)
            engine.enable_voice(barge_in=barge_in)

        engine.run()


if __name__ == "__main__":
    main()
