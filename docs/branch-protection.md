# Негізгі бұтақты қорғау (main)

Settings → Branches → **Add branch ruleset** (немесе *Add classic branch protection rule*), бұтақ: `main`.

| Ереже | Мәні | Неге |
|---|---|---|
| Require a pull request before merging | қосулы | `main`-ге тікелей push жоқ, тек PR арқылы |
| Required approvals | 1 | Кемінде бір ревьюер (команда мүшесі) |
| Dismiss stale approvals when new commits are pushed | қосулы | Жаңа коммиттен кейін ревью қайта қажет |
| Require conversation resolution | қосулы | Ревью ескертулері жабылмай мерж жоқ |
| Require status checks to pass | қосулы | Құбыржол жасыл болмаса мерж жоқ |
| Required checks | `Lint (ruff)`, `Tests (pytest)`, `Security (Trivy, gitleaks)`, `Build and publish image` | CI-дағы job атаулары |
| Require branches to be up to date | қосулы | PR соңғы `main`-мен тексеріледі |
| Block force pushes | қосулы | Тарихты қайта жазуға тыйым |
| Restrict deletions | қосулы | `main`-ді өшіруге тыйым |

Командада бір адам болса, *Required approvals* өз PR-ыңызды бекітуге мүмкіндік бермейді.
Бұл жағдайда approvals = 0 қойып, қалған тексерулерді қалдырыңыз және мұны есепте көрсетіңіз.

## Тексеру

1. `main`-ге тікелей `git push` жасап көріңіз — GitHub бас тартуы керек.
2. Тесті әдейі сындыратын PR ашыңыз — **Merge** батырмасы бұғатталады.
3. Екі нәтиженің де скриншотын есепке қосыңыз.
