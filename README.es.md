# Backend for Agents SDK (BFA)

Un framework y SDK genérico y de diseño estructurado para implementar el patrón **BFA (Backend for Agents)**, que cuenta con soporte nativo para **Enrutamiento Semántico basado en FAISS (búsqueda vectorial)** y abstracciones estándar para Agentes A2A y Servidores MCP.

Diseñado para extender y actualizar el enrutador tradicional BM25 (basado en palabras clave), aprovechando búsquedas vectoriales semánticas para resolver herramientas y agentes de forma dinámica.

---

## Documentación Multilingüe
* [English (Inglés)](README.md)
* [Português (Portugués)](README.pt.md)

---

## Arquitectura del Protocolo BFA

El BFA Gateway actúa como una capa de middleware semántico entre los canales de consumo (por ejemplo, UIs de mensajería, chats) y los agentes o herramientas especializadas.

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

## Características Clave

1. **Enrutamiento Semántico con FAISS:** En lugar de coincidencia exacta de palabras clave (como BM25), el BFA Gateway indexa las descripciones, tags y ejemplos de agentes y herramientas en un índice vectorial local de FAISS. Esto resuelve consultas incluso usando sinónimos (por ejemplo, asociar *"plástico"* con *"tarjeta de crédito"*).
2. **Abstracción `BFAAgent`:** Simplifica la creación de agentes A2A usando el `a2a-sdk` y Starlette. Obliga a declarar metadatos indispensables (`tags`, `examples`, `description`) requeridos para la indexación semántica.
3. **Abstracción `BFAMCP`:** Envuelve y extiende servidores de `FastMCP`. Expone automáticamente un endpoint estandarizado `/tools` con schemas de entrada, descripciones y tags/ejemplos customizados.
4. **Listo para Serverless (AWS Lambda):** Incluye un adaptador de **Mangum** integrado en el Gateway. Combinado con el driver de nube `OpenAIEmbedder`, el BFA Gateway corre en Lambda bajo demanda con cold-start cero.

---

## Instalación y Ejecución de la Demo

### 1. Instalar dependencias
```bash
pip install -r requirements.txt
# Opcional: instalar en modo de desarrollo editable
pip install -e .
```

### 2. Ejecutar la Demo MDBank
La demo inicia tres servidores de simulación en segundo plano:
1. Un servidor MCP MDBank (`examples/mock_mdbank_mcp.py`) en el puerto `8001`.
2. Un agente A2A de Cuentas (`examples/mock_cuentas_agent.py`) en el puerto `8002`.
3. Un agente A2A de Tarjetas (`examples/mock_tarjetas_agent.py`) en el puerto `8003`.
4. El Gateway BFA en el puerto `8000`, realizando el descubrimiento dinámico en red y resolviendo búsquedas semánticas de prueba.

Para ejecutar:
```bash
python examples/run_demo.py
```

### 3. Ejecutar el Panel de Control UI (IRC-A Central Hub)
Hemos incluido un panel visual interactivo desarrollado en React bajo la carpeta `examples/frontend` para monitorear la red de agentes y MCPs activos en tiempo real, registrar dinámicamente nuevos microservicios (plug-and-play) y chatear directamente con los agentes bancarios:

```bash
# Navegar a la carpeta del frontend
cd examples/frontend

# Instalar las dependencias
npm install

# Iniciar el servidor de desarrollo
npm start
```
Abre `http://localhost:3000` en tu navegador para interactuar con tu hub de agentes local en tiempo real.


---

## Créditos y Agradecimientos

Este SDK es una implementación y extensión de código abierto del patrón de arquitectura **BFA (Backend for Agents)** originalmente diseñado y documentado por **Michael Douglas Barbosa Araujo** (Staff AI Architect).

Puedes leer su artículo original introduciendo el patrón aquí:
👉 [O padrão Back-end para Agentes (BFA) - Medium](https://medium.com/@mdbaraujo/o-padr%C3%A3o-back-end-para-agentes-bfa-a53c1c6d87fb)

El objetivo de este proyecto es proveer un SDK modular y estandarizado que extiende su concepto original incorporando soporte para enrutamiento semántico vectorial (FAISS) y adaptadores base unificados. Todo el crédito por el diseño y la visión original de este patrón arquitectónico le pertenece a él.


