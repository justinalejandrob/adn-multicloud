#!/usr/bin/env python3
"""
main.py - Punto de entrada único de la imagen.

  APP_MODE=batch  (por defecto) -> procesa el ADN y termina (VMs / IaaS)
  APP_MODE=server               -> servidor HTTP que procesa bajo demanda (PaaS)

Así la MISMA imagen sirve para IaaS (Azure, Huawei, Claro) y PaaS (GuaraCloud).
"""

import os
import sys

if __name__ == "__main__":
    if os.getenv("APP_MODE", "batch").lower() == "server" or sys.argv[1:2] == ["serve"]:
        import server
        sys.exit(server.main())
    import dna_processor
    sys.exit(dna_processor.main(sys.argv[1:]))
