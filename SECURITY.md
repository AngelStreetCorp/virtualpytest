# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately** — do not open a public issue or PR.

Preferred: use GitHub's private vulnerability reporting on this repository
(**Security → Report a vulnerability**), which opens a confidential advisory
visible only to maintainers.

If that is unavailable, email the maintainers at **contact@virtualpytest.com**
with:

- a description of the issue and its impact,
- steps to reproduce (proof-of-concept if possible),
- affected component(s) and version/commit.

Please give us a reasonable window to investigate and ship a fix before any
public disclosure. We aim to acknowledge reports within **5 business days** and
to keep you updated as we work on a resolution.

## Scope

VirtualPyTest is a self-hosted testing platform. Security-relevant areas include
the orchestration API (`backend_server`), per-host controllers (`backend_host`),
authentication/authorization, and the web UI (`frontend`).

Out of scope: issues that require already-compromised infrastructure, and the
security of third-party services you connect (Supabase, Grafana, object storage,
LLM providers, etc.) — configure and secure those per their own guidance.

## Handling secrets

Never commit credentials, API keys, or `.env` files. All secrets are supplied
via environment variables (see the `*.env.example` templates). If you discover a
committed secret, report it privately as above so it can be rotated and removed.

## Supported versions

This project is under active development; security fixes are applied to the
latest `main`. Pin to a tagged release if you need stability.
