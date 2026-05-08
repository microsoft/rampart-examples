# RAMPART Examples

Runnable showcases of [RAMPART](https://github.com/microsoft/RAMPART): the pytest-native
safety and security testing framework for agentic AI applications.

Each subdirectory is a self-contained demo. Pick one, follow its
`README.md`, and you'll have a red -> fix -> green walkthrough running in
minutes. Each demo declares its own dependencies, manifest, surface,
adapter, and tests; nothing here at the repo root is required at runtime.

## Demos

| Demo | What it shows |
|---|---|
| [helpdesk-bot](helpdesk-bot/README.md) | Indirect prompt injection (XPIA) via a poisoned support ticket. Single-`git apply` red -> green walkthrough. |

## Repository layout

```
rampart-examples/
├── README.md                # this file
├── pyproject.toml           # shared tooling config (ruff, ty, smoke-test pytest)
├── .pre-commit-config.yaml  # shared lint/format hooks (SHA-pinned)
├── .github/workflows/       # public CI: lint, smoke, patch round-trip
├── tests/                   # maintainer smoke tests (no LLM, no API keys)
└── <demo-name>/             # one folder per demo, fully self-contained
    ├── README.md            # walkthrough for THIS demo (the canonical artifact)
    ├── pyproject.toml       # demo's own dependencies and pytest config
    ├── <package_name>/      # the demo's installable Python package (flat layout)
    ├── tests/               # demo-local pytest fixtures + RAMPART tests
    └── mitigation.patch     # the unified-diff fix
```

## For maintainers

The `tests/` directory contains a fast smoke suite that exercises every
demo's deterministic pieces (imports, manifests, surface lifecycle,
predicates, mitigation-patch applicability) without making any LLM
call. The repo is a uv workspace; `uv sync` installs every demo plus
the maintainer toolchain.

```bash
uv sync
uv run pytest
```

Demo users running `pytest` from inside a demo folder never see this
suite; each demo's own `pyproject.toml` scopes pytest to its own
directory.

Public CI (lint + smoke + patch round-trip) runs in GitHub Actions on
every PR. Live integration tests against real OpenAI / Azure OpenAI
endpoints run in an internal Azure DevOps pipeline; see
[`.azure-pipelines/README.md`](.azure-pipelines/README.md).

## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
