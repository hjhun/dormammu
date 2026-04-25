# Configuration Resolver Boundaries

작성일: 2026-04-25

## 목적

`AppConfig`는 런타임 값 객체로 유지하고, 해석 책임은 작은 resolver로
분리한다. 기존 public API는 호환성을 위해 `AppConfig` forwarding method로
남긴다.

## 소유 경계

| 영역 | 값 보관 위치 | 해석 책임 |
| --- | --- | --- |
| Package/project/user asset paths | `AppConfig` path fields | `ConfigAssetResolver` |
| Guidance default file discovery | `AppConfig.default_guidance_files` | `ConfigAssetResolver` |
| Runtime path prompt rendering | `AppConfig.runtime_path_prompt()` forwarding | `ConfigRuntimePathResolver` |
| Agent profile lookup | `AppConfig.agent_profiles`, `AppConfig.agents` | `ConfigAgentProfileResolver` |
| Manifest-backed profile loading | `AppConfig` manifest path fields | `ConfigAgentProfileResolver` |
| MCP profile access | `AppConfig.mcp` | `ConfigMcpAccessResolver` |
| MCP visible servers by role | `AppConfig.mcp`, effective profile | `ConfigMcpAccessResolver` plus `ConfigAgentProfileResolver` |

## Compatibility Forwarders

These methods remain on `AppConfig` for callers:

- `resolve_agent_profile()`
- `resolve_mcp_profile_access()`
- `resolve_mcp_servers_for_profile()`
- `resolve_mcp_servers_for_role()`
- `load_agent_manifest_definitions()`
- `runtime_path_prompt()`

They should stay thin. New behavior should be added to the resolver classes
first, then exposed through `AppConfig` only when existing callers need the
compatibility surface.

## Migration Rule

When adding a new configuration option:

- value parsing and persistence belongs in `config.py`
- package/project/user path discovery belongs in `ConfigAssetResolver`
- agent profile selection belongs in `ConfigAgentProfileResolver`
- MCP server visibility belongs in `ConfigMcpAccessResolver`
- rendered runtime path text belongs in `ConfigRuntimePathResolver`

This keeps `AppConfig` focused on carrying resolved values and compatibility
forwarding instead of accumulating new orchestration logic.
