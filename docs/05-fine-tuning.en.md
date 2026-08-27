# Phase 6 (optional) — Persona fine-tuning

> Only run this phase **after** the RAG is validated (score ≥ 4.0). The goal is to refine
> **persona, format, and reasoning style** — NEVER to record factual knowledge.
> See ADR 0001 for the rationale.

## When it makes sense
- Pure RAG already answers accurately, but the format/consistency of responses varies.
- You want to reduce the dependence on long prompts (token savings) by fixing the persona.

## Synthetic dataset generation (with human curation)
1. Generate question/reasoning/answer pairs from real scenarios (cost, IaC,
   security, comparison). Use the base LLM itself to generate candidates.
2. **Manually review 30%** and discard any example with factual hallucination.
3. Target: 5,000-10,000 curated examples, in instruction format (Alpaca/ShareGPT).

Example item (instruction format):

```json
{
  "instruction": "Analyze the infrastructure and suggest cost improvements.",
  "input": "10 EC2 m5.large instances 24/7 in us-east-1, average CPU usage 15%.",
  "output": "Finding (High, FinOps): underutilization... Recommendation: rightsizing to \
t4g/m7g (Graviton) or Savings Plans. Always confirm prices via Cost Explorer. \
[aws, ec2, Well-Architected: Cost Optimization]"
}
```

## Training (LoRA/QLoRA)
- Suggested base: Llama 3.3 70B Instruct (or 8B for a cheap prototype).
- Technique: QLoRA (4-bit) with PEFT + TRL `SFTTrainer`.
- Starting hyperparameters: `r=64`, `alpha=128`, `dropout=0.05`, 3 epochs, lr=2e-4, bf16.
- Estimated cost (8B): ~$50-200. (70B): ~$500-1500 on A100.

```python
# training (pseudo — use TRL/axolotl)
from peft import LoraConfig
from trl import SFTTrainer

lora = LoraConfig(r=64, lora_alpha=128, lora_dropout=0.05,
                  target_modules=["q_proj","k_proj","v_proj","o_proj"],
                  task_type="CAUSAL_LM")
# SFTTrainer(model=..., train_dataset=..., peft_config=lora, args=...).train()
```

## Post-training evaluation
- Run the **same suite of 60 cases** (eval/) before and after.
- Criterion: improvement in format/consistency **without factual regression**.
- If there is factual regression, revert — the RAG remains the source of truth.

## Serving the fine-tuned model
- Merge the LoRA adapter + self-hosted deployment (vLLM/TGI) OR a managed endpoint
  (SageMaker / Vertex AI / Azure ML).
- Set `LLM_PROVIDER=local` and point to the OpenAI-compatible endpoint.
