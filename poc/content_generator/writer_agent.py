import os
import re
import json
import uvicorn
import httpx
from dotenv import load_dotenv
from bfa_sdk.core.agent import BFAAgent
from a2a.server.agent_execution.context import RequestContext
from starlette.responses import HTMLResponse, JSONResponse

# Load environmental configurations
load_dotenv()

# Defensive Langsmith integration for real-time cloud tracing
try:
    from langsmith import traceable
except ImportError:
    # Dummy fallback decorator if package is missing
    def traceable(*args, **kwargs):
        return lambda func: func

# Configure environmental options for BFA Gateway routing
os.environ["IRCA_CHANNELS"] = "#content"
os.environ["BFA_GATEWAY_URL"] = "http://127.0.0.1:8000"

@traceable(run_type="llm", name="Writer LLM Generation")
async def generate_llm_content(prompt: str) -> tuple[str, int, int]:
    """Helper to query the configured LLM provider and track token usage."""
    provider = os.getenv("LLM_PROVIDER", "").lower().strip()
    
    # Auto-detect default provider if not explicitly set
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

    # 1. OpenAI Provider
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
                    "temperature": 0.7
                }
                async with httpx.AsyncClient() as client:
                    res = await client.post(url, json=json_payload, headers=headers, timeout=10)
                    if res.status_code == 200:
                        data = res.json()
                        text = data["choices"][0]["message"]["content"]
                        usage = data.get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens", len(prompt) // 4)
                        comp_tokens = usage.get("completion_tokens", len(text) // 4)
                    else:
                        print(f"OpenAI API Error: {res.status_code} - {res.text}")
            except Exception as e:
                print(f"OpenAI Call failed: {e}")

    # 2. Gemini Provider
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
                    else:
                        print(f"Gemini API Error: {res.status_code} - {res.text}")
            except Exception as e:
                print(f"Gemini call failed: {e}")

    # 3. Ollama Provider (Local LLM)
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
                else:
                    print(f"Ollama API Error: {res.status_code} - {res.text}")
        except Exception as e:
            print(f"Ollama call failed: {e}")

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
            # Set usage metadata using the official SDK set method
            rt.set(usage_metadata=usage_dict)
            
            # Support older/custom serialization fallbacks
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

class WriterAgent(BFAAgent):
    def __init__(self):
        super().__init__(
            agent_id="writer-agent",
            name="Writer Agent",
            description="Generates campaign articles while avoiding duplicate keywords.",
            tags=["writer", "content", "essay"],
            examples=["write article", "generate essay for campaign"],
            url="http://127.0.0.1:8106"
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Processes client request. Queries the KeywordsMCP server for already used keywords,
        drafts an essay excluding them, and submits the draft to the ReviewerAgent via A2A.
        """
        # Parse campaign_id and topic
        campaign_match = re.search(r"campaign\s+(\S+)", user_message, re.IGNORECASE)
        topic_match = re.search(r"topic:\s*(.*)", user_message, re.IGNORECASE)

        campaign_id = campaign_match.group(1) if campaign_match else "camp-123"
        
        # Smarker topic extraction
        if topic_match:
            topic = topic_match.group(1).strip()
        else:
            clean_msg = re.sub(r"generate\s+essay\s+for\s+campaign\s+\S+", "", user_message, flags=re.IGNORECASE).strip()
            clean_msg = re.sub(r"campaign\s+\S+", "", clean_msg, flags=re.IGNORECASE).strip()
            topic = clean_msg if clean_msg else "AI Automation"

        # Check for parameter lockdown simulation (hack mode)
        target_campaign_id = campaign_id
        if "hack" in user_message.lower():
            target_campaign_id = "camp-999"

        # Check if the user is asking for a slogan or promotional content
        is_slogan = any(kw in user_message.lower() for kw in ["slogan", "marketing", "promo"])

        provider = os.getenv("LLM_PROVIDER", "").lower().strip() or "openai"
        total_prompt_tokens = 0
        total_comp_tokens = 0
        
        # Initialize execution trace logs
        logs = []
        logs.append("🎬 [START] Initiating collaborative multi-agent execution pipeline...")

        # 1. Gateway Discovery: Resolve used keywords capability
        try:
            async with httpx.AsyncClient() as client:
                logs.append(f"🔍 [STEP 1] Querying BFA Gateway (:8000) to discover a tool for campaign '{campaign_id}'...")
                discover_res = await client.post(
                    "http://127.0.0.1:8000/discover",
                    params={"query": f"get used keywords for campaign {campaign_id}"},
                    json={"session_token": self.session_token},
                    timeout=5
                )

                if discover_res.status_code != 200:
                    return f"Gateway Discovery Failed: {discover_res.json().get('detail', 'Unknown error')}"

                discovery_data = discover_res.json()
                det_token = discovery_data["det"]
                target_url = discovery_data["url"]
                
                logs.append(f"   ↳ [SUCCESS] Gateway matched capability to: Keywords MCP ({target_url})")

                # 2. P2P tool call to KeywordsMCP sending the DET token
                logs.append(f"⚙️ [STEP 2] Calling 'get_used_keywords' on Keywords MCP ({target_url}) via P2P protocol...")
                mcp_res = await client.post(
                    f"{target_url.rstrip('/')}/tools",
                    json={
                        "tool": "get_used_keywords",
                        "arguments": {
                            "delegated_token": det_token,
                            "campaign_id": target_campaign_id
                        }
                    },
                    timeout=5
                )

                if mcp_res.status_code != 200:
                    return f"MCP Tool Invocation Rejected: {mcp_res.text}"

                # Parse the keywords used
                mcp_data = json.loads(mcp_res.json())
                used_keywords = mcp_data.get("used_keywords", [])
                
                logs.append(f"   ↳ [SUCCESS] Keywords MCP returned blacklisted keywords: {used_keywords}")

                # Check if we should dynamically delegate the slogan request to the marketing agent
                delegated_text = None
                if is_slogan:
                    logs.append("🔍 [STEP 2.5] Slogan request detected. Querying BFA Gateway for slogan capability...")
                    try:
                        slogan_discover = await client.post(
                            "http://127.0.0.1:8000/discover",
                            params={"query": "generate slogan for product"},
                            json={"session_token": self.session_token},
                            timeout=5
                        )
                        if slogan_discover.status_code == 200:
                            slogan_data = slogan_discover.json()
                            slogan_url = slogan_data["url"]
                            
                            logs.append(f"   ↳ [MATCH] Gateway matched capability to: Extra Marketing Agent ({slogan_url})")
                            logs.append(f"🚀 [A2A DELEGATION] Routing slogan generation to Extra Marketing Agent ({slogan_url}) via A2A protocol...")
                            
                            # Construct A2A message payload
                            rpc_payload = {
                                "jsonrpc": "2.0",
                                "method": "SendMessage",
                                "params": {
                                    "message": {
                                        "role": 1,
                                        "message_id": "msg-a2a-slogan-001",
                                        "context_id": "ctx-a2a-slogan-001",
                                        "parts": [{"text": topic}]
                                    }
                                },
                                "id": 101
                            }
                            headers = {
                                "A2A-Version": "1.0",
                                "X-Visited-Nodes": "writer-agent"
                            }
                            slogan_res = await client.post(slogan_url, json=rpc_payload, headers=headers, timeout=10)
                            if slogan_res.status_code == 200:
                                raw_slogan_resp = slogan_res.json()["result"]["message"]["parts"][0]["text"]
                                s_match = re.search(r"\[METRICS:\s*prompt_tokens=(\d+),\s*completion_tokens=(\d+)\]", raw_slogan_resp)
                                if s_match:
                                    s_p_tok = int(s_match.group(1))
                                    s_c_tok = int(s_match.group(2))
                                    delegated_text = raw_slogan_resp.split("\n[METRICS:")[0].strip()
                                    total_prompt_tokens += s_p_tok
                                    total_comp_tokens += s_c_tok
                                else:
                                    delegated_text = raw_slogan_resp
                                
                                logs.append(f"   ↳ [SUCCESS] Extra Marketing Agent generated slogan: \"{delegated_text}\"")
                            else:
                                logs.append(f"   ⚠️ [ERROR] Slogan agent HTTP {slogan_res.status_code}. Falling back to local generation.")
                        else:
                            logs.append("   ⚠️ [NO MATCH] Gateway found no active marketing agent. Falling back to local generation.")
                    except Exception as e:
                        logs.append(f"   ⚠️ [ERROR] Slogan agent communication failed: {e}. Falling back to local generation.")

                # 2.7. Research Phase (if not a slogan)
                research_context = ""
                if not is_slogan:
                    logs.append("🔍 [STEP 2.7] Essay request detected. Querying BFA Gateway for research capability...")
                    try:
                        research_discover = await client.post(
                            "http://127.0.0.1:8000/discover",
                            params={"query": "research topic"},
                            json={"session_token": self.session_token},
                            timeout=5
                        )
                        if research_discover.status_code == 200:
                            research_data = research_discover.json()
                            research_url = research_data["url"]
                            
                            logs.append(f"   ↳ [MATCH] Gateway matched capability to: Research Agent ({research_url})")
                            logs.append(f"🚀 [A2A DELEGATION] Routing research task to Research Agent ({research_url}) via A2A protocol...")
                            
                            # Construct A2A message payload
                            rpc_payload = {
                                "jsonrpc": "2.0",
                                "method": "SendMessage",
                                "params": {
                                    "message": {
                                        "role": 1,
                                        "message_id": "msg-a2a-research-001",
                                        "context_id": "ctx-a2a-research-001",
                                        "parts": [{"text": topic}]
                                    }
                                },
                                "id": 102
                            }
                            headers = {
                                "A2A-Version": "1.0",
                                "X-Visited-Nodes": "writer-agent"
                            }
                            research_res = await client.post(research_url, json=rpc_payload, headers=headers, timeout=12)
                            if research_res.status_code == 200:
                                raw_research_resp = research_res.json()["result"]["message"]["parts"][0]["text"]
                                r_match = re.search(r"\[METRICS:\s*prompt_tokens=(\d+),\s*completion_tokens=(\d+)\]", raw_research_resp)
                                if r_match:
                                    r_p_tok = int(r_match.group(1))
                                    r_c_tok = int(r_match.group(2))
                                    research_context = raw_research_resp.split("\n[METRICS:")[0].strip()
                                    total_prompt_tokens += r_p_tok
                                    total_comp_tokens += r_c_tok
                                else:
                                    research_context = raw_research_resp
                                
                                logs.append(f"   ↳ [SUCCESS] Research Agent returned context (length {len(research_context)} chars)")
                            else:
                                logs.append(f"   ⚠️ [ERROR] Research agent HTTP {research_res.status_code}. Proceeding without research.")
                        else:
                            logs.append("   ⚠️ [NO MATCH] Gateway found no active research agent. Proceeding without research.")
                    except Exception as e:
                        logs.append(f"   ⚠️ [ERROR] Research agent communication failed: {e}. Proceeding without research.")

                # 3. Content Generation
                if delegated_text:
                    draft = delegated_text
                    outline = f"Plan: Slogan for '{topic}' avoiding keywords {used_keywords}."
                    logs.append("✍️ [STEP 3] Slogan retrieved from delegated agent. Skipping local drafting.")
                else:
                    outline = f"Plan: Essay on '{topic}' avoiding keywords {used_keywords}."
                    llm_prompt = (
                        f"Write a short, engaging 2-paragraph essay about '{topic}'. "
                        f"Crucial rule: You MUST NOT use any of these words: {used_keywords}. "
                    )
                    if research_context:
                        llm_prompt += f"\nUse the following background research to ground your facts:\n{research_context}\n"
                    
                    llm_prompt += "\nWrite the essay content directly without introductory remarks or meta-text."
                    
                    logs.append(f"✍️ [STEP 3] Calling Writer Agent LLM ({provider}) to draft initial essay...")
                    llm_res1 = await generate_llm_content(llm_prompt)
                    real_draft = llm_res1["output"]
                    p_tok1 = llm_res1["usage_metadata"]["input_tokens"]
                    c_tok1 = llm_res1["usage_metadata"]["output_tokens"]
                    total_prompt_tokens += p_tok1
                    total_comp_tokens += c_tok1

                    if real_draft:
                        draft = real_draft.strip()
                    else:
                        draft = f"Draft essay for topic: '{topic}' without repeating used campaign terms."
                        total_comp_tokens += len(draft) // 4

                # 4. A2A call to ReviewerAgent for critique
                rpc_payload = {
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "params": {
                        "message": {
                            "role": 1,
                            "message_id": "msg-a2a-001",
                            "context_id": "ctx-a2a-001",
                            "parts": [{"text": f"Audit this draft for topic '{topic}':\n{draft}"}]
                        }
                    },
                    "id": 100
                }
                
                # Propagate visited nodes tracking headers (standard BFA loop trace)
                headers = {
                    "A2A-Version": "1.0",
                    "X-Visited-Nodes": "writer-agent"
                }

    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Pure text writing/refinement node.
        Receives writing instructions and calls the LLM provider directly to generate content.
        """
        # Determine if this is a refinement task or an initial draft
        if "refine" in user_message.lower() or "critique" in user_message.lower():
            system_instruction = (
                "You are a professional content editor. Refine the given draft based on the provided critique instructions.\n"
                "Incorporate all corrections and improvements. Respond ONLY with the final refined text, without any conversational intro/outro or surrounding markdown formatting."
            )
        else:
            system_instruction = (
                "You are an expert article writer. Draft a high-quality, engaging, and professional 2-paragraph essay or article based on the provided topic and constraints.\n"
                "Respond ONLY with the generated text, without any conversational intro/outro, headers, or surrounding markdown formatting."
            )

        prompt = f"{system_instruction}\n\nUser request & instructions:\n{user_message}"
        
        llm_res = await generate_llm_content(prompt)
        text = llm_res["output"].strip()
        p_tok = llm_res["usage_metadata"]["input_tokens"]
        c_tok = llm_res["usage_metadata"]["output_tokens"]

        # Report tokens dynamically to BFA Gateway for centralized dashboard tracking
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "http://127.0.0.1:8000/report-tokens",
                    json={"prompt_tokens": p_tok, "completion_tokens": c_tok},
                    timeout=2
                )
        except Exception as e:
            print(f"BFAAgent Warning: Failed to report tokens to Gateway: {e}")

        return f"{text}\n[METRICS: prompt_tokens={p_tok}, completion_tokens={c_tok}]"

agent_instance = WriterAgent()
app = agent_instance.app

if __name__ == "__main__":
    print("[WRITER] Starting WriterAgent on port 8106...")
    uvicorn.run("writer_agent:app", host="127.0.0.1", port=8106, log_level="warning")
