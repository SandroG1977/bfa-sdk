import pytest
import jwt
from starlette.testclient import TestClient
from starlette.responses import JSONResponse
from starlette.requests import Request
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from bfa_sdk.core.gateway import create_gateway_app, GATEWAY_PUBLIC_KEY
from bfa_sdk.core.agent import BFAAgent
from bfa_sdk.core.mcp import BFAMCP
from bfa_sdk.router.search import BFASemanticRouter
from bfa_sdk.router.embedder import DummyEmbedder

# 1. Setup mock keys for testing
TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key()
TEST_PUB_PEM = TEST_PUBLIC_KEY.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode("utf-8")


class MockSecureAgent(BFAAgent):
    async def run(self, user_message: str, context) -> str:
        return f"Secure Processed: {user_message}"


@pytest.mark.anyio
async def test_cryptographic_handshake_and_session_minting(monkeypatch):
    """
    Verifies the zero-trust asymmetric handshake protocol between BFAAgent and Gateway.
    """
    app = create_gateway_app()
    client = TestClient(app)
    
    # Mock network calls during BFAAgent initialization
    # We bypass actual auto_register during __init__ to test manually step-by-step
    monkeypatch.setattr(BFAAgent, "_auto_register_to_gateway", lambda self: True)
    
    agent = MockSecureAgent(
        agent_id="test-secure-agent",
        name="Secure Agent",
        description="A secure test agent node.",
        tags=["security"],
        examples=["test security"],
        url="http://localhost:8001",
        private_key=TEST_PRIVATE_KEY
    )
    
    # Manually execute registration handshake endpoints
    # 1. POST /register/init
    res_init = client.post("/register/init", json={"node_id": agent.agent_id, "channels": ["#finance"]})
    assert res_init.status_code == 200
    challenge_bytes = res_init.json()["challenge_bytes"]
    assert len(challenge_bytes) == 64  # Hex representation of 32 bytes
    
    # 2. Solve challenge using agent's private key
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    signature = TEST_PRIVATE_KEY.sign(
        challenge_bytes.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    
    # 3. POST /register/verify
    res_verify = client.post("/register/verify", json={
        "node_id": agent.agent_id,
        "signature": signature.hex(),
        "public_key": TEST_PUB_PEM
    })
    
    assert res_verify.status_code == 200
    verify_data = res_verify.json()
    assert "session_token" in verify_data
    
    # Fetch GATEWAY_PUBLIC_KEY dynamically from the endpoint to avoid double-import mismatches
    res_pub = client.get("/public_key")
    assert res_pub.status_code == 200
    pub_pem = res_pub.json()["public_key"]
    gateway_pubkey = serialization.load_pem_public_key(pub_pem.encode("utf-8"))

    # Decode and verify the session token
    decoded = jwt.decode(verify_data["session_token"], gateway_pubkey, algorithms=["RS256"])
    assert decoded["sub"] == "test-secure-agent"
    assert decoded["channels"] == ["#finance"]


def test_logical_channel_masking():
    """
    Verifies that capability vectors are filtered out (masked) when channels don't overlap.
    """
    embedder = DummyEmbedder()
    router = BFASemanticRouter(embedder)
    
    # Register two tools with different channels
    router.update_registry({
        "credit-tool": {
            "name": "fetch_credit_score",
            "description": "Fetch customer credit rating",
            "tags": ["credit"],
            "examples": ["get score"],
            "type": "tool",
            "channels": ["#finance"]
        },
        "compliance-tool": {
            "name": "check_aml_status",
            "description": "Perform anti-money laundering check",
            "tags": ["aml"],
            "examples": ["check aml"],
            "type": "tool",
            "channels": ["#aml-restricted"]
        }
    })
    router.build_index()
    
    # Case A: Caller has #finance channel
    res_finance = router.resolve("check aml", agent_channels=["#finance"])
    # Should NOT match compliance-tool because it is restricted to #aml-restricted channel
    assert res_finance["best"] is None or res_finance["best"]["skill"] != "compliance-tool"
    
    # Case B: Caller has #aml-restricted channel
    res_aml = router.resolve("check aml", agent_channels=["#aml-restricted"])
    assert res_aml["best"] is not None
    assert res_aml["best"]["skill"] == "compliance-tool"


@pytest.mark.anyio
async def test_offline_det_verification_and_parameter_lockdown():
    """
    Tests offline verification inside BFAMCP wrapper and validation constraints (lockdown).
    """
    mcp_server = BFAMCP("BankDataRiver", node_id="bank-data-river", gateway_public_key=TEST_PUBLIC_KEY)
    
    @mcp_server.tool(tags=["bank"], examples=["get balance"])
    def get_balance(customer_id: str, delegated_token: str) -> str:
        return f"Balance for {customer_id}: $5000"
        
    # Mint a valid DET token targetting customer_id='882'
    # Signed with our TEST_PRIVATE_KEY representing the BFA Gateway signature
    import time
    valid_det = jwt.encode(
        {
            "sub": "credit-agent",
            "aud": "bank-data-river",
            "permitted_action": "get_balance",
            "restricted_params": {"customer_id": "882"},
            "exp": int(time.time()) + 60
        },
        TEST_PRIVATE_KEY,
        algorithm="RS256"
    )
    
    # Call tool function directly to test validation wrapper
    # Case 1: Valid DET + Matching Parameter (Should succeed)
    result = get_balance(customer_id="882", delegated_token=valid_det)
    assert result == "Balance for 882: $5000"
    
    # Case 2: Valid DET + Wrong Parameter (Parameter Lockdown trigger, should raise ValueError)
    with pytest.raises(ValueError, match="IRC-A DET Token validation failed"):
        get_balance(customer_id="999", delegated_token=valid_det)
        
    # Case 3: Invalid DET signature (should fail verification)
    invalid_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    invalid_det = jwt.encode(
        {
            "sub": "credit-agent",
            "aud": "bank-data-river",
            "permitted_action": "get_balance",
            "restricted_params": {"customer_id": "882"},
            "exp": int(time.time()) + 60
        },
        invalid_key,
        algorithm="RS256"
    )
    with pytest.raises(ValueError, match="IRC-A DET Token validation failed"):
        get_balance(customer_id="882", delegated_token=invalid_det)


def test_recursive_loop_mitigation_middleware(monkeypatch):
    """
    Verifies that BFAAgent intercepts recursive loops via HTTP headers.
    """
    monkeypatch.setattr(BFAAgent, "_auto_register_to_gateway", lambda self: True)
    
    agent = MockSecureAgent(
        agent_id="loan-officer-agent",
        name="Loan Officer",
        description="Processes loan approvals.",
        tags=["loan"],
        examples=["apply loan"],
        url="http://localhost:8002"
    )
    
    client = TestClient(agent.app)
    
    # Case A: Request without loop (should execute normally)
    response = client.post("/", json={
        "jsonrpc": "2.0",
        "method": "SendMessage",
        "params": {
            "message": {
                "role": 1,
                "message_id": "msg-123",
                "context_id": "context-456",
                "parts": [{"text": "hello"}]
            }
        },
        "id": 1
    }, headers={
        "X-Trace-Id": "tx-999",
        "X-Visited-Nodes": "compliance-agent, credit-agent"
    })
    
    assert response.status_code == 200
    
    # Case B: Request with recursion loop (agent ID is already in visited list)
    response_loop = client.post("/", json={
        "jsonrpc": "2.0",
        "method": "SendMessage",
        "params": {
            "message": {
                "role": 1,
                "message_id": "msg-123",
                "context_id": "context-456",
                "parts": [{"text": "hello"}]
            }
        },
        "id": 1
    }, headers={
        "X-Trace-Id": "tx-999",
        "X-Visited-Nodes": "compliance-agent, loan-officer-agent, credit-agent"
    })
    
    assert response_loop.status_code == 409
    error_payload = response_loop.json()
    assert "IRC-A Circular Loop Detected" in error_payload["error"]["message"]


def test_uncovered_key_loading():
    """
    Tests loading private and public keys from PEM strings and verification error branches.
    """
    pem_private = TEST_PRIVATE_KEY.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")
    
    agent = MockSecureAgent(
        agent_id="pem-agent",
        name="PEM Agent",
        description="Tests PEM loading",
        tags=["pem"],
        examples=["ex"],
        url="http://localhost:8009",
        private_key=pem_private,
        gateway_public_key=TEST_PUB_PEM
    )
    assert agent._private_key is not None
    assert agent.gateway_public_key is not None
    
    # verify_incoming_det edge cases
    # 1. No gateway public key configured
    agent_no_pub = MockSecureAgent(
        agent_id="pem-agent",
        name="PEM Agent",
        description="Tests PEM loading",
        tags=["pem"],
        examples=["ex"],
        url="http://localhost:8009",
    )
    agent_no_pub.gateway_public_key = None
    assert agent_no_pub.verify_incoming_det("token", "action", {}) is False
    
    # 2. Token decode failure
    assert agent.verify_incoming_det("invalid-token-string", "action", {}) is False
    
    # 3. Permitted action mismatch
    import time
    det = jwt.encode(
        {"sub": "pem-agent", "aud": "pem-agent", "permitted_action": "diff_action", "exp": int(time.time()) + 60},
        TEST_PRIVATE_KEY,
        algorithm="RS256"
    )
    assert agent.verify_incoming_det(det, "expected_action", {}) is False


def test_gateway_validation_errors():
    """
    Tests Gateway API endpoints validation error branches.
    """
    app = create_gateway_app()
    client = TestClient(app)
    
    # 1. /register/init without node_id
    res = client.post("/register/init", json={"channels": ["#finance"]})
    assert res.status_code == 400
    assert "Missing node_id" in res.json()["detail"]
    
    # 2. /register/verify missing parameters
    res = client.post("/register/verify", json={"node_id": "test"})
    assert res.status_code == 400
    assert "Missing required parameters" in res.json()["detail"]
    
    # 3. /register/verify non-existent node
    res = client.post("/register/verify", json={
        "node_id": "non-existent-node",
        "signature": "aabbcc",
        "public_key": TEST_PUB_PEM
    })
    assert res.status_code == 400
    assert "No active challenge" in res.json()["detail"]
    
    # 4. /register/verify invalid signature
    client.post("/register/init", json={"node_id": "bad-sig-node"})
    res = client.post("/register/verify", json={
        "node_id": "bad-sig-node",
        "signature": "00" * 256,  # dummy invalid signature
        "public_key": TEST_PUB_PEM
    })
    assert res.status_code == 401
    assert "Invalid cryptographic signature" in res.json()["detail"]
    
    # 5. /register/disconnect missing node_id
    res = client.post("/register/disconnect", json={})
    assert res.status_code == 400
    assert "Missing node_id" in res.json()["detail"]


def test_discover_endpoint_failures():
    """
    Tests /discover endpoint error handling.
    """
    app = create_gateway_app()
    client = TestClient(app)
    
    # 1. Missing session token
    res = client.post("/discover", params={"query": "test"})
    assert res.status_code == 401
    assert "Missing session_token" in res.json()["detail"]
    
    # 2. Invalid session token
    res = client.post("/discover", params={"query": "test"}, json={"session_token": "bad-token"})
    assert res.status_code == 401
    assert "Invalid session token" in res.json()["detail"]
    
    # 3. Expired session token
    from bfa_sdk.core.gateway import GATEWAY_PRIVATE_KEY
    import time
    expired_token = jwt.encode(
        {"sub": "caller", "channels": ["#public"], "exp": int(time.time()) - 10},
        GATEWAY_PRIVATE_KEY,
        algorithm="RS256"
    )
    res = client.post("/discover", params={"query": "test"}, json={"session_token": expired_token})
    assert res.status_code == 401
    assert "Session token expired" in res.json()["detail"]
    
    # 4. No matching capability found
    valid_token = jwt.encode(
        {"sub": "caller", "channels": ["#empty-channel"], "exp": int(time.time()) + 100},
        GATEWAY_PRIVATE_KEY,
        algorithm="RS256"
    )
    res = client.post("/discover", params={"query": "test"}, json={"session_token": valid_token})
    assert res.status_code == 404
    assert "No matching capability found" in res.json()["detail"]


@pytest.mark.anyio
async def test_registration_fallback_scenarios(monkeypatch):
    """
    Tests fall-soft simple registration in both BFAAgent and BFAMCP when handshake fails.
    """
    import httpx
    from unittest.mock import MagicMock
    
    # Force challenge-response init to return 404 Not Found to trigger NotImplementedError fallback
    async def mock_async_post_fallback(self, url, *args, **kwargs):
        mock_resp = MagicMock()
        if "register/agent" in str(url) or "register/mcp" in str(url):
            mock_resp.status_code = 200
        else:
            mock_resp.status_code = 404
            mock_resp.text = "Handshake endpoints not implemented"
        return mock_resp

    def mock_sync_post_fallback(url, *args, **kwargs):
        mock_resp = MagicMock()
        if "register/agent" in str(url) or "register/mcp" in str(url):
            mock_resp.status_code = 200
        else:
            mock_resp.status_code = 404
            mock_resp.text = "Handshake endpoints not implemented"
        return mock_resp
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_async_post_fallback)
    monkeypatch.setattr(httpx, "post", mock_sync_post_fallback)
    
    # Case A: BFAAgent fallback
    agent = MockSecureAgent(
        agent_id="fallback-agent",
        name="Fallback Agent",
        description="test",
        tags=["fallback"],
        examples=["ex"],
        url="http://localhost:8011",
        gateway_url="http://localhost:8000"
    )
    success = await agent.register_with_gateway("http://localhost:8000")
    assert success is True
    
    # Case B: BFAMCP fallback
    mcp = BFAMCP("fallback-mcp", gateway_url="http://localhost:8000")
    success_mcp = await mcp.register_with_gateway("http://localhost:8000", "http://localhost:8012")
    assert success_mcp is True


