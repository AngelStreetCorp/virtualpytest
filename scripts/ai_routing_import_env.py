#!/usr/bin/env python3
"""
One-time import of the pre-TASK-30 AI configuration into the AI routing tables.

Before TASK-30 the model for each AI call came from env vars (AI_PROVIDER,
AI_{AGENT,VISION,TEXT}_{PROVIDER,MODEL}, LOCAL_AI_*, ANALYZER_OPENROUTER_MODEL,
DOM_MODEL/DOM_EFFORT) plus provider keys (*_API_KEY), and two call sites were
pinned in code (public Ask → MiniMax, DOM generation → OpenAI gpt-5.5 / OpenRouter).
This script reproduces exactly that behaviour as server-default routes, so the
code switch changes nothing until someone edits Settings → AI:

  * provider keys      → server-side secrets store (ai_secrets.json)
  * providers in use   → ai_endpoints (anthropic/openrouter are seeded by the migration)
  * task models        → ai_profiles + the server-default root routes agent/vision/text
  * Sherlock override  → route analyzer.sherlock
  * DOM generator      → route vision.dom (with the GPT-5 reasoning flags)
  * public docs Ask    → route public.ask on MiniMax (flat-rate quota)
  * MCP screenshot VLM → route vision.screenshot (VLM_PROVIDER: minimax coding-plan VLM by default)
  * MCP prompt proxy   → route agent.mcp_prompt (OpenRouter google/gemini-2.5-pro)
  * browser-use agent  → route agent.browser (OpenRouter o4-mini, temperature 1.0)

Run ON THE SERVER after applying setup/db/migrations/20260929e_ai_routing.sql and
BEFORE deploying the TASK-30 code. Idempotent: re-running updates the same rows.

    python3 scripts/ai_routing_import_env.py --dry-run
    python3 scripts/ai_routing_import_env.py
    python3 scripts/ai_routing_import_env.py --host-env /path/to/host/.env

Vision and text calls ran on the hosts, so their provider/model came from the HOST
.env: pass one representative host .env with --host-env (its AI_VISION_* / AI_TEXT_*
/ LOCAL_AI_* / keys are used for those tasks). Agents ran on the server (server .env).

Afterwards remove the listed env keys from the .env files (the settings API refuses
to write them back).
"""

from __future__ import annotations

import argparse
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Pre-TASK-30 behaviour, frozen here: which provider served each task by default and
# which model each provider used per task (shared/src/lib/ai/config.py before TASK-30).
OLD_DEFAULT_PROVIDER_BY_TASK = {'agent': 'anthropic', 'vision': 'openrouter', 'text': 'openrouter'}
OLD_PROVIDER_MODELS = {
    'anthropic': {'agent': 'claude-sonnet-4-20250514', 'vision': 'claude-sonnet-4-20250514',
                  'text': 'claude-sonnet-4-20250514'},
    'openrouter': {'agent': 'openai/gpt-4.1-mini', 'vision': 'qwen/qwen3-vl-8b-instruct',
                   'text': 'openai/gpt-4.1-mini'},
    'openai': {'agent': 'gpt-4.1-mini', 'vision': 'gpt-4.1-mini', 'text': 'gpt-4.1-mini'},
    'minimax': {'agent': 'MiniMax-M2.7-highspeed', 'vision': None, 'text': 'MiniMax-M2.7-highspeed'},
    'google': {'agent': 'gemini-2.5-flash', 'vision': 'gemini-2.5-flash', 'text': 'gemini-2.5-flash'},
    'local': {'agent': None, 'vision': None, 'text': None},
}
KEY_ENV = {'anthropic': 'ANTHROPIC_API_KEY', 'openrouter': 'OPENROUTER_API_KEY', 'openai': 'OPENAI_API_KEY',
           'minimax': 'MINIMAX_API_KEY', 'minimax_vlm': 'MINIMAX_API_KEY', 'google': 'GOOGLE_API_KEY',
           'local': 'LOCAL_AI_API_KEY'}
# Provider name (old) -> endpoint name + preset (new).
ENDPOINTS = {'anthropic': ('anthropic', 'anthropic'), 'openrouter': ('openrouter', 'openrouter'),
             'openai': ('openai', 'openai'), 'minimax': ('minimax', 'minimax'),
             'minimax_vlm': ('minimax-vlm', 'minimax_vlm'), 'google': ('google', 'google'),
             'local': ('local', 'openai_compatible')}
