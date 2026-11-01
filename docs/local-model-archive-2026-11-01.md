# Unused local generation-model archive

Archive destination: `E:\JurisAI\archives\ollama-unused-20261101`.
The archive script is `.local/archive-unused-models.ps1`. Without `-Execute`
it only validates the plan. With `-Execute` it copies each selected model's
manifest and referenced blobs, verifies SHA-256 against the manifest, and only
then removes that exact model through Ollama's deletion API. Shared blobs are
managed by Ollama rather than deleted manually.

Selected models: `gemma4:12b-it-qat`, `qwen3.5:4b`, `deepseek-r1:8b`,
`llama3:latest`, `llama3-8b-backup:latest`.

Protected models: `nomic-embed-text:latest`, `bge-m3:latest`,
`qwen3-embedding:0.6b`. PostgreSQL/Docker and application configuration are
outside the operation's scope.

## Restore if needed

The archive contains the standard `models/blobs` and `models/manifests`
directory layout. Stop Ollama before restoring. Copy the archived blobs and
manifests back under `C:\Users\enure\.ollama\models`, preserving their paths.
For existing files, verify matching hashes before deciding whether to skip;
do not blindly overwrite different files. Restart Ollama and confirm the
restored model with `/api/tags`. This restores weights without downloading
them again; it does not switch the application's cloud-provider setting.

Do not delete the HDD archive unless these models are no longer needed or
another verified backup exists. Execution progress, not this document alone,
determines which models have completed archival.