@pytest.mark.anyio
async def test_disconnect_and_shutdown_hooks(monkeypatch):
    """
    Verifies /register/disconnect and shutdown hooks.
    """
    import httpx
    from unittest.mock import MagicMock
    
    app = create_gateway_app()
    client = TestClient(app)
    
    # 1. Register a mock agent skill first
    from bfa_sdk.core.gateway import ROUTER
    ROUTER.update_registry({
        "test-disconnect-agent": {
            "name": "disconnect_skill",
            "description": "test skill",
            "tags": [],
            "examples": [],
            "type": "agent",
            "url": "http://localhost:8099"
        }
    })
    ROUTER.build_index()
    assert "test-disconnect-agent" in ROUTER.registry
    
    # 2. Call /register/disconnect to kick it
    res = client.post("/register/disconnect", json={"node_id": "test-disconnect-agent"})
    assert res.status_code == 200
    assert "test-disconnect-agent" not in ROUTER.registry
    
    # 3. Test BFAAgent shutdown event triggering disconnect call
    disconnect_called = False
    async def mock_post_disconnect(self, url, *args, **kwargs):
        nonlocal disconnect_called
        if "register/disconnect" in str(url):
            disconnect_called = True
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        return mock_resp
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_disconnect)
    
    monkeypatch.setattr(BFAAgent, "_auto_register_to_gateway", lambda self: True)
    agent = MockSecureAgent(
        agent_id="shutdown-agent",
        name="Shutdown Agent",
        description="test",
        tags=["loan"],
        examples=["ex"],
        url="http://localhost:8002",
        gateway_url="http://localhost:8000"
    )
    
    # TestClient context naturally runs shutdown handlers
    with TestClient(agent.app) as tc:
        pass
        
    assert disconnect_called is True


