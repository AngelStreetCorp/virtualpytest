# Translation glossary (fr / de)

Keys in `t()` are the English source text; `locales/fr.json` and `locales/de.json` are flat
`{ "English": "translation" }`, sorted keys. Formal register: "vous" / "Sie".
Keep `{placeholders}` exactly as written. Product names stay untranslated: VirtualPyTest, Atlas,
Grafana, Jira, TestRail, Slack, Langfuse, MinIO.

| English | Français | Deutsch |
|---|---|---|
| Device | Appareil | Gerät |
| Host | Hôte | Host |
| Test case | Cas de test | Testfall |
| Campaign | Campagne | Kampagne |
| Run | Exécution | Ausführung |
| Report | Rapport | Bericht |
| Navigation tree | Arbre de navigation | Navigationsbaum |
| Node | Nœud | Knoten |
| Edge | Transition | Übergang |
| Workspace | Espace de travail | Arbeitsbereich |
| Settings | Paramètres | Einstellungen |
| Dashboard | Tableau de bord | Dashboard |
| Interface | Interface | Oberfläche |

Notes
- Same English, different meaning: use a context, `t('Run', { context: 'nav' })` has the key `Run#nav`.
- Plurals: the key is the English plural form; the catalog value is a string or `{ "one": "…", "other": "…" }`.
- German is about 30% longer than English: leave room in fixed-width controls.
