import { useAppState } from "./StateContext";
import AppLayout from "./Layout";
import ChatBox from "./components/ChatBox";
import PromptSuggestions from "./components/PromptSuggestions";

export default function ChatPage() {
    const { messages, setMessages, loading, setLoading, updateState, state } =
        useAppState();

    async function sendMessage(message) {
        if (!message.trim()) return;

        const userMessage = {
            id: crypto.randomUUID(),
            role: "user",
            content: message,
        };
        setMessages((prev) => [...prev, userMessage]);
        setLoading(true);

        // Generamos un session_id dinámico o usamos uno existente
        const session_id = state.session_id || crypto.randomUUID();
        // Guardamos el session_id en el estado si no existía
        if (!state.session_id) {
            updateState({ session_id });
        }

        try {
            // 1. Fetch FAISS Semantic Routing Resolution info (in parallel)
            let routingTag = "";
            try {
                const resolveRes = await fetch(`http://localhost:8000/resolve?query=${encodeURIComponent(message)}`);
                if (resolveRes.ok) {
                    const resolveData = await resolveRes.json();
                    const best = resolveData.best;
                    if (best) {
                        routingTag = `\n\n---\n*🔌 Enrutado semánticamente por **IRC-A** a **${best.skill}** (${best.type === 'agent' ? 'Agente A2A' : 'MCP Tool'}) con **${(best.confidence * 100).toFixed(1)}%** de confianza.*`;
                    }
                }
            } catch (err) {
                console.warn("Could not fetch routing resolution info:", err);
            }

            // 2. Invoke the routed microservice via BFA Gateway
            const response = await fetch(`http://localhost:8000/invoke?query=${encodeURIComponent(message)}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "agent.execute",
                    params: {
                        user_input: {
                            text: message
                        }
                    },
                    id: 1
                }),
            });

            if (!response.ok) {
                throw new Error("Failed to invoke BFA Gateway");
            }

            const data = await response.json();
            
            // Extract response text from A2A JSON-RPC format
            let textResponse = "";
            if (data.error) {
                textResponse = `⚠️ **Error del Agente (${data.error.code}):** ${data.error.message}`;
            } else {
                textResponse = data?.result?.output?.text || "Sin respuesta estructurada del agente.";
            }

            const finalMessage = textResponse + routingTag;
            const assistantId = crypto.randomUUID();

            setMessages((prev) => [
                ...prev,
                {
                    id: assistantId,
                    role: "assistant",
                    content: finalMessage,
                },
            ]);

            // Actualizamos las respuestas del estado compartido para que el visualizador de datos las procese
            updateState({
                responses: [textResponse]
            });

        } catch (err) {
            console.error("Error al enviar mensaje:", err);
            setMessages((prev) => [
                ...prev,
                {
                    id: crypto.randomUUID(),
                    role: "assistant",
                    content: "Error de conexión con el BFA Gateway. Por favor, verificá que el servidor Gateway (Puerto 8000) esté corriendo.",
                },
            ]);
        } finally {
            setLoading(false);
        }
    }

    return (
        <AppLayout>
        {messages.length === 0 ? (
            <PromptSuggestions onSelect={sendMessage} />
        ) : (
            <ChatBox
            messages={messages}
            setMessages={setMessages}
            onSend={sendMessage}
            loading={loading}
            />
        )}
        </AppLayout>
    );
}