# Publish status

**Complete.** Runtime modules on `main`:

- gates · loop · mcp_tools · mcp_server · selftest
- pin · state · audit · types · agents · cli
- docs · LICENSE · CAPABILITIES · examples

```bash
git clone https://github.com/ZuluYokohama/maxop-mcp-harness.git
cd maxop-mcp-harness
export PYTHONPATH=src
python -m maxop_harness.cli selftest
```
