# Phase 17 fixtures

- `markdown.md` is the source fixture for the public Markdown lane.
- `meeting.vtt` is the source fixture for the public transcript lane.
- `corrupt.bin` is the deterministic invalid-input fixture.
- DOCX, PPTX, and PDF containers are generated in each test temporary directory from the existing deterministic document fixture generator, so binary artifacts do not obscure the regression source review.
