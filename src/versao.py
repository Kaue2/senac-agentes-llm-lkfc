"""Versão do sistema (Parte 3, §4.2): vai para o carimbo de todo log, para a raiz de todo trace e
para todo resultado da suíte de avaliação. Sem ela, nenhum número se compara entre versões.

Semver do SISTEMA, não do código: sobe o minor quando muda o comportamento (prompt, ferramenta,
controle, regra do grafo) e o patch quando só corrige sem mudar o contrato. O histórico, com o
commit de cada versão, está em docs/mudancas.md.
"""

SISTEMA_VERSAO = "2.1.0"
