"""
scripts/reset_session.py

Emergency Redis session reset for a specific user.
Use when a customer is stuck in HUMAN_ACTIVE
and cannot be reached via the /reset endpoint.

Usage:
    python scripts/reset_session.py <psid>
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.session_service import reset_session, get_session_state
from utils.logger import get_logger

logger = get_logger("reset_session")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/reset_session.py <psid>")
        sys.exit(1)

    psid = sys.argv[1].strip()
    logger.info(f"Resetting session for PSID: {psid}")

    state_before = get_session_state(psid)
    logger.info(f"State before reset: {state_before.value}")

    reset_session(psid)

    state_after = get_session_state(psid)
    logger.info(f"State after reset:  {state_after.value}")
    print(f"\n✓ Session reset complete for {psid}\n")


if __name__ == "__main__":
    main()
