# Backend for Agents SDK (BFA)

Um framework e SDK genérico e opinado para implementar o padrão **BFA (Backend for Agents)**, com suporte nativo a **Roteamento Semântico baseado em FAISS (busca vetorial)** e abstrações padronizadas para Agentes A2A e Servidores MCP.

Projetado para estender e atualizar o roteador tradicional BM25 baseado em palavras-chave, aproveitando buscas vetoriais semânticas para resolver ferramentas e agentes de forma dinâmica.

---

## Documentação Multilíngue
* [English (Inglês)](README.md)
* [Español (Espanhol)](README.es.md)

---

## Arquitetura do Protocolo BFA

O BFA Gateway atua como uma camada de middleware semântico entre os canais de consumo (ex: UIs de mensagens, sistemas de chat) e agentes ou ferramentas especializadas.

```mermaid
graph TD
    Consumer[Consumidor / Whatsapp / WebApp] -->|1. Resolve Query| BFA[BFA Gateway]
    
    subgraph BFA_Gateway ["BFA Gateway (Backend for Agents)"]
        Router[Semantic Router] -->|2. Search Embeddings| FAISS[FAISS Vector Store]
        Registry[Registry] -->|Load metadata| Router
    end
    
    BFA -->|3. Route & Invoke| Agent1[Agente de Cuentas (A2A)]
    BFA -->|3. Route & Invoke| Agent2[Agente de Tarjetas (A2A)]
    BFA -->|4. Execute Tool| MCP1[MDBank MCP (FastMCP)]
```

---

## Principais Recursos

1. **Roteamento Semântico baseado em FAISS:** Em vez de fazer correspondência exata de palavras-chave (como o BM25), o BFA Gateway indexa as descrições, tags e exemplos dos agentes e ferramentas em um índice vetorial local FAISS. Isso resolve consultas mesmo quando sinônimos são usados (ex: associar *"plástico"* a *"cartão de crédito"*).
2. **Abstração `BFAAgent`:** Simplifica a criação de agentes A2A usando o `a2a-sdk` e Starlette. Força a declaração de metadatos essenciais (`tags`, `examples`, `description`) exigidos para a indexação vetorial.
3. **Abstração `BFAMCP`:** Envolve e estende servidores `FastMCP`. Expõe automaticamente um endpoint padronizado `/tools` contendo schemas de entrada, descrições e tags/exemplos customizados para descoberta.
4. **Pronto para Serverless (AWS Lambda):** Inclui um adaptador **Mangum** embutido no Gateway. Combinado com o driver de nuvem `OpenAIEmbedder`, o BFA Gateway roda em Lambda sob demanda com cold-start zero.

---

## Instalação e Execução do Demo

### 1. Instalar as dependências
```bash
pip install -r requirements.txt
# Opcional: instalar em modo de desenvolvimento editável
pip install -e .
```

### 2. Rodar a Demonstração do MDBank
A demonstração inicia três servidores de simulação em segundo plano:
1. Um servidor MCP MDBank (`examples/mock_mdbank_mcp.py`) na porta `8001`.
2. Um agente A2A de Cuentas (`examples/mock_cuentas_agent.py`) na porta `8002`.
3. Um agente A2A de Tarjetas (`examples/mock_tarjetas_agent.py`) na porta `8003`.
4. O Gateway BFA na porta `8000`, realizando a descoberta em tempo real e resolvendo buscas semânticas de teste.

Para rodar:
```bash
python examples/run_demo.py
```

### 3. Rodar o Painel de Controle UI (IRC-A Central Hub)
Incluímos um painel visual construído em React na pasta `examples/frontend` para monitorar a rede de agentes/mcp ativos, registrar dinamicamente novos microserviços (plug-and-play) e conversar diretamente com os agentes do banco:

```bash
# Navegar até a pasta do frontend
cd examples/frontend

# Instalar as dependências
npm install

# Iniciar o servidor de desenvolvimento
npm start
```
Abra `http://localhost:3000` no seu navegador para interagir com o seu hub de agentes local em tempo real.


---

## Créditos e Agradecimentos

Este SDK é uma implementação e extensão de código aberto do padrão de arquitetura **BFA (Backend for Agents)** originalmente idealizado e documentado por **Michael Douglas Barbosa Araujo** (Staff AI Architect).

Você pode ler o artigo original dele introduzindo o padrão aqui:
👉 [O padrão Back-end para Agentes (BFA) - Medium](https://medium.com/@mdbaraujo/o-padr%C3%A3o-back-end-para-agentes-bfa-a53c1c6d87fb)

O objetivo deste projeto é disponibilizar um SDK padronizado e modular, estendendo o conceito original dele com suporte a roteamento semântico vetorial (FAISS) e adaptadores base unificados. Todos os créditos pelo padrão arquitetônico fundamental pertencem a ele.


