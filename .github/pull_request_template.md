## What and why

<!-- What does this change, and why? Link the issue it closes: "Closes #123". -->

## How it was checked

<!-- Tick what applies. Say what you tried by hand in Firefox, with your Firefox build and desktop. -->

- [ ] `pytest` passes, and `ruff check .`, `ruff format --check .` and `mypy` are clean
- [ ] For changes to `chrome/`: `pytest -m browser` passes (it needs Firefox and network access)
- [ ] For changes to `chrome/`: I tried it by hand in a real Firefox (hover and real drags can't be simulated headless)
- [ ] A bug fix comes with the test that would have caught it

## Housekeeping

- [ ] The pull request title follows [Conventional Commits](https://www.conventionalcommits.org/) (`feat(css): ...`, `fix: ...`)
- [ ] `README.md` and `README.pt-BR.md` are both updated, if the docs changed
- [ ] The target branch is `devel/devel` (only `devel/devel` goes into `main`)
