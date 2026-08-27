"""ReAct (Reasoning + Acting) + function-calling mode para o orchestrator.

Implementa o loop ReAct mencionado no roadmap (Fase 4):
- LLM raciocina sobre qual tool chamar
- Tools disponíveis: query_rag, invoke_specialist, get_live_data, inspect_iac
- Loop: Thought → Action → Observation → ... → Final Answer
- Max iterações para prevenir loops infinitos

Diferente do modo estático atual:
- Estático: roteamento heurístico → executa 1-3 specialists em paralelo → fim
- ReAct: LLM decide steps → pode chamar múltiplas tools em sequência → raciocínio sobre resultado

Benefícios:
- Queries complexas multi-step (ex: "Analise meu ambiente AWS e sugira plano de economia")
- Combinar RAG + tools + inspection de forma adaptativa
- Raciocínio transparente (chain-of-thought)

Quando usar:
- ReAct mode: queries abertas, multi-step, requer raciocínio
- Static mode (default): queries diretas, baixa latência

Design:
- Usa prompt estruturado com function definitions
- Parser simples de JSON retornado pelo LLM
- Fallback gracioso para modo estático se ReAct falhar
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from cip.agents.models import AnalysisPlan, Finding, Intent
from cip.config import CloudName
from cip.logging import get_logger
from cip.rag.engine import RagEngine, get_engine

log = get_logger(__name__)


# SpecialistResult is defined here to avoid circular import with orchestrator
@dataclass
class SpecialistResult:
    """Resultado de execução de um especialista (réplica para evitar import circular)."""

    def __init__(
        self, name: str, answer: str, sources: list, latency_ms: int
    ) -> None:
        self.name = name
        self.answer = answer
        self.sources = sources
        self.latency_ms = latency_ms


# ─────────────────────────────────────────────────────────────────────────
# Tool definitions
# ─────────────────────────────────────────────────────────────────────────


class ToolName(str, Enum):
    """Tools disponíveis para o LLM chamar."""

    QUERY_RAG = "query_rag"  # busca no vector store
    INVOKE_SPECIALIST = "invoke_specialist"  # dispara um especialista
    GET_LIVE_DATA = "get_live_data"  # dados ao vivo de uma cloud
    INSPECT_IAC = "inspect_iac"  # roda Inspection Engine


# Schema das tools (formato OpenAI function calling-like)
TOOL_SCHEMA: list[dict[str, Any]] = [
    {
        "name": ToolName.QUERY_RAG,
        "description": "Busca informação na base de conhecimento oficial (RAG). Use para fatos sobre cloud, well-architected, security, FinOps, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Pergunta refinada para RAG"},
                "cloud": {"type": "string", "enum": ["aws", "gcp", "azure"], "description": "Filtro de cloud opcional"},
                "service": {"type": "string", "description": "Filtro de serviço opcional (ex: ec2, s3)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": ToolName.INVOKE_SPECIALIST,
        "description": "Dispara um especialista (aws/gcp/azure/finops/security/sre/k8s/tf) com pergunta focada",
        "parameters": {
            "type": "object",
            "properties": {
                "specialist": {
                    "type": "string",
                    "enum": ["aws", "gcp", "azure", "finops", "security", "sre", "kubernetes", "terraform"],
                },
                "query": {"type": "string", "description": "Pergunta focada para o especialista"},
            },
            "required": ["specialist", "query"],
        },
    },
    {
        "name": ToolName.GET_LIVE_DATA,
        "description": "Coleta dados ao vivo de uma cloud (custo, inventory, recommendations). Requer credenciais AWS/Azure/GCP.",
        "parameters": {
            "type": "object",
            "properties": {
                "cloud": {"type": "string", "enum": ["aws", "gcp", "azure"]},
            },
            "required": ["cloud"],
        },
    },
    {
        "name": ToolName.INSPECT_IAC,
        "description": "Inspeciona código Terraform ou manifesto Kubernetes para findings de segurança/custo/operational",
        "parameters": {
            "type": "object",
            "properties": {
                "iac_payload": {"type": "string", "description": "Conteúdo do .tf ou YAML"},
            },
            "required": ["iac_payload"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────
# ReAct Step + Result
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class ReActStep:
    """Uma iteração do loop ReAct."""

    step_number: int
    thought: str
    action: str  # tool name
    action_input: dict[str, Any]
    observation: str
    latency_ms: int = 0
    error: str | None = None


@dataclass
class ReActResult:
    """Resultado completo do loop ReAct."""

    question: str
    steps: list[ReActStep] = field(default_factory=list)
    final_answer: str = ""
    total_latency_ms: int = 0
    tool_calls: list[str] = field(default_factory=list)  # tool names called
    grounding_ok: bool = False
    error: str | None = None


# ─────────────────────────────────────────────────────────────────────────
# ReAct Orchestrator
# ─────────────────────────────────────────────────────────────────────────


# Regex para extrair JSON do output do LLM
JSON_BLOCK_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


REACT_SYSTEM_PROMPT = f"""\
Você é um engenheiro de cloud sênior usando o padrão ReAct (Reasoning + Acting).

