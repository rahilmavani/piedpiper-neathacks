# Culprit

`git bisect` for agent behaviour, with receipts.

Give Culprit a good ref, a bad ref and an eval suite. It finds the commit that broke your agent, explains why that change was made (from the Entire session), proposes the smallest fix that restores quality while keeping the intended gain, and verifies it statistically.

Team PiedPiper, neatHack 2026. Work in progress: see `PRD.md` for the spec and `hackathon.md` for the build log.

## Status

Bootstrap complete. Culprit build (M1) starts next.
