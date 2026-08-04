# Testing

Guardrails fail silently: when a control stops working the chatbot does not raise an error, it just keeps answering unguarded. Tests are how that stays visible.

## Code layout

| File | Contents | Needs the core? |
| --- | --- | --- |
| `checks.py` | All decision logic: thresholds, verdicts, rules. Imports nothing from `cat` | No |
| `settings.py` | The settings model the admin form is built from, and the shipped defaults | Yes |
| `ict_site_rag_guards.py` | The hooks only: read from the Cat, delegate to `checks`, write back | Yes |
| `tests/unit/` | Pure logic and shipped metadata. Plain `pytest`, no Cheshire Cat at all | No |
| `tests/integration/` | Hook wiring and configuration, against a fake `cat` object | Yes |

The test folders are the classification: what goes in `tests/unit/` must import nothing from `cat`, and a file that breaks that rule fails loudly instead of being silently skipped. Everything under `tests/unit/` therefore runs anywhere, which is what makes the fast local loop possible.

`tests/integration/` needs the core only because the module under test imports `cat.log` and `cat.mad_hatter.decorators` at import time, not because a Cat must be running. Those tests never contact a live instance: the container is used as an interpreter, not as a server. Automated tests against a running instance do not exist yet; see `What is not automated` below.

One thing to know before adding files here: the Cat imports every `.py` it finds in the plugin folder, recursively, including `tests/`, and it does so under a package name where a bare `import checks` does not resolve. Left alone, that makes the core log `Unable to load plugin ict-site-rag-guards` on every activation. Both test modules therefore put the plugin folder on `sys.path` before importing, which keeps a genuine breakage failing rather than skipping. It is also why `pytest.ini` and the two runner scripts are deliberately not Python files.

The `@hook` decorator turns functions into non-callable `CatHook` objects. Tests reach the real function through `.function`.

## Environment setup

Two options, depending on which tests you want to run.

Local interpreter, `tests/unit` only:

```bash
python -m pip install pytest
```

Container, whole suite:

```bash
docker compose up -d
```

Add `--build` only after changing the image or the core dependencies: it is not needed to run the plugin or its tests, and it is considerably slower.

## Running the tests

Two equivalent runners live in the plugin root: `run-tests.ps1` for PowerShell and `run-tests.sh` for Linux and macOS. They wrap both environments, take the same three forms, and return pytest's own exit code.

| What it runs | PowerShell | Linux / macOS |
| --- | --- | --- |
| `tests/unit` only, no container | `.\run-tests.ps1 -Unit` | `./run-tests.sh --unit` |
| the whole suite, in the container | `.\run-tests.ps1` | `./run-tests.sh` |
| the whole suite, one line per test | `.\run-tests.ps1 -Detailed` | `./run-tests.sh --detailed` |

Because the exit code is pytest's own, either script can be reused from a git hook or from CI. If a prerequisite is missing, no interpreter with `pytest`, container not running, `compose.yml` not where expected, they say which command fixes it instead of failing obscurely.

The `pre-commit` hook runs `tests/unit` too, and nothing else: a commit must not depend on Docker being up, or the hook would either block legitimate commits or skip in silence. `tests/integration` is for the runners, before pushing.

Two limits of that gate are worth knowing. It runs `pytest` against the files on disk, not against the staged snapshot, so with unstaged changes in the working tree what passes is not exactly what is being committed. And if no interpreter with `pytest` is available it warns and lets the commit through, on the grounds that blocking for a missing development tool teaches `--no-verify`, which would also disable the secret scan.

The shell version also handles two things the PowerShell one never meets: it falls back to the standalone `docker-compose` binary where Compose v2 is not a docker subcommand, and it picks the first interpreter that can actually import `pytest` rather than the first one on `PATH`.

The git hooks deliberately keep referring to the PowerShell runner, because the development machine for this plugin is Windows.

Calling `pytest` directly works too. Locally:

```bash
python -m pytest tests/unit
```

In the container:

```bash
docker compose exec -w /app/cat/plugins/ict-site-rag-guards cheshire-cat-core python -m pytest
```

From Git Bash on Windows that same command fails with `Cwd must be an absolute path`, because the shell rewrites the `-w` path. Prefix it with `MSYS_NO_PATHCONV=1`, which is what `run-tests.sh` does, so it works under Git Bash as well as on Linux.

No `PYTHONPATH` is needed: `pytest.ini` declares `pythonpath = . /app`, where `.` makes the plugin modules importable and `/app` makes the core importable inside the container. A path that does not exist is ignored, so the same file works on a developer machine. Without that second entry `tests/integration/` is skipped rather than failed, which reads as a success.

## What is not automated

Verification against a real instance is currently manual: activate the plugin, send messages through `POST /message`, and read `docker compose logs -f cheshire-cat-core` to confirm which code path ran. A correct-looking answer does not prove it came from this plugin; the log lines do.

This tier matters because it catches what the other two cannot. The interaction with the `Rate Limiter` plugin is the case in point: its checks used to intercept messages before this plugin ever saw them, and nothing in the code of either plugin showed it. The hook priority now settles who answers, and a unit test guards the priority, but the ordering itself is only ever confirmed on a running instance.

The same tier is where another plugin's side effects show up. Above its own `max_prompt_length`, Rate Limiter still records an infraction and suspends the user for 5, 15 or 60 minutes, silently blocking their next legitimate messages, even though the reply delivered is this plugin's. No test can see that either. See `DEV/ISSUES_TODO.md`.
