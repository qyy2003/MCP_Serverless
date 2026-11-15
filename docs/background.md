# Project background (original proposal notes)

The notes that started the project, kept as written. The reply at the end set the scope:
serverless deployment of MCP tools, not agent sandboxes.

```text
Agentic AI tools. -Justin
Yes, it’s good. 
Providers already host MCP servers on serverless platforms:
AWS: MCP servers on Lambda, plus AgentCore Gateway, which turns Lambda functions into MCP tools.
Cloudflare: a stateless createMcpHandler on Workers.
Vercel: mcp-handler, described as built for “long idle times, quick message bursts”.
Microsoft: an Azure Functions MCP extension.
Also, Code sandboxes run on serverless technology. E2B uses Firecracker, the same microVM as Lambda. AWS launched Lambda MicroVMs in June 2026 specifically for running AI-generated code.
But NO EXISTING Benchmark can currently measure & compare then, Below is what exist today:
Sandbox “benchmarks” are vendor blog posts. A widely circulated 2026 comparison of seven sandbox providers lists cold starts of “~25 ms” to “2–3 s”, with no repetitions, regions, harness or raw data.
MCP benchmarks measure the LLM, not the infrastructure. MCP-Bench, MCP-Universe and LiveMCPBench score how well models use tools. They say nothing about latency or cost.
Systems papers bring their own workloads. TrEnv-X and AgentSysBench each use their own setup, so their results can’t be compared.
We could possibly work on the following questions
How does the tool call time split between startup, protocol round trips, network waits and compute
How does the tool call actually interact with the LLM API call, will they be overlapped or not
What’s the time difference between cold start and warm one, how often does it trigger the cold one
Could we predict the bill in advance/ are the current billing model good or reasonable enough
Things to build
[MCP benchmark] Test MCP-Bench, MCP-Universe and LiveMCPBench server sets on the serverless setting
[Sandbox] Test public agent trajectories, such as OpenHands SWE trajectories on serverless setting
Define our own benchmark
Overall, personally I think it’s an emerging and interesting topic


reply:

For agentic workloads, I would recommend focusing on the serverless deployment aspect; there is already a semester project at SPCL covering agentic sandboxes. Characterizing tool performance on serverless platforms, including the metrics you mentioned, would be an interesting and useful direction.
```
