# API Contract Checker

Validate `docs/development/openapi/openapi.yaml` with a YAML parser before development. Require OpenAPI 3.x, `info.title`, `info.version`, at least one path, HTTP operations, responses, and resolvable internal or local-file `$ref` values. Pass `--baseline previous-openapi.yaml` to block removed paths or methods. This gate does not judge API business semantics or every form of schema compatibility.
