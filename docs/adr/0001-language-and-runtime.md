# ADR 0001: Language and runtime

**Choice:** Python (>=3.10), including the CLI, as a single-language codebase.

**Why:** The model provider abstraction (Anthropic/OpenAI/Google) is best served
by Python's mature, first-party SDKs and the surrounding LLM-agent ecosystem
(eval harnesses, structured-output libraries, tracing), the evaluation
framework is a data-analysis problem Python's tooling fits well, and code
graph parsing can lean on `tree-sitter`'s Python bindings. Go was considered
for the CLI specifically, for its single static-binary distribution story, but
that advantage doesn't apply here since the project already ships as a Docker
image — splitting the CLI into a second language would instead force an RPC
or subprocess boundary between `cli/` and the in-process orchestration
(`agent/`, `providers/`, `context/`, etc.) for no corresponding benefit.
