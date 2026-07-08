// RegistryPage.jsx
import React, { useState, useEffect } from "react";
import AppLayout from "./Layout";
import { useAppState } from "./StateContext";

export default function RegistryPage() {
    const { updateState } = useAppState();
    const [skills, setSkills] = useState({});
    const [loading, setLoading] = useState(false);
    const [registerUrl, setRegisterUrl] = useState("");
    const [registerType, setRegisterType] = useState("agent");
    const [message, setMessage] = useState({ text: "", type: "" });

    // Fetch active BFA gateway registry
    async function fetchRegistry() {
        setLoading(true);
        try {
            const response = await fetch("http://localhost:8000/skills");
            if (response.ok) {
                const data = await response.json();
                setSkills(data);
            }
        } catch (err) {
            console.error("Error fetching skills registry:", err);
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        fetchRegistry();
    }, []);

    // Handle new self-registration
    async function handleRegister(e) {
        e.preventDefault();
        if (!registerUrl.trim()) return;

        setMessage({ text: "Conectando al servidor IRC-A...", type: "info" });
        try {
            const endpoint = registerType === "agent" ? "register/agent" : "register/mcp";
            const response = await fetch(`http://localhost:8000/${endpoint}?url=${encodeURIComponent(registerUrl.trim())}`, {
                method: "POST"
            });

            const data = await response.json();
            if (response.ok) {
                setMessage({ text: `¡Registro exitoso! Servidor indexado en FAISS.`, type: "success" });
                setRegisterUrl("");
                fetchRegistry(); // Reload active list
            } else {
                setMessage({ text: `Error de registro: ${data.detail || "URL no válida o inalcanzable"}`, type: "error" });
            }
        } catch (err) {
            console.error("Registration error:", err);
            setMessage({ text: "Error de red al conectar con el Gateway central de BFA.", type: "error" });
        }
    }

    const agentsList = Object.entries(skills).filter(([_, item]) => item.type === "agent");
    const toolsList = Object.entries(skills).filter(([_, item]) => item.type === "tool");

    return (
        <AppLayout>
            <div className="p-6 flex-1 overflow-auto flex flex-col gap-6 bg-gray-900 font-sans">
                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-gray-800 pb-4">
                    <div>
                        <h1 className="text-3xl font-bold text-white flex items-center gap-2">
                            <span>🔌</span> Nodo Central IRC-A (BFA Gateway)
                        </h1>
                        <p className="text-gray-400 text-sm mt-1">
                            Directorio y Ruteador Semántico de Agentes Financieros y Microservicios MCP en Tiempo Real.
                        </p>
                    </div>
                    <button 
                        onClick={fetchRegistry}
                        className="mt-4 md:mt-0 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition text-sm font-semibold border border-gray-700 flex items-center gap-2"
                    >
                        <span>🔄</span> Actualizar Directorio
                    </button>
                </div>

                {/* Main section: Form + Stats */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Register Form */}
                    <div className="lg:col-span-2 bg-gray-800 p-6 rounded-2xl border border-gray-700 shadow-xl flex flex-col justify-between">
                        <form onSubmit={handleRegister} className="flex flex-col gap-4">
                            <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                                <span>⚡</span> Conectar Nuevo Agente / MCP en Caliente
                            </h2>
                            <p className="text-gray-400 text-xs">
                                Ingresa el endpoint del microservicio que deseas acoplar a la red. El servidor extraerá sus metadatos e indexará sus capacidades dinámicamente en FAISS.
                            </p>

                            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-2">
                                <div className="md:col-span-3">
                                    <label className="block text-xs font-semibold text-gray-400 mb-1">URL del Endpoint</label>
                                    <input 
                                        type="url" 
                                        placeholder="http://127.0.0.1:8004"
                                        value={registerUrl}
                                        onChange={(e) => setRegisterUrl(e.target.value)}
                                        className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500 text-sm"
                                        required
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-gray-400 mb-1">Tipo de Servicio</label>
                                    <select 
                                        value={registerType}
                                        onChange={(e) => setRegisterType(e.target.value)}
                                        className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500 text-sm h-[38px]"
                                    >
                                        <option value="agent">Agente (A2A)</option>
                                        <option value="mcp">Servidor MCP</option>
                                    </select>
                                </div>
                            </div>

                            <button 
                                type="submit"
                                className="w-full md:w-auto self-end px-6 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white rounded-lg font-bold text-sm shadow-lg transition mt-2"
                            >
                                Registrar y Re-Indexar
                            </button>
                        </form>

                        {/* Status Message */}
                        {message.text && (
                            <div className={`mt-4 p-3 rounded-lg text-xs font-semibold flex items-center gap-2 ${
                                message.type === "success" ? "bg-green-900/50 border border-green-800 text-green-300" :
                                message.type === "error" ? "bg-red-900/50 border border-red-800 text-red-300" :
                                "bg-blue-900/50 border border-blue-800 text-blue-300"
                            }`}>
                                <span>{message.type === "success" ? "✅" : message.type === "error" ? "❌" : "ℹ️"}</span>
                                {message.text}
                            </div>
                        )}
                    </div>

                    {/* Stats Card */}
                    <div className="bg-gray-800 p-6 rounded-2xl border border-gray-700 shadow-xl flex flex-col gap-4">
                        <h2 className="text-lg font-semibold text-white">📊 Métricas del Servidor</h2>
                        <div className="grid grid-cols-2 gap-4">
                            <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 text-center">
                                <span className="text-2xl font-bold text-blue-400">{agentsList.length}</span>
                                <p className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mt-1">Agentes Activos</p>
                            </div>
                            <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 text-center">
                                <span className="text-2xl font-bold text-indigo-400">{toolsList.length}</span>
                                <p className="text-gray-400 text-[10px] uppercase font-bold tracking-wider mt-1">Tools Indexadas</p>
                            </div>
                        </div>
                        <div className="bg-gray-900 p-3 rounded-xl border border-gray-800 text-xs text-gray-400">
                            <div className="flex justify-between py-1 border-b border-gray-800">
                                <span>Enrutador Semántico:</span>
                                <span className="text-green-400 font-semibold">FAISS CPU</span>
                            </div>
                            <div className="flex justify-between py-1 mt-1">
                                <span>Estado del Nodo:</span>
                                <span className="text-green-400 font-semibold">ONLINE</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Connected Agents & Tools Lists */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
                    {/* Agents list */}
                    <div className="flex flex-col gap-4">
                        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                            <span>🤖</span> Agentes Conectados ({agentsList.length})
                        </h2>
                        {agentsList.length === 0 ? (
                            <div className="bg-gray-800 border border-gray-850 text-gray-500 rounded-2xl p-6 text-center text-sm border-dashed">
                                Ningún agente registrado dinámicamente.
                            </div>
                        ) : (
                            <div className="flex flex-col gap-3">
                                {agentsList.map(([id, item]) => (
                                    <div key={id} className="bg-gray-800 p-4 rounded-2xl border border-gray-700 shadow-md hover:scale-[1.01] transition">
                                        <div className="flex justify-between items-start">
                                            <h3 className="font-bold text-white text-base">{item.name}</h3>
                                            <span className="bg-blue-900/60 text-blue-300 border border-blue-800 text-[10px] px-2 py-0.5 rounded-full uppercase font-bold">
                                                A2A Agent
                                            </span>
                                        </div>
                                        <p className="text-gray-300 text-xs mt-1.5">{item.description}</p>
                                        <div className="flex flex-wrap gap-1 mt-3">
                                            {item.tags.map((tag) => (
                                                <span key={tag} className="bg-gray-900 text-gray-400 text-[10px] px-2 py-0.5 rounded-md font-semibold">
                                                    #{tag}
                                                </span>
                                            ))}
                                        </div>
                                        <div className="text-[10px] text-gray-500 mt-3 border-t border-gray-700/50 pt-2 flex justify-between">
                                            <span>ENDPOINT:</span>
                                            <span className="font-mono text-gray-400 select-all">{item.url}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Tools list */}
                    <div className="flex flex-col gap-4">
                        <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                            <span>🛠️</span> Herramientas MCP Indexadas ({toolsList.length})
                        </h2>
                        {toolsList.length === 0 ? (
                            <div className="bg-gray-800 border border-gray-850 text-gray-500 rounded-2xl p-6 text-center text-sm border-dashed">
                                Ningún servidor MCP registrado dinámicamente.
                            </div>
                        ) : (
                            <div className="flex flex-col gap-3">
                                {toolsList.map(([name, item]) => (
                                    <div key={name} className="bg-gray-800 p-4 rounded-2xl border border-gray-700 shadow-md hover:scale-[1.01] transition">
                                        <div className="flex justify-between items-start">
                                            <h3 className="font-bold text-white text-base font-mono">{name}</h3>
                                            <span className="bg-indigo-900/60 text-indigo-300 border border-indigo-800 text-[10px] px-2 py-0.5 rounded-full uppercase font-bold">
                                                MCP Tool
                                            </span>
                                        </div>
                                        <p className="text-gray-300 text-xs mt-1.5">{item.description}</p>
                                        <div className="flex flex-wrap gap-1 mt-3">
                                            {item.tags && item.tags.map((tag) => (
                                                <span key={tag} className="bg-gray-900 text-gray-400 text-[10px] px-2 py-0.5 rounded-md font-semibold">
                                                    #{tag}
                                                </span>
                                            ))}
                                        </div>
                                        <div className="text-[10px] text-gray-500 mt-3 border-t border-gray-700/50 pt-2 flex justify-between">
                                            <span>MCP SERVER:</span>
                                            <span className="font-mono text-gray-400 select-all">{item.server_url}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </AppLayout>
    );
}
