# v0.3.0 build notes

- Added LOCAL / HYBRID / CLOUD AI backends.
- LOCAL uses LM Studio OpenAI-compatible Chat Completions via `OpenAIChatCompletionsModel`.
- LOCAL does not require or read the OpenAI API key.
- Added persisted `data/ai_config.json`.
- Added LM Studio `/v1/models` health/model discovery.
- Added Yahoo Finance benchmark research packet for LOCAL macro analysis.
- Added bounded local product catalog; LOCAL Product Agent may not invent tickers outside the catalog/user holdings.
- LOCAL agents run sequentially to reduce memory pressure on 16GB machines.
- HYBRID limits OpenAI usage to Macro/Product/Fact Check; other LLM roles run local.
- Added memory warning with psutil.
- Added friendly quota/LM Studio errors.
- Added `LOCAL_AI_SETUP.bat` for LM Studio/Qwen3 8B setup assistance.
- Kept deterministic Python portfolio construction/quant validation and existing hard guardrails.
