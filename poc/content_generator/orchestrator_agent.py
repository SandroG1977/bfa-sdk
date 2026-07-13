import os
import re
import json
import uvicorn
import httpx
from dotenv import load_dotenv
from bfa_sdk.core.agent import BFAAgent
from a2a.server.agent_execution.context import RequestContext
from starlette.responses import HTMLResponse, JSONResponse

load_dotenv()

# Defensive Langsmith integration for real-time cloud tracing
try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        return lambda func: func

# Configure environmental options for BFA Gateway routing
os.environ["IRCA_CHANNELS"] = "#content"
os.environ["BFA_GATEWAY_URL"] = "http://127.0.0.1:8000"

@traceable(run_type="llm", name="Orchestrator Planner LLM")
async def generate_llm_content(prompt: str) -> dict:
    """Helper to query the configured LLM provider and track token usage."""
    provider = os.getenv("LLM_PROVIDER", "").lower().strip()
    if not provider:
        if os.getenv("OPENAI_API_KEY", "").strip().strip("'\""):
            provider = "openai"
        elif (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")).strip().strip("'\""):
            provider = "gemini"
        else:
            provider = "mock"

    text = ""
    prompt_tokens = len(prompt) // 4
    comp_tokens = 0

    # 1. OpenAI
    if provider == "openai":
        openai_key = os.getenv("OPENAI_API_KEY", "").strip().strip("'\"")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip().strip("'\"")
        if openai_key:
            try:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}"
                }
                json_payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2
                }
                async with httpx.AsyncClient() as client:
                    res = await client.post(url, json=json_payload, headers=headers, timeout=10)
                    if res.status_code == 200:
                        data = res.json()
                        text = data["choices"][0]["message"]["content"]
                        usage = data.get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens", len(prompt) // 4)
                        comp_tokens = usage.get("completion_tokens", len(text) // 4)
            except Exception as e:
                print(f"[ORCHESTRATOR] OpenAI failed: {e}")

    # 2. Gemini
    elif provider == "gemini":
        gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")).strip().strip("'\"")
        if gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
                async with httpx.AsyncClient() as client:
                    res = await client.post(
                        url,
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        headers={"Content-Type": "application/json"},
                        timeout=10
                    )
                    if res.status_code == 200:
                        data = res.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        usage = data.get("usageMetadata", {})
                        prompt_tokens = usage.get("promptTokenCount", len(prompt) // 4)
                        comp_tokens = usage.get("candidatesTokenCount", len(text) // 4)
            except Exception as e:
                print(f"[ORCHESTRATOR] Gemini failed: {e}")

    # 3. Ollama
    elif provider == "ollama":
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip().strip("'\"")
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3").strip().strip("'\"")
        try:
            url = f"{ollama_host.rstrip('/')}/api/chat"
            json_payload = {
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=json_payload, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    text = data["message"]["content"]
                    prompt_tokens = data.get("prompt_eval_count", len(prompt) // 4)
                    comp_tokens = data.get("eval_count", len(text) // 4)
        except Exception as e:
            print(f"[ORCHESTRATOR] Ollama failed: {e}")

    # Log custom LLM metrics to Langsmith if package is active and environment variables are set
    try:
        from langsmith import get_current_run_tree
        rt = get_current_run_tree()
        if rt:
            rt.metadata.update({
                "ls_provider": provider,
                "ls_model_name": os.getenv("OPENAI_MODEL", "gpt-4o-mini") if provider == "openai" else provider
            })
            usage_dict = {
                "input_tokens": prompt_tokens,
                "output_tokens": comp_tokens,
                "total_tokens": prompt_tokens + comp_tokens
            }
            rt.set(usage_metadata=usage_dict)
            if not isinstance(rt.extra, dict):
                rt.extra = {}
            rt.extra["usage_metadata"] = usage_dict
            try:
                rt.usage_metadata = usage_dict
            except:
                pass
    except Exception as e:
        pass

    return {
        "output": text,
        "usage_metadata": {
            "input_tokens": prompt_tokens,
            "output_tokens": comp_tokens,
            "total_tokens": prompt_tokens + comp_tokens
        }
    }

class OrchestratorAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="orchestrator-agent",
            name="Orchestrator Agent",
            description="OpenClaw-style generic planner agent that receives instructions and dynamically delegates to BFA nodes.",
            tags=["orchestrator", "planner", "assistant"],
            examples=["research a topic", "write an essay on something", "generate a slogan"],
            url="http://127.0.0.1:8101"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        logs = []
        logs.append("🎬 [START] Orchestrator Agent received instruction: " + user_message)

        # 1. Ask the LLM to plan which Gateway capability to discover
        planner_prompt = (
            "You are the Orchestrator Agent (OpenClaw-style planner). You receive instructions and decide which capability to query in the BFA Gateway.\n"
            f"User instruction: '{user_message}'\n\n"
            "We have these capabilities registered in BFA:\n"
            "- 'research topic' (Research Agent)\n"
            "- 'write article' (Writer Agent)\n"
            "- 'generate slogan for product' (Extra Marketing Agent)\n"
            "- 'get used keywords for campaign' (Keywords MCP tool)\n\n"
            "Rules:\n"
            "1. CRITICAL: If the user request asks to write, create, draft, compose, or generate an article, essay, text, or post (even if it also mentions research, web search, or keyword checks), you MUST select 'write article'. The Writer Agent is the one responsible for the entire content writing flow, and it will handle the research, keyword checks, and reviews internally.\n"
            "2. Select 'research topic' ONLY if the user ONLY wants web search results or info gathering, and does NOT want to write an essay/article.\n"
            "3. If the user wants a slogan, select 'generate slogan for product'.\n"
            "4. If the user wants to check keywords or campaign details, select 'get used keywords for campaign'.\n\n"
            "Respond ONLY with a valid JSON block containing:\n"
            "{\n"
            "  \"capability\": \"write article\" | \"research topic\" | \"generate slogan for product\" | \"get used keywords for campaign\",\n"
            "  \"payload\": \"the exact message or payload to delegate to the target\"\n"
            "}"
        )

        logs.append("🧠 [STEP 1] Generating plan using Orchestrator Planner LLM...")
        llm_res = await generate_llm_content(planner_prompt)
        plan_text = llm_res["output"].strip()
        p_tok = llm_res["usage_metadata"]["input_tokens"]
        c_tok = llm_res["usage_metadata"]["output_tokens"]

        total_prompt_tokens = p_tok
        total_comp_tokens = c_tok

        # Parse JSON from planner output
        try:
            # Clean possible markdown block markers
            plan_clean = re.sub(r"```json\s*", "", plan_text)
            plan_clean = re.sub(r"```\s*$", "", plan_clean).strip()
            plan_data = json.loads(plan_clean)
            target_capability = plan_data["capability"]
            target_payload = plan_data["payload"]
        except Exception as e:
            logs.append(f"   ⚠️ [ERROR] Failed to parse planning output: {e}. Defaulting to 'write article'.")
            target_capability = "write article"
            target_payload = user_message

        logs.append(f"   ↳ [PLAN] Selected capability: '{target_capability}' with payload: '{target_payload}'")

        # 2. Query Gateway for discovery
        logs.append(f"🔍 [STEP 2] Querying BFA Gateway to discover a handler for '{target_capability}'...")
        async with httpx.AsyncClient() as client:
            try:
                discover_res = await client.post(
                    "http://127.0.0.1:8000/discover",
                    params={"query": target_capability},
                    json={"session_token": self.session_token},
                    timeout=5
                )
                if discover_res.status_code != 200:
                    return f"Gateway Discovery Failed: {discover_res.text}"

                discovery_data = discover_res.json()
                target_url = discovery_data["url"]
                node_type = discovery_data.get("type", "agent")
                
                logs.append(f"   ↳ [SUCCESS] Gateway matched capability to: {target_url} ({node_type})")
            except Exception as e:
                return f"Discovery Request Failed: {e}"

            # 3. Delegation Execution (A2A or P2P tool call)
            logs.append(f"🚀 [STEP 3] Delegating execution to handler {target_url} via BFA protocol...")
            if node_type == "agent":
                # A2A SendMessage
                rpc_payload = {
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "role": 1,
                            "message_id": "msg-orchestrator-delegation-001",
                            "context_id": "ctx-orchestrator-delegation-001",
                            "parts": [{"text": target_payload}]
                        }
                    },
                    "id": 500
                }
                headers = {
                    "A2A-Version": "1.0",
                    "X-Visited-Nodes": "orchestrator-agent"
                }
                
                try:
                    agent_res = await client.post(target_url, json=rpc_payload, headers=headers, timeout=35)
                    if agent_res.status_code == 200:
                        raw_resp = agent_res.json()["result"]["message"]["parts"][0]["text"]
                        
                        # Extract metrics if present
                        metrics_match = re.search(r"\[TOTAL_METRICS:\s*prompt_tokens=(\d+),\s*completion_tokens=(\d+)\]", raw_resp)
                        if not metrics_match:
                            metrics_match = re.search(r"\[METRICS:\s*prompt_tokens=(\d+),\s*completion_tokens=(\d+)\]", raw_resp)
                            
                        if metrics_match:
                            sub_p = int(metrics_match.group(1))
                            sub_c = int(metrics_match.group(2))
                            clean_resp = raw_resp.split("\n[METRICS:")[0].split("\n[TOTAL_METRICS:")[0].strip()
                            total_prompt_tokens += sub_p
                            total_comp_tokens += sub_c
                        else:
                            clean_resp = raw_resp
                        
                        logs.append("🏁 [FINISH] Dynamic delegation completed successfully.")
                        
                        final_output = (
                            "=== Orchestrator Agent Execution Steps ===\n"
                            + "\n".join(logs) + "\n\n"
                            + f"=== Result from Discovered Node ({target_url}) ===\n"
                            + f"{clean_resp}\n"
                            + f"[TOTAL_METRICS: prompt_tokens={total_prompt_tokens}, completion_tokens={total_comp_tokens}]"
                        )
                        
                        # Report tokens to Gateway
                        try:
                            await client.post(
                                "http://127.0.0.1:8000/report-tokens",
                                json={"prompt_tokens": total_prompt_tokens, "completion_tokens": total_comp_tokens},
                                timeout=2
                            )
                        except:
                            pass
                            
                        return final_output
                    else:
                        return f"Delegation HTTP Error {agent_res.status_code}: {agent_res.text}"
                except Exception as e:
                    return f"Delegation Connection Failed: {e}"
            else:
                # P2P Tool Call (for KeywordsMCP)
                # Parse campaign_id from payload or default
                campaign_match = re.search(r"campaign\s+(\S+)", target_payload, re.IGNORECASE)
                campaign_id = campaign_match.group(1) if campaign_match else "camp-123"
                
                try:
                    tool_res = await client.post(
                        f"{target_url.rstrip('/')}/tools",
                        json={
                            "tool": "get_used_keywords",
                            "arguments": {
                                "delegated_token": discovery_data.get("det", "dummy-det"),
                                "campaign_id": campaign_id
                            }
                        },
                        timeout=5
                    )
                    if tool_res.status_code == 200:
                        mcp_data = json.loads(tool_res.json())
                        used_keywords = mcp_data.get("used_keywords", [])
                        logs.append("🏁 [FINISH] P2P Tool execution completed successfully.")
                        
                        final_output = (
                            "=== Orchestrator Agent Execution Steps ===\n"
                            + "\n".join(logs) + "\n\n"
                            + f"=== Result from Discovered MCP Server ({target_url}) ===\n"
                            + f"Campaign '{campaign_id}' forbidden keywords: {used_keywords}\n"
                            + f"[TOTAL_METRICS: prompt_tokens={total_prompt_tokens}, completion_tokens={total_comp_tokens}]"
                        )
                        return final_output
                    else:
                        return f"MCP Tool Invocation Rejected: {tool_res.text}"
                except Exception as e:
                    return f"MCP Tool Connection Failed: {e}"

agent_instance = OrchestratorAgent()
app = agent_instance.app

# Serve Visualizer HTML Dashboard
async def serve_dashboard(request):
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Visualizer Dashboard Template Not Found</h1>", status_code=404)

# Endpoint to check which API Key is loaded in the .env file
async def api_status(request):
    provider = os.getenv("LLM_PROVIDER", "").lower().strip()
    if not provider:
        if os.getenv("OPENAI_API_KEY", "").strip().strip("'\""):
            provider = "openai"
        elif (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")).strip().strip("'\""):
            provider = "gemini"
        else:
            provider = "mock"
    return JSONResponse({"provider": provider})

# Proxy endpoint to check online status of all registered nodes without browser CORS issues
async def get_nodes_status(request):
    gateway_online = False
    status_list = []
    try:
        async with httpx.AsyncClient() as client:
            try:
                res_gw = await client.get("http://127.0.0.1:8000/", timeout=1)
                if res_gw.status_code == 200:
                    gateway_online = True
            except:
                pass
            
            if gateway_online:
                res = await client.get("http://127.0.0.1:8000/skills", timeout=2)
                if res.status_code == 200:
                    skills = res.json()
                    unique_nodes = {}
                    for item in skills.values():
                        url = item.get("url") or item.get("server_url")
                        if not url:
                            continue
                        
                        port = ""
                        try:
                            from urllib.parse import urlparse
                            u = urlparse(url)
                            port = f"(:{u.port})" if u.port else ""
                        except:
                            pass
                        
                        clean_url = url.rstrip('/')
                        if item.get("type") == "agent":
                            unique_nodes[clean_url] = {
                                "name": f"{item.get('name', 'Agent')} {port}",
                                "check_url": f"{clean_url}/.well-known/agent-card.json"
                            }
                        else:
                            server_name = "Keywords MCP" if item.get("name") in ["get_used_keywords", "reserve_keyword"] else "MCP Server"
                            unique_nodes[clean_url] = {
                                "name": f"{server_name} {port}",
                                "check_url": f"{clean_url}/tools"
                            }
                    
                    # Check online status of each node server-side
                    for clean_url, node in unique_nodes.items():
                        node_online = False
                        try:
                            test_res = await client.get(node["check_url"], timeout=1)
                            if test_res.status_code == 200:
                                node_online = True
                        except:
                            pass
                        status_list.append({
                            "name": node["name"],
                            "online": node_online
                        })
    except Exception as e:
        print(f"Error checking nodes status: {e}")
    
    return JSONResponse({
        "gateway_online": gateway_online,
        "nodes": status_list
    })

# Proxy route to pull skills list from BFA Gateway server-side (prevents browser CORS errors)
async def get_gateway_skills(request):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("http://127.0.0.1:8000/skills", timeout=2)
            if res.status_code == 200:
                return JSONResponse(res.json())
            return JSONResponse({"error": f"Gateway returned {res.status_code}"}, status_code=res.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# Proxy route to pull token metrics from BFA Gateway server-side (prevents browser CORS errors)
async def get_gateway_token_metrics(request):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("http://127.0.0.1:8000/token-metrics", timeout=2)
            if res.status_code == 200:
                return JSONResponse(res.json())
            return JSONResponse({"error": f"Gateway returned {res.status_code}"}, status_code=res.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# Action trigger endpoint to run the different POC flows
async def run_visual_flow(request):
    flow_type = request.path_params.get("flow_type")
    body = await request.json()
    query_text = body.get("query", "")
    
    async with httpx.AsyncClient() as client:
        headers = {"A2A-Version": "1.0"}
        
        if flow_type == "normal":
            rpc_payload = {
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": 1,
                        "message_id": "visual-msg-1",
                        "context_id": "visual-ctx-1",
                        "parts": [{"text": query_text}]
                    }
                },
                "id": 1
            }
            res = await client.post("http://127.0.0.1:8101/", json=rpc_payload, headers=headers, timeout=40)
            if res.status_code == 200:
                res_data = res.json()
                if "error" in res_data:
                    return JSONResponse({"error": res_data["error"]["message"]})
                
                raw_result = res_data["result"]["message"]["parts"][0]["text"]
                total_prompt = 0
                total_comp = 0
                
                metrics_match = re.search(
                    r"\[TOTAL_METRICS:\s*prompt_tokens=(\d+),\s*completion_tokens=(\d+)\]",
                    raw_result
                )
                if metrics_match:
                    total_prompt = int(metrics_match.group(1))
                    total_comp = int(metrics_match.group(2))
                    result_text = raw_result.split("[TOTAL_METRICS:")[0].strip()
                else:
                    result_text = raw_result
                
                return JSONResponse({
                    "result": result_text,
                    "tokens": {
                        "prompt_tokens": total_prompt,
                        "completion_tokens": total_comp,
                        "total_tokens": total_prompt + total_comp
                    }
                })
            return JSONResponse({"error": f"HTTP Error {res.status_code}: {res.text}"})
            
        elif flow_type == "hack":
            # Direct hack test to WriterAgent to showcase parameters lockdown block
            rpc_payload = {
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": 1,
                        "message_id": "visual-msg-2",
                        "context_id": "visual-ctx-2",
                        "parts": [{"text": f"generate essay for campaign camp-123 on topic: {query_text} hack"}],
                    }
                },
                "id": 2
            }
            res = await client.post("http://127.0.0.1:8106/", json=rpc_payload, headers=headers, timeout=40)
            if res.status_code == 200:
                res_data = res.json()
                if "error" in res_data:
                    return JSONResponse({"error": res_data["error"]["message"]})
                
                raw_result = res_data["result"]["message"]["parts"][0]["text"]
                return JSONResponse({
                    "result": raw_result,
                    "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                })
            return JSONResponse({"error": f"HTTP Error {res.status_code}: {res.text}"})
            
        elif flow_type == "loop":
            rpc_payload = {
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": 1,
                        "message_id": "visual-msg-3",
                        "context_id": "visual-ctx-3",
                        "parts": [{"text": "loop"}]
                    }
                },
                "id": 3
            }
            res = await client.post("http://127.0.0.1:8103/", json=rpc_payload, headers=headers, timeout=40)
            if res.status_code == 200:
                res_data = res.json()
                if "error" in res_data:
                    return JSONResponse({"result": f"Status: 409, Body: {json.dumps(res_data)}"})
                
                raw_result = res_data["result"]["message"]["parts"][0]["text"]
                return JSONResponse({
                    "result": raw_result,
                    "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                })
            return JSONResponse({"result": f"Status: {res.status_code}, Body: {res.text}"})

from starlette.routing import Route
app.routes.append(Route("/", serve_dashboard, methods=["GET"]))
app.routes.append(Route("/api-status", api_status, methods=["GET"]))
app.routes.append(Route("/api-status/nodes", get_nodes_status, methods=["GET"]))
app.routes.append(Route("/api/gateway/skills", get_gateway_skills, methods=["GET"]))
app.routes.append(Route("/api/gateway/token-metrics", get_gateway_token_metrics, methods=["GET"]))
app.routes.append(Route("/run-flow/{flow_type}", run_visual_flow, methods=["POST"]))

if __name__ == "__main__":
    print("[ORCHESTRATOR] Starting OrchestratorAgent on port 8101...")
    uvicorn.run("orchestrator_agent:app", host="127.0.0.1", port=8101, log_level="warning")
