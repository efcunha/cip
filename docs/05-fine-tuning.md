# Fase 6 (opcional) — Fine-tuning de persona

> Só execute esta fase **depois** do RAG validado (score ≥ 4.0). O objetivo é refinar
> **persona, formato e estilo de raciocínio** — NUNCA gravar conhecimento factual.
> Ver ADR 0001 para a justificativa.

## Quando faz sentido
- O RAG puro já responde com precisão, mas o formato/consistência das respostas varia.
- Você quer reduzir a dependência de prompt longo (economia de tokens) fixando a persona.

## Geração de dataset sintético (com curadoria humana)
1. Gere pares pergunta/raciocínio/resposta a partir de cenários reais (custo, IaC,
   segurança, comparação). Use o próprio LLM base para gerar candidatos.
2. **Revise manualmente 30%** e descarte qualquer exemplo com alucinação factual.
3. Meta: 5.000-10.000 exemplos curados, no formato de instrução (Alpaca/ShareGPT).

Exemplo de item (formato instrução):

```json
{
  "instruction": "Analise a infraestrutura e sugira melhorias de custo.",
  "input": "10 instâncias EC2 m5.large 24/7 em us-east-1, uso médio de CPU 15%.",
  "output": "Achado (High, FinOps): subutilização... Recomendação: rightsizing para \
t4g/m7g (Graviton) ou Savings Plans. Sempre confirme preços via Cost Explorer. \
[aws, ec2, Well-Architected: Cost Optimization]"
}
```

## Treino (LoRA/QLoRA)
- Base sugerida: Llama 3.3 70B Instruct (ou 8B para protótipo barato).
- Técnica: QLoRA (4-bit) com PEFT + TRL `SFTTrainer`.
- Hiperparâmetros de partida: `r=64`, `alpha=128`, `dropout=0.05`, 3 épocas, lr=2e-4, bf16.
- Custo estimado (8B): ~$50-200. (70B): ~$500-1500 em A100.

```python
# treino (pseudo — usar TRL/axolotl)
from peft import LoraConfig
from trl import SFTTrainer

lora = LoraConfig(r=64, lora_alpha=128, lora_dropout=0.05,
                  target_modules=["q_proj","k_proj","v_proj","o_proj"],
                  task_type="CAUSAL_LM")
# SFTTrainer(model=..., train_dataset=..., peft_config=lora, args=...).train()
```

## Avaliação pós-treino
- Rode a **mesma suíte de 60 casos** (eval/) antes e depois.
- Critério: melhora em formato/consistência **sem regressão factual**.
- Se houver regressão factual, reverta — o RAG continua sendo a fonte de verdade.

## Servindo o modelo fine-tunado
- Merge do adapter LoRA + deploy self-hosted (vLLM/TGI) OU endpoint gerenciado
  (SageMaker / Vertex AI / Azure ML).
- Ajuste `LLM_PROVIDER=local` e aponte para o endpoint OpenAI-compatible.