CAPS = {'anthropic': ['tools', 'vision'], 'openai': ['tools', 'vision'], 'google': ['tools', 'vision'],
        'minimax': ['tools'], 'minimax_vlm': ['vision'], 'openrouter': [], 'local': []}
DOM_EXTRA = {'max_tokens_param': 'max_completion_tokens', 'omit_temperature': True,
             'response_format': {'type': 'json_object'}}
REMOVED_ENV_KEYS = ['AI_PROVIDER', 'AI_AGENT_PROVIDER', 'AI_AGENT_MODEL', 'AI_VISION_PROVIDER',
                    'AI_VISION_MODEL', 'AI_TEXT_PROVIDER', 'AI_TEXT_MODEL', 'LOCAL_AI_BASE_URL',
                    'LOCAL_AI_MODEL', 'LOCAL_AI_API_KEY', 'LOCAL_AI_TIMEOUT', 'ANALYZER_OPENROUTER_MODEL',
                    'DOM_MODEL', 'DOM_EFFORT', 'VLM_PROVIDER', 'VLM_PROVIDER_FALLBACK', 'VLM_TIMEOUT_SECONDS',
                    'OPENAI_VLM_MODEL', 'ANTHROPIC_VLM_MODEL', 'GEMINI_VLM_MODEL', 'GEMINI_API_KEY']
# The MCP screenshot tool read the Gemini key as GEMINI_API_KEY.
KEY_ALIASES = {'google': ('GOOGLE_API_KEY', 'GEMINI_API_KEY')}


def parse_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def old_provider(env: dict, task: str) -> str:
    """Pre-TASK-30 resolution: AI_<TASK>_PROVIDER -> AI_PROVIDER if it can serve -> default."""
    explicit = env.get(f'AI_{task.upper()}_PROVIDER', '').strip().lower()
    if explicit:
        return explicit
    primary = env.get('AI_PROVIDER', '').strip().lower()
    if primary and (primary == 'local' or OLD_PROVIDER_MODELS.get(primary, {}).get(task)):
        return primary
    return OLD_DEFAULT_PROVIDER_BY_TASK[task]


def old_model(env: dict, provider: str, task: str) -> str | None:
    configured = env.get(f'AI_{task.upper()}_MODEL', '').strip()
    if provider == 'local':
        model = configured or env.get('LOCAL_AI_MODEL', '').strip()
    else:
        model = configured or OLD_PROVIDER_MODELS.get(provider, {}).get(task)
    if model and provider not in ('openrouter', 'local') and '/' in model:
        model = model.split('/', 1)[1]
    return model or None


def slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')[:60]