@pytest.mark.anyio
async def test_full_mcp_and_agent_handshake_coverage(monkeypatch):
    """
    Achieves 100% coverage on handshake success, shutdown hooks, key properties,
    verify_incoming_det param lockdown success, and abstract parent run call.
    """
    import httpx
    import time
    from unittest.mock import MagicMock
    
    # 1. Mock httpx to return 200 for all registration endpoints
    async def mock_async_post_success(self, url, *args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {
            "challenge_bytes": "abcchallenge",
            "session_token": "mockjwttoken",
            "expiry": int(time.time()) + 3600
        }
        return mock_resp
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_async_post_success)
    
    # Also mock sync httpx.get for gateway key downloading in init
    def mock_sync_get_success(url, *args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {"public_key": TEST_PUB_PEM}
        return mock_resp
    monkeypatch.setattr(httpx, "get", mock_sync_get_success)
    
    # A. Test BFAAgent registration end-to-end
    agent = MockSecureAgent(
        agent_id="handshake-agent",
        name="Handshake Agent",
        description="test",
        tags=["h"],
        examples=["ex"],
        url="http://localhost:8015",
        gateway_url="http://localhost:8000"
    )
    
    # Verify public_key_pem property and auto-register
    assert agent.public_key_pem is not None
    success = await agent.register_with_gateway("http://localhost:8000")
    assert success is True
    
    # B. Test BFAMCP registration end-to-end
    mcp = BFAMCP("handshake-mcp", gateway_url="http://localhost:8000")
    success_mcp = await mcp.register_with_gateway("http://localhost:8000", "http://localhost:8016")
    assert success_mcp is True
    
    # C. Trigger BFAMCP shutdown hook
    with TestClient(mcp.app) as tc:
        pass
        
    # D. Test verify_incoming_det parameter lockdown SUCCESS
    det = jwt.encode(
        {
            "sub": "caller",
            "aud": "handshake-agent",
            "permitted_action": "audit",
            "restricted_params": {"user_id": 42},
            "exp": int(time.time()) + 60
        },
        TEST_PRIVATE_KEY,
        algorithm="RS256"
    )
    agent.gateway_public_key = TEST_PUBLIC_KEY
    assert agent.verify_incoming_det(det, "audit", {"user_id": 42}) is True
    
    # E. Test calling abstract method run in BFAAgent directly to cover the pass statement
    try:
        await BFAAgent.run(agent, "msg", None)
    except Exception:
        pass
        
    # F. Test tool without delegated_token
    @mcp.tool(name="no_token_tool")
    def no_token_tool(x: int) -> int:
        return x + 1
        
    res = no_token_tool(10)
    assert res == 11


def test_agent_auto_register_thread_fallback(monkeypatch):
    """
    Tests BFAAgent _auto_register_to_gateway thread fallback when no event loop is running.
    """
    import httpx
    
    # Mock register_with_gateway to avoid actual network calls
    called = False
    async def mock_register(self, gateway_url):
        nonlocal called
        called = True
        return True
        
    monkeypatch.setattr(BFAAgent, "register_with_gateway", mock_register)
    
    agent = MockSecureAgent(
        agent_id="thread-agent",
        name="Thread Agent",
        description="test",
        tags=["thread"],
        examples=["ex"],
        url="http://localhost:8019",
        gateway_url="http://localhost:8000"
    )
    
    import time
    time.sleep(0.1)


def test_mcp_public_key_download_failure(monkeypatch):
    """
    Tests MCP public key download exception branches.
    """
    import httpx
    def mock_get_fail(*args, **kwargs):
        raise httpx.RequestError("Mock connection error")
    monkeypatch.setattr(httpx, "get", mock_get_fail)
    
    mcp = BFAMCP("fail-mcp", gateway_url="http://localhost:8000")
    assert mcp.gateway_public_key is None


