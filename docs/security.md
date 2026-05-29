# Security And Secret Handling

EGM is a local Python library, but its examples and benchmark adapters can call
external model APIs. Credentials must stay outside the repository.

## Rules

- Never commit real API keys, bearer tokens, GitHub tokens, cloud credentials, or
  provider secrets.
- Keep real credentials in the shell environment, a local `.env` file, or a
  secret manager.
- Commit only `.env.example`.
- Benchmark reports may record provider names, model names, dates, sample sizes,
  and costs. They must not record raw secrets.
- Public benchmark commands should show placeholders such as
  `DEEPSEEK_API_KEY=...`, never a real key.

## Local Setup

Copy the template if you want a local dotenv-style file:

```powershell
Copy-Item .env.example .env
```

Then fill only the keys needed for the run:

```powershell
$env:DEEPSEEK_API_KEY="..."
python examples/deepseek_refund_agent/run.py
```

The deterministic examples and local benchmark suite do not need API keys:

```powershell
python examples/deepseek_refund_agent/run.py --mock
python benchmarks/run_local.py
```

## Secret Scan

Run this before committing benchmark or example changes:

```powershell
python scripts/scan_secrets.py
```

The scanner is intentionally lightweight and dependency-free. It checks common
provider key shapes and literal secret assignments in text files. It is not a
replacement for GitHub secret scanning or a dedicated tool such as gitleaks, but
it is fast enough to run in CI and catches the failure mode EGM has already hit:
accidentally hardcoding a model API key in a benchmark script.
