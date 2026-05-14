# Flask Reference Prototype

This folder contains the retired Python/Flask prototype that was used to prove
the data model, parser contract, routing logic, SQL safety rules, and regression
tests before the Android app became the product surface.

The active app is now `android/`. This prototype remains useful as design
history and as a reference for parser/database experiments, but it is not the
shipping target.

## Contents

- Flask screens in `templates/` and `static/`
- Python orchestration and SQL helpers
- MCP experiment files
- historical fine-tuned parser runtime helpers
- early Jupyter notebooks under `notebooks/`
- regression tests under `tests/`

## Local Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The local SQLite database is ignored by Git and can be regenerated from
`seed.sql` or the notebooks.

Fine-tuned parser adapters are not committed. If you run the retired parser
runtime, point `SECOND_BRAIN_FINETUNED_PARSER_ADAPTER` at a local adapter
folder.
