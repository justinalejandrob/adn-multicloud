#!/usr/bin/env python3
"""
main.py - Punto de entrada único de la imagen.

  APP_MODE=batch  (por defecto) -> procesa el ADN y termina (VMs / IaaS)
  APP_MODE=server               -> servidor HTTP que procesa bajo demanda (PaaS)
                                   + dashboard + maestro del clúster
  APP_MODE=nodo                 -> nodo del clúster con etcd: worker (8000) +
                                   coordinador (elección de líder) + dashboard (8080)
  APP_MODE=etcd                 -> miembro de etcd (memoria compartida del clúster)
  APP_MODE=worker               -> solo worker (modo anterior, maestro en la PC)
  python main.py master ...     -> maestro por terminal (reparte a las nubes)

Así la MISMA imagen sirve para IaaS (Azure, Huawei, Claro) y PaaS (GuaraCloud).
"""

import os
import sys

if __name__ == "__main__":
    mode = os.getenv("APP_MODE", "batch").lower()
    if mode == "nodo" or sys.argv[1:2] == ["nodo"]:
        import coordinador
        sys.exit(coordinador.run_node())
    if mode == "etcd" or sys.argv[1:2] == ["etcd"]:
        import etcd_node
        sys.exit(etcd_node.main())
    if mode == "worker" or sys.argv[1:2] == ["worker"]:
        import worker
        sys.exit(worker.main())
    if sys.argv[1:2] == ["master"]:
        import master
        sys.exit(master.main(sys.argv[2:]))
    if mode == "server" or sys.argv[1:2] == ["serve"]:
        import server
        sys.exit(server.main())
    import dna_processor
    sys.exit(dna_processor.main(sys.argv[1:]))
