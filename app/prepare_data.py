#!/usr/bin/env python3
"""
prepare_data.py - Deja listo el archivo de ADN antes de procesarlo.

  - Si DNA_URL está definida -> descarga el ADN real (fetch_dna.py)
  - Si no                    -> genera ADN sintético determinista (generate_dna.py)
"""

import os
import sys

if __name__ == "__main__":
    if os.getenv("DNA_URL"):
        import fetch_dna
        sys.exit(fetch_dna.main(sys.argv[1:]))
    import generate_dna
    sys.exit(generate_dna.main(sys.argv[1:]))
