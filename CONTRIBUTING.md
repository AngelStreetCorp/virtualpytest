# Contributing to VirtualPyTest

Thanks for your interest in contributing to VirtualPyTest.

VirtualPyTest is an open-source test automation and monitoring platform for TVs, set-top boxes, mobile devices, web applications, and other screen-based devices.

Contributions are welcome — from bug reports and documentation fixes to new device support and platform features.

## Ways to contribute

You do not need to write code to contribute.

* **Report a bug** — describe what happened, what you expected, and how to reproduce it.
* **Suggest a feature** — explain the problem or workflow you want to improve.
* **Improve documentation** — fix unclear, incomplete, or outdated information.
* **Submit a fix or feature** — open a pull request with a focused change.
* **Add device support** — new controllers and integrations are welcome.

For larger changes, consider opening an issue or discussion first so the approach can be agreed before significant work begins.

## Get started

Fork the repository, clone your fork, and create a branch from `main`.

```bash
git clone https://github.com/<your-username>/virtualpytest.git
cd virtualpytest

git checkout -b feat/short-description
```

For a development environment, follow the [Developer setup guide](docs/get-started/local-dev.md).

For a standard Docker installation, see the [Docker setup guide](docs/get-started/docker.md).

## Development workflow

1. Create a branch from `main`.
2. Make one focused change.
3. Add or update tests where appropriate.
4. Update documentation if behavior or configuration changes.
5. Run the relevant checks locally.
6. Push your branch.
7. Open a pull request against `main`.

Common branch prefixes:

```text
feat/     new functionality
fix/      bug fixes
docs/     documentation
refactor/ internal improvements
test/     tests
```

Clear branch names are more important than following this convention exactly.

## Before opening a pull request

Run the checks relevant to the part of the project you changed.

For backend changes:

```bash
python -m pytest tests/backend_server
```

For frontend changes, from `frontend/`:

```bash
npm run lint
npm run typecheck
npm run test
```

Run the production build when your change affects frontend behavior or dependencies:

```bash
npm run build
```

See the [CI documentation](docs/get-started/ci_cd.md) for the full project checks.

## Pull request guidelines

Please:

* Keep each pull request focused on one logical change.
* Explain what changed and why.
* Link the related issue when there is one.
* Include screenshots for visible UI changes.
* Add or update tests for behavior changes where practical.
* Update documentation when behavior, configuration, APIs, or installation steps change.
* Avoid unrelated formatting or refactoring in the same pull request.

Small, focused pull requests are generally easier to review.

## Adding device support

New device controllers and integrations are welcome.

Before starting a larger device integration, review the existing controllers and the [Controller Creation Guide](docs/technical/architecture/CONTROLLER_CREATION_GUIDE.md).

For substantial new integrations, opening an issue or discussion first is recommended.

## Documentation

Documentation improvements are welcome and can be submitted like any other contribution.

Most documentation lives under [`docs/`](docs/).

Useful starting points:

* [Developer setup](docs/get-started/local-dev.md)
* [Documentation index](docs/README.md)
* [API documentation](docs/api/README.md)
* [Architecture documentation](docs/technical/)
* [CI documentation](docs/get-started/ci_cd.md)

## Secrets and generated files

Do not commit:

* passwords or API keys;
* access tokens;
* private certificates or keys;
* populated `.env` files;
* customer or device credentials;
* virtual environments;
* `node_modules`;
* generated build artifacts unless the repository explicitly tracks them.

Use the provided `.env.example` files as configuration templates.

If a secret is accidentally committed, treat it as exposed and rotate it.

## Security vulnerabilities

Please do **not** report security vulnerabilities through a public GitHub issue or discussion.

Follow [SECURITY.md](SECURITY.md) for private disclosure instructions.

## Questions

Use GitHub Discussions for questions, ideas, or larger design discussions.

Use GitHub Issues for confirmed bugs and actionable feature requests.

## License

By contributing to VirtualPyTest, you agree that your contributions are licensed under the same terms as the project.

See [LICENSE](LICENSE) for the full terms.
