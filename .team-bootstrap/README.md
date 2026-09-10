# Team runtime bundle

`STEM-SCI-runtime-v1.zip` is stored with Git LFS. It contains the shared runtime snapshot used for the team handoff:

- backend and root `.stem_sci` databases and project files;
- uploaded project materials and generated artifacts;
- repository-local retrieval data under `data/local`;
- the complete `cgt_blind_output_rerun_046` acceptance run.

Run `git lfs pull` after cloning, then run `powershell -ExecutionPolicy Bypass -File .\scripts\setup-team.ps1`.

The bundle deliberately excludes API keys. Each teammate must configure `.env.local` locally.
