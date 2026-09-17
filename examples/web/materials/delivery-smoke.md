# UTF-8 file copy: minimal delivery acceptance

Build a minimal Agent Skill for copying a regular UTF-8 text file to another specified path,
preserving its bytes exactly, including whitespace and the final newline.

The user provides both relative paths. Both parent directories exist, and the destination
file does not exist. Inputs are regular files smaller than 1 KB. Other encodings, symlinks,
large files, directory creation, overwriting and rollback policies are outside this task.
No further product decisions are needed. Do not expand the scope to those features.

A concise SKILL.md using standard local file tools is sufficient. No extra scripts, test
frameworks or dependencies are required. Prefer the smallest working skill.

Use exactly one development scenario and one distinct holdout scenario. Each must provide
a short source file and check that the target file's entire contents equal the source.
Use different text in development and holdout. These are synthetic public materials.
