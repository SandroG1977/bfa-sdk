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
