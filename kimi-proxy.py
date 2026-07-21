#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Launcher for kimi_proxy V9.

Usage:
  python kimi-proxy.py            — start with kimi-proxy.json config
  python kimi-proxy.py --config my.json
"""

import sys
import os

# Add script directory to sys.path to find the kimi_proxy package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kimi_proxy.__main__ import main

if __name__ == "__main__":
    main()
