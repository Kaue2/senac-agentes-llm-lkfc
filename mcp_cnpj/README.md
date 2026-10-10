# mcp_cnpj — servidor MCP de CNPJ/CEP (Exercício 10)

Confere a matriz e o endereço de uma rede de farmácia concorrente a partir do CNPJ.
O servidor publica `consultar_cnpj` e `consultar_cep` (BrasilAPI) e o recurso
`referencia://ufs`. O cliente encadeia CNPJ -> CEP e não conhece a BrasilAPI.

Requer o SDK `mcp` 2.3.0 e `httpx` (já presentes no `.venv`).

## Como rodar

Terminal 1, o servidor (Streamable HTTP em `http://127.0.0.1:8000/mcp`):

```bash
.venv/bin/python mcp_cnpj/servidor.py
# outra porta: MCP_CNPJ_PORTA=8010 .venv/bin/python mcp_cnpj/servidor.py
```

Terminal 2, o cliente:

```bash
.venv/bin/python mcp_cnpj/cliente_cnpj.py 61.585.865/0001-51
# servidor em outro endereço: MCP_CNPJ_URL=http://127.0.0.1:8010/mcp
```

Códigos de saída do cliente: `0` sucesso, `1` erro de domínio (CNPJ/CEP inválido ou
inexistente), `2` falha de infraestrutura (BrasilAPI fora do ar, timeout, 5xx),
`3` servidor inacessível ou sem as ferramentas esperadas, `64` uso incorreto.

## Testes

Offline (a BrasilAPI é substituída por `httpx.MockTransport`):

```bash
.venv/bin/python -m pytest tests/test_mcp_cnpj.py -q
```

A saída real do cliente para os três CNPJs de teste está no fim de `cliente_cnpj.py`.