class Importer:
    def __init__(self, env: dict, host_env: dict, dry_run: bool):
        from shared.src.lib.database import ai_routing_db
        from shared.src.lib.ai import secrets_store
        self.db = ai_routing_db
        self.secrets = secrets_store
        self.env = env
        # Vision/text ran on hosts: their config wins for those tasks when provided.
        self.host_env = {**env, **host_env} if host_env else env
        self.dry = dry_run
        self.endpoints = {e['name']: e for e in ai_routing_db.list_endpoints()}
        self.profiles = {p['name']: p for p in ai_routing_db.list_profiles()}
        self.routes = [r for r in ai_routing_db.list_routes(None)]
        self.log: list[str] = []

    def say(self, line: str) -> None:
        self.log.append(line)
        print(('[dry-run] ' if self.dry else '') + line)

    def key(self, provider: str) -> str:
        for env_name in KEY_ALIASES.get(provider, (KEY_ENV[provider],)):
            value = self.env.get(env_name, '').strip()
            if value:
                return value
        return ''

    def endpoint(self, provider: str) -> dict:
        name, preset = ENDPOINTS[provider]
        existing = self.endpoints.get(name)
        fields: dict = {'name': name, 'preset': preset}
        if provider == 'local':
            fields['base_url'] = self.env.get('LOCAL_AI_BASE_URL', '').strip().rstrip('/')
            if not fields['base_url']:
                raise SystemExit('❌ A task uses the local provider but LOCAL_AI_BASE_URL is empty')
            timeout = self.env.get('LOCAL_AI_TIMEOUT', '').strip()
            fields['timeout_s'] = int(timeout) if timeout.isdigit() else 300
        key = self.key(provider)
        if key:
            fields['secret_name'] = name
        if existing:
            updates = {k: v for k, v in fields.items() if existing.get(k) != v}
            if updates:
                self.say(f'endpoint {name}: update {sorted(updates)}')
                if not self.dry:
                    existing = self.db.update_row('ai_endpoints', existing['id'], updates) or existing
        else:
            self.say(f'endpoint {name}: create ({preset})')
            existing = {**fields, 'id': f'dry-{name}'} if self.dry else self.db.create_row('ai_endpoints', fields)
        if key:
            self.say(f'secret {name}: from {"/".join(KEY_ALIASES.get(provider, (KEY_ENV[provider],)))}')
            if not self.dry:
                self.secrets.set_secret(name, key)
        self.endpoints[name] = existing
        return existing

    def profile(self, provider: str, model: str, *, name: str | None = None, extra: dict | None = None,
                capabilities: list[str] | None = None, temperature: float | None = None) -> dict:
        endpoint = self.endpoint(provider)
        name = name or f'{ENDPOINTS[provider][0]}-{slug(model)}'
        fields = {'name': name, 'endpoint_id': endpoint['id'], 'model': model,
                  'capabilities': capabilities if capabilities is not None else CAPS.get(provider, [])}
        if extra:
            fields['extra'] = extra
        if temperature is not None:
            fields['temperature'] = temperature
        # Reuse a seeded profile that already points at this endpoint + model.
        existing = self.profiles.get(name) or next(
            (p for p in self.profiles.values() if p['endpoint_id'] == endpoint['id'] and p['model'] == model
             and not extra and temperature is None), None)
        if existing:
            return existing
        self.say(f'profile {name}: create ({model} on {endpoint["name"]})')
        created = {**fields, 'id': f'dry-{name}'} if self.dry else self.db.create_row('ai_profiles', fields)
        self.profiles[name] = created
        return created

    def route(self, usage: str, profile: dict) -> None:
        existing = next((r for r in self.routes if r['usage_key'] == usage and not r.get('team_id')
                         and not r.get('host_name') and not r.get('device_model')
                         and not r.get('userinterface_name')), None)
        if existing:
            if existing['profile_id'] == profile['id']:
                self.say(f'route {usage}: already → {profile["name"]}')
                return
            self.say(f'route {usage}: repoint → {profile["name"]}')
            if not self.dry:
                self.db.update_row('ai_routes', existing['id'], {'profile_id': profile['id']})
            return
        self.say(f'route {usage}: create → {profile["name"]}')
        if not self.dry:
            self.routes.append(self.db.create_row('ai_routes', {'team_id': None, 'usage_key': usage,
                                                                'profile_id': profile['id']}))

    def run(self) -> None:
        env = self.env
        for task in ('agent', 'vision', 'text'):
            task_env = env if task == 'agent' else self.host_env
            provider = old_provider(task_env, task)
            if provider not in ENDPOINTS:
                raise SystemExit(f'❌ Unknown provider "{provider}" for task {task}')
            model = old_model(task_env, provider, task)
            if not model:
                raise SystemExit(f'❌ No model for task {task} on provider {provider} '
                                 f'(set AI_{task.upper()}_MODEL or LOCAL_AI_MODEL before importing)')
            self.route(task, self.profile(provider, model))

        sherlock_model = env.get('ANALYZER_OPENROUTER_MODEL', '').strip()
        if sherlock_model:
            self.route('analyzer.sherlock', self.profile('openrouter', sherlock_model))

        # DOM generator: OpenAI gpt-5.5 (reasoning) when an OpenAI key exists, else OpenRouter.
        if env.get('OPENAI_API_KEY', '').strip():
            effort = (env.get('DOM_EFFORT', '').strip() or 'medium').lower()
            dom_model = env.get('DOM_MODEL', '').strip() or 'gpt-5.5'
            self.route('vision.dom', self.profile('openai', dom_model, name=f'dom-{slug(dom_model)}',
                                                  extra={**DOM_EXTRA, 'reasoning_effort': effort},
                                                  capabilities=['vision']))
        elif env.get('OPENROUTER_API_KEY', '').strip():
            dom_model = env.get('DOM_MODEL', '').strip() or 'qwen/qwen3-vl-235b-a22b-instruct'
            self.route('vision.dom', self.profile('openrouter', dom_model,
                                                  extra={'response_format': {'type': 'json_object'}},
                                                  name=f'dom-{slug(dom_model)}', capabilities=['vision']))

        # Public docs Ask was pinned to MiniMax (flat subscription).
        if env.get('MINIMAX_API_KEY', '').strip():
            model = (old_model(env, 'minimax', 'agent') if old_provider(env, 'agent') == 'minimax'
                     else None) or 'MiniMax-M2.7-highspeed'
            self.route('public.ask', self.profile('minimax', model))

        # MCP capture_screenshot(vlm=true) description, picked by VLM_PROVIDER (default minimax).
        vlm = (env.get('VLM_PROVIDER', '').strip() or 'minimax').lower()
        vlm_targets = {
            'minimax': ('minimax_vlm', 'minimax-vlm'),
            'openai': ('openai', env.get('OPENAI_VLM_MODEL', '').strip() or 'gpt-4o-mini'),
            'anthropic': ('anthropic', env.get('ANTHROPIC_VLM_MODEL', '').strip() or 'claude-haiku-4-5-20251001'),
            'gemini': ('google', env.get('GEMINI_VLM_MODEL', '').strip() or 'gemini-2.5-flash'),
        }
        if vlm in vlm_targets and self.key(vlm_targets[vlm][0]):
            provider, model = vlm_targets[vlm]
            self.route('vision.screenshot', self.profile(provider, model, capabilities=['vision']))
        elif vlm == 'tesseract':
            self.say('vision.screenshot: VLM_PROVIDER=tesseract has no AI equivalent — it inherits the vision '
                     'route; tesseract still runs when that AI call fails')

        # MCP prompt proxy and the browser-use agent were pinned to OpenRouter models.
        if self.key('openrouter'):
            self.route('agent.mcp_prompt', self.profile('openrouter', 'google/gemini-2.5-pro',
                                                        capabilities=['tools']))
            self.route('agent.browser', self.profile('openrouter', 'o4-mini', name='openrouter-o4-mini-t1',
                                                     temperature=1.0, capabilities=['tools', 'vision']))

        # Keys for providers present in env but not routed yet — keep them usable.
        for provider in ('anthropic', 'openrouter', 'openai', 'minimax', 'google'):
            if self.key(provider) and ENDPOINTS[provider][0] not in self.endpoints:
                self.endpoint(provider)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='print the plan, change nothing')
    parser.add_argument('--server-env', default=os.path.join(PROJECT_ROOT, '.env'),
                        help='the server .env (default: this checkout .env; pass /opt/virtualpytest/.env '
                             'when running from a copy before the code deploy)')
    parser.add_argument('--host-env', default=None,
                        help='a host .env: vision/text config and keys the hosts used')
    args = parser.parse_args()

    server_env = parse_env(args.server_env)
    if not server_env:
        raise SystemExit(f'❌ {args.server_env} is empty or missing')
    host_env = parse_env(args.host_env) if args.host_env else {}
    if args.host_env and not host_env:
        raise SystemExit(f'❌ {args.host_env} is empty or missing')
    for key, value in server_env.items():
        os.environ.setdefault(key, value)  # DB credentials for the supabase client
    # Keys: anything either side held (server wins on conflict).
    env = {**host_env, **server_env}

    importer = Importer(env, host_env, args.dry_run)
    importer.run()

    present = [k for k in REMOVED_ENV_KEYS if k in env]
    print('\nDone.' if not args.dry_run else '\nDry run only — nothing written.')
    if present:
        print('Remove these keys from the .env files (no longer read): ' + ', '.join(present))
    key_names = sorted({v for v in KEY_ENV.values() if v in env})
    if key_names:
        print('Provider keys now live in ~/.config/virtualpytest/ai_secrets.json; '
              'remove them from host .env files: ' + ', '.join(key_names))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
