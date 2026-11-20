import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Testes não exportam trace para logs/traces/ (o arquivo é evidência citada nos documentos); o
# teste de telemetria configura um exportador em memória.
os.environ["OTEL_DESLIGADO"] = "1"
