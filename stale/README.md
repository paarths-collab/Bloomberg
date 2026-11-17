# stale/

Legacy code that nothing in the live product references. It is kept here
instead of being deleted so it stays easy to browse and recover.

- It is NOT imported, built, tested or deployed. Nothing outside this folder
  should import from it (paths mirror the original locations, e.g.
  `backend/markets/core/config.py` is now `stale/backend/markets/core/config.py`).
- Everything was moved with `git mv`, so `git log --follow <path>` keeps history.
- Everything is also recoverable as it was at commit `08d480d` (the commit
  just before this move), e.g. `git show 08d480d:backend/fix3.py`.

## Categories

- `backend/` - duplicated or orphaned backend modules: per-package `core/config.py`
  copies, `data_loader.py` and `fred_data_service.py` copies, superseded
  services (`old_fred_*`, `news/*_service.py` duplicates, `network/service.py`,
  `peers/core/*`, `screener/core/screener_service.py`, ...), unused agent and
  Monte Carlo helpers, audit/fix one-offs, and empty placeholder packages
  (`analytics`, `records`, `profile/core`, `screener/core`).
- `scripts/` - one-off rewrite/repair scripts (`fix.py`, `fix2.py`,
  `localize.py`, `auto_fix.py`) and vendored libraries (`peewee.py`,
  `pwiz.py`, `six.py`). Do not run `auto_fix.py`: it edits source files.
- `app/` and `boomerang-trading/` - unbuildable Next.js leftovers at the repo root
  (the real frontend is `frontend/`).
- `frontend/` - unused chat components (`ChatCommandBar`, `ChatFeatureCards`,
  `ChatSidebar`), unused `animations/LaserFlow` components, an old
  `.checkpoints/` snapshot, and unreferenced `public/world-map*` images.
- `test_output.txt`, `test_output_full.txt` - old captured test logs.
- `outputs/` - generated KPI/Q-table result files (JSON/TXT) written by
  `scripts/bloomberg_kpi_test.py` and `train_rl_qtable.py` (their default output
  directory is `outputs/` at the repo root). Nothing reads them; the scripts
  regenerate them on demand.