Tools disponíveis (chame-as em sequência até ter info suficiente para responder):
{json.dumps(TOOL_SCHEMA, indent=2, ensure_ascii=False)}

Sempre responda em JSON com este formato:
{{
  "thought": "<seu raciocínio sobre o que fazer agora>",
  "action": "<nome_da_tool_ou_final_answer>",
  "action_input": {{<argumentos_da_tool>}} | {{}},
  "is_final": <true|false>
}}

Quando tiver informação suficiente, use:
{{
  "thought": "Tenho info suficiente para responder",
  "action": "final_answer",
  "action_input": {{"answer": "<resposta completa em pt-BR com citações>"}},
  "is_final": true
}}
"""


class ReActOrchestrator:
    """Implementa loop ReAct com function calling."""

    MAX_STEPS = 5
    STEP_TIMEOUT_S = 30.0

    def __init__(self, engine: RagEngine | None = None) -> None:
        self._engine = engine or get_engine()
        self._settings_engine = None  # lazy

    async def run(
        self,
        question: str,
        plan: AnalysisPlan,
        iac_payload: str | None = None,
    ) -> ReActResult:
        """Executa loop ReAct: Thought → Action → Observation → ... → Final Answer.

        Args:
            question: pergunta original do usuário
            plan: plano gerado pelo classifier (para contexto)
            iac_payload: se houver, inspection inicial disponível

        Returns:
            ReActResult com steps + final_answer
        """
        result = ReActResult(question=question)
        started = time.perf_counter()

        # Histórico de actions + observations
        history: list[dict[str, Any]] = []
        sources_seen: set[str] = set()

        # Se há payload IaC, faz inspection inicial automaticamente
        if iac_payload:
            inspection_result = await self._execute_tool(
                ToolName.INSPECT_IAC,
                {"iac_payload": iac_payload},
            )
            history.append({
                "step": 1,
                "thought": "Inspecionar IaC fornecido para identificar problemas",
                "action": ToolName.INSPECT_IAC,
                "observation": inspection_result,
            })
            sources_seen.add(inspection_result[:100])  # sample

        # Loop ReAct
        for step_num in range(1, self.MAX_STEPS + 1):
            try:
                # 1. LLM gera thought + action
                llm_output = await self._generate_next_step(
                    question, plan, history
                )

                # 2. Parse da resposta
                parsed = self._parse_llm_output(llm_output)
                if not parsed:
                    log.warning("react_parse_failed", step=step_num, output=llm_output[:200])
                    # Tenta continuar com fallback
                    if step_num == 1:
                        # Primeira step falhou, usa modo estático como fallback
                        return await self._fallback_to_static(
                            result, question, plan, iac_payload, history, started
                        )
                    break

                thought = parsed.get("thought", "")
                action = parsed.get("action", "")
                action_input = parsed.get("action_input", {}) or {}
                is_final = parsed.get("is_final", False)

                # 3. Se for final, termina
                if is_final or action == "final_answer":
                    result.final_answer = action_input.get("answer", llm_output)
                    result.grounding_ok = bool(sources_seen)
                    log.info("react_final", steps=step_num - 1)
                    break

                # 4. Executa a tool
                observation = await self._execute_tool(action, action_input)

                # 5. Adiciona step ao resultado
                step = ReActStep(
                    step_number=step_num,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=observation[:500],  # limita observation
                )
                result.steps.append(step)
                result.tool_calls.append(action)
                if action == ToolName.QUERY_RAG:
                    sources_seen.add(observation[:100])

                # 6. Adiciona ao histórico
                history.append({
                    "step": step_num,
                    "thought": thought,
                    "action": action,
                    "action_input": action_input,
                    "observation": observation,
                })

            except Exception as exc:  # noqa: BLE001
                log.warning("react_step_error", step=step_num, error=str(exc))
                result.error = str(exc)
                # Em erro, tenta fallback estático
                return await self._fallback_to_static(
                    result, question, plan, iac_payload, history, started
                )

        # Se saiu do loop sem final_answer
        if not result.final_answer:
            result.final_answer = (
                f"Loop ReAct terminou sem final_answer após {len(result.steps)} steps. "
                f"Tools chamadas: {', '.join(result.tool_calls) or 'nenhuma'}. "
                f"Última observation: {result.steps[-1].observation[:200] if result.steps else 'N/A'}"
            )

        result.total_latency_ms = int((time.perf_counter() - started) * 1000)
        result.grounding_ok = result.grounding_ok or bool(sources_seen)
        return result

    async def _generate_next_step(
        self,
        question: str,
        plan: AnalysisPlan,
        history: list[dict[str, Any]],
    ) -> str:
        """Chama LLM para gerar próximo thought + action."""
        from cip.rag.llm import build_llm

        if self._settings_engine is None:
            self._settings_engine = build_llm()

        # Monta prompt com histórico
        history_str = ""
        for h in history:
            history_str += f"\nStep {h['step']}:\n  Thought: {h['thought']}\n"
            history_str += f"  Action: {h['action']}\n"
            history_str += f"  Observation: {h['observation'][:300]}...\n"

        prompt = (
            f"Pergunta original: {question}\n\n"
            f"Plano: intent={plan.intent.value}, clouds={plan.clouds}, "
            f"specialists={plan.specialists}\n\n"
            f"Histórico:\n{history_str if history_str else '(vazio)'}\n\n"
            "Qual é o próximo passo? Responda em JSON conforme schema."
        )

        try:
            resp = await self._settings_engine.acomplete(
                prompt=prompt,
                system_prompt=REACT_SYSTEM_PROMPT,
            )
            return str(resp)
        except Exception as exc:  # noqa: BLE001
            log.warning("react_llm_error", error=str(exc))
            # Fallback: retorna um JSON que finaliza
            return json.dumps({
                "thought": "LLM error, finalizando",
                "action": "final_answer",
                "action_input": {
                    "answer": f"Não foi possível raciocinar: {exc}",
                },
                "is_final": True,
            })

    def _parse_llm_output(self, output: str) -> dict[str, Any] | None:
        """Extrai JSON do output do LLM."""
        # Tenta parse direto primeiro
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass

        # Tenta encontrar bloco JSON
        match = JSON_BLOCK_RE.search(output)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    async def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Executa tool e retorna observation (string).

        Async porque algumas tools (query_rag, invoke_specialist) fazem RAG
        assíncrono. Rodando dentro de um loop ReAct async, awaitamos
        diretamente em vez de asyncio.run() — que dispara
        "cannot be called from a running event loop" e vaza coroutines
        nunca awaitadas.
        """
        try:
            if tool_name == ToolName.QUERY_RAG:
                return await self._tool_query_rag(arguments)
            elif tool_name == ToolName.INVOKE_SPECIALIST:
                return await self._tool_invoke_specialist(arguments)
            elif tool_name == ToolName.GET_LIVE_DATA:
                return self._tool_get_live_data(arguments)
            elif tool_name == ToolName.INSPECT_IAC:
                return self._tool_inspect_iac(arguments)
            else:
                return f"[Tool {tool_name} não reconhecida]"
        except Exception as exc:  # noqa: BLE001
            log.warning("react_tool_failed", tool=tool_name, error=str(exc))
            return f"[Tool {tool_name} falhou: {exc}]"

    async def _tool_query_rag(self, args: dict[str, Any]) -> str:
        """Tool: query_rag (busca no vector store)."""
        query = args.get("query", "")
        cloud = args.get("cloud")
        r = await self._engine.query(query, cloud=cloud)
        return r.answer

    async def _tool_invoke_specialist(self, args: dict[str, Any]) -> str:
        """Tool: invoke_specialist."""
        from cip.prompts.specialists import SPECIALIST_PROMPTS

        specialist = args.get("specialist", "general")
        query = args.get("query", "")
        spec_prompt = SPECIALIST_PROMPTS.get(specialist, "")

        augmented = f"{query}\n\n[CONTEXTO {specialist}]:\n{spec_prompt}"

        r = await self._engine.query(augmented)
        return r.answer

    def _tool_get_live_data(self, args: dict[str, Any]) -> str:
        """Tool: get_live_data (dados ao vivo de cloud)."""
        from cip.tools.registry import collect_cost_signals

        cloud = args.get("cloud", "aws")
        try:
            signals, _ = collect_cost_signals([cloud])
            return signals or f"[Sem dados ao vivo para {cloud}]"
        except Exception as exc:  # noqa: BLE001
            return f"[Erro coletando dados de {cloud}: {exc}]"

    def _tool_inspect_iac(self, args: dict[str, Any]) -> str:
        """Tool: inspect_iac."""
        from cip.inspection.engine import inspect_payload

        payload = args.get("iac_payload", "")
        findings = inspect_payload(payload)
        if not findings:
            return "[Inspection: nenhum finding]"
        return "\n".join(
            f"- [{f.severity}] {f.title}: {f.recommendation}" for f in findings
        )

    async def _fallback_to_static(
        self,
        result: ReActResult,
        question: str,
        plan: AnalysisPlan,
        iac_payload: str | None,
        history: list[dict[str, Any]],
        started: float,
    ) -> ReActResult:
        """Fallback: usa orchestrator estático."""
        from cip.agents.orchestrator import Orchestrator

        log.info("react_fallback_static", steps=len(result.steps))

        # Executa orchestrator estático (apenas uma vez). Já rodamos dentro de
        # um loop ReAct async, então awaitamos diretamente (sem asyncio.run).
        static_orch = Orchestrator(engine=self._engine)
        try:
            static_result = await static_orch.handle(
                question=question,
                cloud=plan.clouds[0] if plan.clouds else None,
                iac_payload=iac_payload,
            )
            result.final_answer = static_result.summary
            result.tool_calls.append("[static-fallback]")
        except Exception as exc:  # noqa: BLE001
            result.final_answer = f"Fallback estático falhou: {exc}"
            result.error = str(exc)

        result.total_latency_ms = int((time.perf_counter() - started) * 1000)
        return result
