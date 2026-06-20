# Example task: login-redirect

A throwaway target repo + a Spec Kit-style `tasks.md` and `bounds.json`, used to drive
the short loop. The L4 clone sandbox needs `repo/` to be a git repo, so initialize
it once:

```bash
cd repo && git init -q && git add -A && git commit -qm init && cd ..
```

Then, from the sembl-stack root:

```bash
sembl-stack run examples/tasks/login-redirect/task.yaml
```

Expected: the mock executor wanders out of scope on attempt 1 (**BLOCK**), gets the
gate's reasons fed back, behaves on attempt 2 (**PASS**).

## Driving a real agent (OpenCode)

Swap the executor and name a model in `sembl.stack.yaml`:

```yaml
layers:
  execute: opencode
options:
  execute:
    model: tokenrouter/MiniMax-M3   # provider/model as `opencode models` lists it
    timeout: 1200
```

The adapter runs `opencode run --pure --dangerously-skip-permissions <prompt>` inside the
sandbox: `--pure` ignores the operator's personal plugins/skills so the agent is driven
only by the task + bounds we hand it, and `--dangerously-skip-permissions` lets it edit
files headlessly (safe — the sandbox is a disposable clone, and the diff is what gets
gated). Requires `opencode` on PATH with the chosen provider authenticated.

## Or run the stages independently (partial use / mid-entry)

```bash
sembl-stack bounds  --task task.yaml                       --out bounds.json   # L2
sembl-stack execute --task task.yaml --bounds bounds.json  --out change.json   # L3
sembl-stack verify  --change change.json --bounds bounds.json                  # L5
```

Stop after any stage; insert your own step between two (read the upstream artifact, write
the downstream one). The gate also runs on a raw diff with nothing else involved (the
adoption wedge):

```bash
sembl-stack verify --diff my.patch --bounds bounds.json   # PASS/WARN -> exit 0, BLOCK -> 1
```

